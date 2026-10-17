"""Run the EPUB->AZW3/MOBI web app headlessly (Playwright Chromium) and collect outputs.

Contract: see schema.md.  Writes <out_dir>/ours.<fmt> and <out_dir>/ours.<fmt>.meta.json
({app_version, app_sha, ms, status_text, console_errors, error, chapters_reported, skipped_chapters}).

Cache: a stored result is reused only when its `app_sha` (sha256 over docs/index.html +
docs/jszip.min.js) equals the current one, so uncommitted app edits invalidate outputs. Errors raised
by the harness itself (stored as "harness: ...") and timeouts are never reused.
"""
# Broad `except Exception` (and silent cleanup) is deliberate: the harness contract is that one bad
# book or one flaky tool never aborts a corpus run; failures are recorded in the result instead.
# ruff: noqa: BLE001, S110
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Self

from common import ROOT, default_timeout, entry_path, select_entries, write_json_atomic

DOCS = ROOT / "docs"
APP_FILES = ("index.html", "jszip.min.js")  # everything the conversion code depends on

__all__ = ["AppRunner", "app_sha", "app_version", "default_timeout", "entry_path", "select_entries",
           "start_server"]


# ── helpers ────────────────────────────────────────────────────────────────

def app_version(root: Path = ROOT) -> str:
    """Grep `const APP_VERSION = '...'` from docs/index.html."""
    text = (Path(root) / "docs" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const\s+APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not m:
        raise RuntimeError("APP_VERSION not found in docs/index.html")
    return m.group(1)


def app_sha(root: Path = ROOT) -> str:
    """sha256 over docs/index.html + docs/jszip.min.js (cache key: changes with any app edit)."""
    h = hashlib.sha256()
    for name in APP_FILES:
        f = Path(root) / "docs" / name
        h.update(name.encode() + b"\0")
        h.update(f.read_bytes() if f.exists() else b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


class _SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def start_server(docs: Path = DOCS):
    httpd = HTTPServer(("localhost", 0), partial(_SilentHandler, directory=str(docs)))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://localhost:{port}"


MAX_DOWNLOADS_PER_PAGE = 8

_DONE_JS = (
    '() => { const s = document.getElementById("status"); '
    'return !!s && /\\b(ok|error)\\b/.test(s.className); }'
)


class AppRunner:
    """Context manager: HTTP server on docs/ + one headless Chromium/context/page."""

    def __init__(self, root: Path = ROOT, headless: bool = True):
        self.root = Path(root)
        self.headless = headless
        self.version = app_version(self.root)
        self.app_sha = app_sha(self.root)
        self._console: list[str] = []
        self._warnings: list[str] = []
        self._fresh = False  # page already navigated to the app
        self._downloads = 0  # downloads on the current page (Chromium throttles after 10)
        self.httpd = self.base_url = None
        self._pw = self._browser = self._ctx = self.page = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> Self:
        from playwright.sync_api import sync_playwright
        self.httpd, self.base_url = start_server(self.root / "docs")
        self._pw = sync_playwright().start()
        self._launch()
        return self

    def __exit__(self, *exc) -> None:
        self._close_browser()
        for fn in (lambda: self._pw.stop(), lambda: self.httpd.shutdown()):
            try:
                fn()
            except Exception:
                pass

    def _launch(self) -> None:
        self._browser = self._pw.chromium.launch(headless=self.headless)
        # service workers blocked: no stale cache between app versions
        self._ctx = self._browser.new_context(accept_downloads=True, service_workers="block")
        self.page = None
        self._new_page()
        self._fresh = False

    def _close_browser(self) -> None:
        for fn in (lambda: self._ctx.close(), lambda: self._browser.close()):
            try:
                fn()
            except Exception:
                pass
        self._ctx = self._browser = self.page = None

    def _relaunch(self) -> None:
        """After a harness-side failure the browser/context may be wedged or gone: start over."""
        self._close_browser()
        self._launch()

    def _new_page(self) -> None:
        if self.page is not None:
            try:
                self.page.close(run_before_unload=False)
            except Exception:
                pass
        self.page = self._ctx.new_page()
        self._downloads = 0
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda e: self._console.append(f"pageerror: {e}"))
        self.page.on("crash", lambda *_: self._console.append("pageerror: page crashed"))

    def _on_console(self, m) -> None:
        if m.type == "error":
            self._console.append(f"console.error: {m.text}")
        elif m.type == "warning":
            self._warnings.append(m.text)

    def _recycle_page(self) -> None:
        """Close the (possibly wedged) page and open a fresh one on the app."""
        self._new_page()
        self.page.goto(self.base_url, wait_until="load", timeout=30000)
        self._fresh = True

    def _ready_page(self) -> None:
        """Reuse the page between books (handleFile/convertToAzw3 reset their own state)."""
        # Chromium silently drops the 11th click-triggered download on a page, so recycle early
        if not self._fresh or self._downloads >= MAX_DOWNLOADS_PER_PAGE:
            self._recycle_page()

    # -- conversion --------------------------------------------------------
    def convert(self, entry: dict, fmt: str, out_dir: Path, *, timeout_s: int | None = None,
                force: bool = False) -> dict:
        timeout_s = timeout_s or default_timeout(entry)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"ours.{fmt}"
        meta_file = out_dir / f"ours.{fmt}.meta.json"

        # cache: same app files and (output exists, or a definitive app error was recorded)
        if not force and meta_file.exists():
            try:
                cached = json.loads(meta_file.read_text(encoding="utf-8"))
                if cached.get("app_sha") == self.app_sha:
                    err = cached.get("error")
                    if out_file.exists() and not err:
                        return cached
                    if (not out_file.exists() and err and err != "timeout"
                            and not str(err).startswith("harness:")):
                        return cached
            except Exception:
                pass

        meta = {"app_version": self.version, "app_sha": self.app_sha, "ms": None, "status_text": "",
                "console_errors": [], "error": None,
                "chapters_reported": None, "skipped_chapters": []}
        for stale in (out_file, meta_file):
            if stale.exists():
                stale.unlink()
        try:
            self._convert_into(entry, fmt, out_file, meta, timeout_s)
        except Exception as e:  # never raise for a single book
            meta["error"] = meta["error"] or f"harness: {type(e).__name__}: {str(e)[:500]}"
            if out_file.exists() and meta["error"]:
                out_file.unlink()
            # the page, the context or the whole browser may be wedged or gone: start a new one
            try:
                self._relaunch()
            except Exception as e2:
                self._fresh = False
                meta["error"] += f" | relaunch failed: {type(e2).__name__}: {str(e2)[:200]}"
        meta["console_errors"] = list(self._console)
        meta["skipped_chapters"] = [w.split("Skip chapter:", 1)[1].strip()
                                    for w in self._warnings if "Skip chapter:" in w]
        write_json_atomic(meta_file, meta)
        return meta

    def _convert_into(self, entry: dict, fmt: str, out_file: Path, meta: dict, timeout_s: int) -> None:
        self._console.clear()
        self._warnings.clear()
        self._ready_page()
        page = self.page
        # a previous book's "status ok" must not satisfy the wait; also allow re-feeding the same path
        page.evaluate("""() => { document.getElementById('status').className = 'status';
                                 document.getElementById('fileInput').value = ''; }""")
        page.evaluate(
            """(fmt) => { const r = document.querySelector('input[name="fmt"][value="' + fmt + '"]');
                          if (r) r.click(); }""", fmt)
        src = entry_path(entry)
        t0 = time.perf_counter()
        page.set_input_files("#fileInput", str(src))
        try:
            page.wait_for_function(_DONE_JS, timeout=timeout_s * 1000, polling=10)
        except Exception as e:
            if "Timeout" in type(e).__name__ or "Timeout" in str(e)[:80]:
                meta["ms"] = int((time.perf_counter() - t0) * 1000)
                meta["error"] = "timeout"
                self._console.append("harness: timeout")
                self._fresh = False  # recycle on next book (main thread may be wedged)
                return
            raise
        meta["ms"] = int((time.perf_counter() - t0) * 1000)
        cls = page.get_attribute("#status", "class") or ""
        meta["status_text"] = (page.text_content("#status") or "").strip()
        m = re.search(r"(\d+)\s+chapter\(s\)", meta["status_text"])
        if m:
            meta["chapters_reported"] = int(m.group(1))
        if re.search(r"\berror\b", cls):
            meta["error"] = meta["status_text"] or "error (empty status)"
            return
        tmp = out_file.with_name(out_file.name + ".part")
        self._downloads += 1
        try:
            with page.expect_download(timeout=20000) as dl:
                page.click("#dlBtn")
            dl.value.save_as(tmp)
            try:
                dl.value.delete()  # Playwright keeps its own copy until the context closes
            except Exception:
                pass
        except Exception:
            # fallback: read the blob straight from the page
            b64 = page.evaluate("""async () => {
                const r = await fetch(document.getElementById('dlBtn').href);
                const b = new Uint8Array(await r.arrayBuffer()); let s = '';
                for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768));
                return btoa(s); }""")
            tmp.write_bytes(base64.b64decode(b64))
            self._fresh = False
        os.replace(tmp, out_file)


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert corpus EPUBs with the web app")
    ap.add_argument("--manifest", default=str(ROOT / "tests/corpus/manifest.json"))
    ap.add_argument("--ids", help="comma-separated ids or fnmatch globs (default: all)")
    ap.add_argument("--fmt", default="azw3,mobi")
    ap.add_argument("--out", default=str(ROOT / "tests/corpus/out"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    entries = select_entries(json.loads(Path(a.manifest).read_text(encoding="utf-8")), a.ids)
    fmts = [f.strip() for f in a.fmt.split(",") if f.strip()]
    out_root = Path(a.out)
    print(f"{len(entries)} entries x {fmts}; app {app_version()}")
    with AppRunner() as runner:
        for e in entries:
            for fmt in fmts:
                m = runner.convert(e, fmt, out_root / e["sha256"], timeout_s=default_timeout(e),
                                   force=a.force)
                od = out_root / e["sha256"] / f"ours.{fmt}"
                size = od.stat().st_size if od.exists() else 0
                state = "ok" if not m["error"] else f"ERR {m['error'][:80]!r}"
                print(f"{e['id'][-60:]:60} {fmt:5} {m['ms'] if m['ms'] is not None else '-':>7} ms "
                      f"{size:>9} B  {state}  js-errors={len(m['console_errors'])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
