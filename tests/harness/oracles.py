"""Oracles for the differential quality harness (WP3).

Two layers, see schema.md:

* ``gate(out_dir, fmt, who)``: can independent parsers read the file at all?
  Runs mobitool (libmobi), KindleUnpack and Calibre's reader on ``<out_dir>/<who>.<fmt>``
  and fills ``<out_dir>/unpack/<fmt>/<who>/``.
* ``invariants(entry, out_dir, fmt, page, base_url=None, who="ours", skip_style=False)``: does the
  KindleUnpack reconstruction of our file still carry what the input EPUB carried (text, images,
  TOC, internal links, author CSS)?

Nothing in here raises for a single book: failures become ``ok: False`` / ``null`` + an error string.
A tool that runs out of time gives ``ok: None, err: "timeout"`` (not evaluated, never cached).
Corpus files are untrusted: inputs are unzipped with ``zipfile`` (path-sanitised) into
``<out_dir>/input/`` only, XML is parsed without network/entity resolution, and the style score loads
pages in a Chromium context with JavaScript disabled and every non-local request aborted.
"""
# Broad `except Exception` (and silent cleanup) is deliberate: the harness contract is that one bad
# book or one flaky tool never aborts a corpus run; failures are recorded in the result instead.
# ruff: noqa: BLE001, S110
from __future__ import annotations

import difflib
import hashlib
import html.entities
import io
import json
import os
import posixpath
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import traceback
import unicodedata
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, quote, unquote, urlparse

from common import ROOT, entry_path, sha256_file, write_json_atomic

KINDLEUNPACK = ROOT / "tests/corpus/tools/KindleUnpack/lib/kindleunpack.py"
TOOL_TIMEOUT_S = 120               # base per-tool timeout; tool_timeout() adds 60 s per 10 MB
ERR_TAIL = 1500
MAX_UNZIP_BYTES = 1 << 30          # refuse to inflate more than 1 GiB per book
STYLE_VIEWPORT = {"width": 600, "height": 800}
STYLE_PROPS = [
    "display", "font-weight", "font-style", "font-size", "font-family", "text-align", "text-indent",
    "margin-top", "margin-bottom", "margin-left", "margin-right", "padding-left", "padding-right",
    "line-height", "text-decoration-line", "font-variant", "white-space", "list-style-type",
    "vertical-align",
]
# elements that anchor the style alignment even without own text (svg <image> included, so an
# svg-wrapped picture that became an <img> still pairs up)
ANCHOR_TAGS = {"img", "hr", "image"}
IMAGE_TAGS = {"img", "image"}
# properties a descendant inherits (or, for text-align/indent, shows through its block): the only
# ones that are meaningful between an element and a container of a different kind
INHERITED_PROPS = {"font-weight", "font-style", "font-size", "font-family", "text-align", "text-indent",
                   "line-height", "font-variant", "white-space", "list-style-type"}
SKIP_TEXT_TAGS = {"style", "script", "head", "title", "template", "noscript"}

OPF_NS = "http://www.idpf.org/2007/opf"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
OPS_NS = "http://www.idpf.org/2007/ops"
XLINK_NS = "http://www.w3.org/1999/xlink"


# ════════════════════════════════════════════════════════════════════════════
# tools
# ════════════════════════════════════════════════════════════════════════════

def install_tools(root: Path = ROOT) -> None:
    """Idempotent presence checks; raises RuntimeError with an install hint for anything missing."""
    root = Path(root)
    problems = []
    if not shutil.which("mobitool"):
        problems.append("mobitool not on PATH -> `brew install libmobi`")
    ku = root / "tests/corpus/tools/KindleUnpack/lib/kindleunpack.py"
    if not ku.exists():
        problems.append(f"KindleUnpack missing at {ku} -> `git clone --depth 1 "
                        "https://github.com/kevinhendricks/KindleUnpack tests/corpus/tools/KindleUnpack`")
    if not shutil.which("ebook-convert"):
        problems.append("ebook-convert not on PATH -> install Calibre (`brew install --cask calibre`)")
    # Chromium: ask Playwright for its executable in a subprocess (the caller may already be
    # inside a sync_playwright() block, where starting a second one would raise).
    try:
        cp = subprocess.run(
            [sys.executable, "-c",
             ("from playwright.sync_api import sync_playwright\n"
              "p = sync_playwright().start()\nprint(p.chromium.executable_path)\np.stop()")],
            check=False, capture_output=True, text=True, timeout=60)
        exe = cp.stdout.strip().splitlines()[-1] if cp.stdout.strip() else ""
        if cp.returncode != 0 or not exe or not Path(exe).exists():
            problems.append("Playwright Chromium not installed -> "
                            "`uv run --with playwright playwright install chromium`"
                            + (f" ({cp.stderr.strip()[-200:]})" if cp.stderr.strip() else ""))
    except Exception as e:  # playwright not importable, timeout, ...
        problems.append(f"Playwright unavailable ({type(e).__name__}: {e}) -> "
                        "`uv run --with playwright playwright install chromium`")
    if problems:
        raise RuntimeError("oracle tools missing:\n  - " + "\n  - ".join(problems))


def _tail(*chunks) -> str:
    s = "\n".join(c.decode("utf-8", "replace") if isinstance(c, bytes) else (c or "") for c in chunks)
    return s.strip()[-ERR_TAIL:]


def tool_timeout(path: Path) -> int:
    """120 s base + 60 s per 10 MB of the file a tool reads."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        size = 0
    return TOOL_TIMEOUT_S + int(60 * size / (10 * 1024 * 1024))


def _run(cmd: list[str], timeout: int = TOOL_TIMEOUT_S) -> tuple[int | None, str]:
    """Run a command in its own process group; returns (returncode or None on timeout, output).

    On timeout the whole group is killed (ebook-convert and KindleUnpack spawn helpers)."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, _tail(out, err)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            p.kill()
        out, err = p.communicate()
        return None, _tail(out, err, f"[timeout after {timeout}s]")


def _file_sig(p: Path) -> dict:
    return {"size": p.stat().st_size, "sha256": sha256_file(p)}


def _fresh_dir(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)


# ── PalmDoc structure probe (only used to explain a mobitool failure) ─────────

def _pdb_records(data: bytes) -> list[bytes]:
    n = struct.unpack(">H", data[76:78])[0]
    offs = [struct.unpack(">I", data[78 + 8 * i:82 + 8 * i])[0] for i in range(n)] + [len(data)]
    return [data[offs[i]:offs[i + 1]] for i in range(n)]


def _trailing_size(rec: bytes, flags: int) -> int:
    """Total size of a text record's trailing entries, walked like Calibre's
    MobiReader.sizeof_trailing_entries: bits of flags >> 1 from the lowest up, each entry read
    backwards from the current end (at most 4 bytes, high bit marks the entry's first byte),
    then the multibyte overlap (bit 0) last."""
    size = 0
    f = flags >> 1
    while f:
        if f & 1:
            end = len(rec) - size
            v = shift = 0
            for i in range(1, min(4, end) + 1):
                c = rec[end - i]
                v |= (c & 0x7F) << shift
                shift += 7
                if c & 0x80:
                    break
            size += v
        f >>= 1
    if flags & 1 and len(rec) > size:
        size += (rec[len(rec) - size - 1] & 3) + 1
    return size


def _palmdoc_len(b: bytes) -> int:
    n = i = 0
    while i < len(b):
        c = b[i]
        i += 1
        if c == 0 or 9 <= c <= 0x7F:
            n += 1
        elif 1 <= c <= 8:
            n += c
            i += c
        elif c >= 0xC0:
            n += 2
        else:
            n += (((c << 8) | (b[i] if i < len(b) else 0)) & 7) + 3
            i += 1
    return n


def structure_hints(path: Path) -> list[str]:
    """Header consistency checks that libmobi enforces and Calibre/KindleUnpack tolerate."""
    hints = []
    try:
        data = Path(path).read_bytes()
        recs = _pdb_records(data)
        r0 = recs[0]
        comp, _, text_len, n_text, rec_size = struct.unpack(">HHIHH", r0[:12])
        hlen = struct.unpack(">I", r0[20:24])[0]
        version = struct.unpack(">I", r0[36:40])[0]
        flags = struct.unpack(">H", r0[0xF2:0xF4])[0] if hlen >= 0xE4 else 0
        if version >= 8 and hlen >= 0xB8:
            fdst_rec, fdst_cnt = struct.unpack(">II", r0[0xC0:0xC8])
            if fdst_rec != 0xFFFFFFFF and fdst_rec < len(recs):
                fd = recs[fdst_rec]
                if fd[:4] != b"FDST":
                    hints.append(f"MOBI header fdst_index={fdst_rec} does not point at an FDST record")
                else:
                    real = struct.unpack(">I", fd[8:12])[0]
                    if fdst_cnt != real and fdst_cnt > 1:
                        hints.append(
                            f"MOBI header fdst_section_count={fdst_cnt} but the FDST record has {real} "
                            f"section(s); libmobi mobi_parse_fdst() requires equality -> MOBI_DATA_CORRUPT "
                            f"(Calibre's inspector also rejects it: 'KF8 Header contains invalid FDST count'). "
                            f"Header field looks like it holds the FDST record index ({fdst_rec}).")
        if comp in (1, 2):
            total = 0
            big = []
            for i in range(1, min(n_text, len(recs) - 1) + 1):
                rec = recs[i]
                body = rec[:len(rec) - _trailing_size(rec, flags)]
                ln = _palmdoc_len(body) if comp == 2 else len(body)
                total += ln
                if ln > rec_size:
                    big.append((i, ln))
            if big:
                hints.append(
                    f"{len(big)} text record(s) decompress to more than text_record_size={rec_size} "
                    f"(first: record {big[0][0]} -> {big[0][1]} bytes); libmobi's decompressor has a "
                    f"{rec_size}-byte output buffer per record -> MOBI_BUFFER_END ('Buffer error'). "
                    f"Records must hold exactly {rec_size} bytes; carry a split UTF-8 sequence via the "
                    f"multibyte trailing entry (extra_flags bit 0) instead of growing the record.")
            if total != text_len:
                hints.append(f"sum of decompressed text records {total} != header text_length {text_len}")
    except Exception as e:
        hints.append(f"structure probe failed: {type(e).__name__}: {e}")
    return hints


# ── gate ──────────────────────────────────────────────────────────────────────

def _ku_parts(ku_dir: Path) -> list[Path]:
    return sorted((ku_dir / "mobi8/OEBPS/Text").glob("part*.xhtml"))


def _timed_out(timeout: int, out: str, **extra) -> dict:
    return {"ok": None, "err": "timeout", "timeout_s": timeout, "output_tail": out[-300:], **extra}


def _gate_kindleunpack(src: Path, d: Path, fmt: str, timeout: int | None = None) -> dict:
    if d.exists():
        shutil.rmtree(d)
    d.parent.mkdir(parents=True, exist_ok=True)
    if not KINDLEUNPACK.exists():
        return {"ok": False, "err": f"harness: KindleUnpack not found at {KINDLEUNPACK}"}
    timeout = timeout or tool_timeout(src)
    rc, out = _run([sys.executable, "-I", str(KINDLEUNPACK), "--epub_version=2", str(src), str(d)],
                   timeout)
    if rc is None:
        return _timed_out(timeout, out, parts=0)
    warnings = [ln.strip() for ln in out.splitlines() if re.search(r"\bwarning\b", ln, re.IGNORECASE)][:10]
    parts = _ku_parts(d)
    book7 = d / "mobi7/book.html"
    if fmt == "azw3":
        tree_ok = (d / "mobi8/OEBPS/content.opf").exists() and bool(parts)
        what = "mobi8/OEBPS/content.opf + Text/part*.xhtml"
    else:
        tree_ok = book7.exists() or ((d / "mobi8/OEBPS/content.opf").exists() and bool(parts))
        what = "mobi7/book.html"
    ok = rc == 0 and tree_ok
    res = {"ok": ok, "err": None if ok else
           (out if rc != 0 else f"exit 0 but no output tree ({what} missing)\n{out}")[-ERR_TAIL:],
           "parts": len(parts) if parts else (1 if book7.exists() else 0)}
    if warnings:
        res["warnings"] = warnings
    return res


def _gate_mobitool(src: Path, d: Path, fmt: str, who: str, ku_parts: int | None,
                   timeout: int | None = None) -> dict:
    _fresh_dir(d)
    timeout = timeout or tool_timeout(src)
    rc, out = _run(["mobitool", "-e", "-o", str(d), str(src)], timeout)
    if rc is None:
        return _timed_out(timeout, out, version=None, parts=None)
    m = re.search(r"Mobi version:\s*(\d+)", out)
    version = int(m.group(1)) if m else None
    epubs = sorted(d.glob("*.epub"))
    problems = []
    parts = None
    if rc != 0:
        problems.append(f"exit {rc}")
    if not epubs or epubs[0].stat().st_size == 0:
        problems.append("no EPUB written")
    else:
        try:
            with zipfile.ZipFile(epubs[0]) as z:
                parts = sum(1 for n in z.namelist() if re.fullmatch(r"OEBPS/part\d+\.html", n))
        except Exception as e:
            problems.append(f"unreadable EPUB: {e}")
    want = {8} if fmt == "azw3" else ({6} if who == "ours" else {6, 8})
    if version is not None and version not in want:
        problems.append(f"Mobi version {version}, expected {sorted(want)}")
    if parts is not None:
        if parts == 0:
            problems.append("EPUB has no OEBPS/part*.html")
        elif version == 8 and ku_parts and parts != ku_parts:
            problems.append(f"{parts} parts but KindleUnpack found {ku_parts}")
        elif version == 6 and parts != 1:
            problems.append(f"MOBI v6 should give 1 part, got {parts}")
    ok = not problems
    # mobitool prints book metadata (incl. long descriptions) before its error: keep only the last lines
    out_tail = "\n".join(ln[:200] for ln in out.splitlines()[-4:])
    res = {"ok": ok, "err": None if ok else _tail("; ".join(problems), out_tail), "version": version,
           "parts": parts}
    if not ok:
        res["hints"] = structure_hints(src)
    return res


def _gate_calibre(src: Path, txt: Path, timeout: int | None = None) -> dict:
    txt.parent.mkdir(parents=True, exist_ok=True)
    if txt.exists():
        txt.unlink()
    timeout = timeout or tool_timeout(src)
    rc, out = _run(["ebook-convert", str(src), str(txt)], timeout)
    if rc is None:
        if txt.exists():
            txt.unlink()
        return _timed_out(timeout, out, chars=0)
    ok = rc == 0 and txt.exists()
    return {"ok": ok, "err": None if ok else
            (out if rc != 0 else f"exit 0 but {txt.name} not written\n{out}")[-ERR_TAIL:],
            "chars": txt.stat().st_size if txt.exists() else 0}


def gate(out_dir: Path, fmt: str, who: str = "ours", force: bool = False) -> dict:
    """Run mobitool, KindleUnpack and ebook-convert on <out_dir>/<who>.<fmt>.

    Returns {"mobitool": {ok, err, ...}, "kindleunpack": {...}, "calibre_reader": {...}}.
    Results are cached in unpack/<fmt>/<who>/gate.json keyed by the file's sha256; a tool is re-run
    when the file changed, its output is gone, or force=True. Timeouts (ok None) and harness errors
    are not cached.
    """
    out_dir = Path(out_dir)
    src = out_dir / f"{who}.{fmt}"
    base = out_dir / "unpack" / fmt / who
    names = ("mobitool", "kindleunpack", "calibre_reader")
    if not src.exists():
        return {n: {"ok": False, "err": f"{src.name} does not exist"} for n in names}
    try:
        base.mkdir(parents=True, exist_ok=True)
        sig = _file_sig(src)
        cache_f = base / "gate.json"
        cache = {}
        if cache_f.exists() and not force:
            try:
                c = json.loads(cache_f.read_text(encoding="utf-8"))
                if c.get("sig") == sig:
                    cache = c.get("results", {})
            except Exception:
                cache = {}
        outputs = {"kindleunpack": base / "kindleunpack", "mobitool": base / "mobitool",
                   "calibre_reader": base / "calibre.txt"}
        res = {}
        for name in ("kindleunpack", "mobitool", "calibre_reader"):  # KU first: mobitool cross-checks it
            hit = cache.get(name)
            if hit is not None and outputs[name].exists():
                res[name] = hit
                continue
            try:
                if name == "kindleunpack":
                    res[name] = _gate_kindleunpack(src, outputs[name], fmt)
                elif name == "mobitool":
                    kp = res["kindleunpack"].get("parts") if res["kindleunpack"].get("ok") is True else None
                    res[name] = _gate_mobitool(src, outputs[name], fmt, who, kp)
                else:
                    res[name] = _gate_calibre(src, outputs[name])
            except Exception as e:
                res[name] = {"ok": False, "err": f"harness: {type(e).__name__}: {e}"[-ERR_TAIL:]}
        keep = {n: v for n, v in res.items()
                if v.get("ok") is not None and not str(v.get("err") or "").startswith("harness:")}
        write_json_atomic(cache_f, {"sig": sig, "results": keep})
        return {n: res[n] for n in names}
    except Exception as e:
        return {n: {"ok": False, "err": f"harness: {type(e).__name__}: {e}"} for n in names}


# ════════════════════════════════════════════════════════════════════════════
# HTTP server for the style score
# ════════════════════════════════════════════════════════════════════════════

_SERVERS: dict[str, Path] = {}


class _OutHandler(SimpleHTTPRequestHandler):
    extensions_map: ClassVar[dict[str, str]] = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".xhtml": "application/xhtml+xml", ".xht": "application/xhtml+xml",
        ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
        ".css": "text/css", ".svg": "image/svg+xml", ".ncx": "application/xml",
        ".opf": "application/xml", ".otf": "font/otf", ".ttf": "font/ttf", ".woff": "font/woff",
        ".woff2": "font/woff2", ".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif",
    }

    def guess_type(self, path):
        # ?as=xhtml / ?as=html forces the parser, like the app's DOMParser + text/html fallback
        mode = parse_qs(urlparse(self.path).query).get("as", [None])[0]
        if mode == "xhtml":
            return "application/xhtml+xml"
        if mode == "html":
            return "text/html; charset=utf-8"
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_):
        pass

    def log_error(self, *_):
        pass


def start_out_server(out_root: Path) -> str:
    """Serve out_root (normally tests/corpus/out) on localhost:<random>; returns base_url."""
    out_root = Path(out_root).resolve()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_OutHandler, directory=str(out_root)))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    _SERVERS[base_url] = out_root
    return base_url


def _server_for(root: Path) -> str:
    root = Path(root).resolve()
    for url, r in _SERVERS.items():
        if r == root:
            return url
    return start_out_server(root)


def _url_for(base_url: str, out_dir: Path, path: Path, mode: str | None = None) -> str:
    root = _SERVERS.get(base_url, out_dir.resolve().parent)
    rel = Path(path).resolve().relative_to(root).as_posix()
    return f"{base_url}/{quote(rel)}" + (f"?as={mode}" if mode else "")


# ════════════════════════════════════════════════════════════════════════════
# document helpers
# ════════════════════════════════════════════════════════════════════════════

_XML_ENTS = {"amp", "lt", "gt", "quot", "apos"}
_ENT_RE = re.compile(rb"&([A-Za-z][A-Za-z0-9]{1,31});")


def _entities_to_numeric(b: bytes) -> bytes:
    def sub(m):
        name = m.group(1).decode("ascii")
        if name in _XML_ENTS:
            return m.group(0)
        cp = html.entities.name2codepoint.get(name)
        return f"&#{cp};".encode() if cp is not None else m.group(0)
    return _ENT_RE.sub(sub, b)


_HTML_START_RE = re.compile(rb"<html\b.*?(?=<head\b|<body\b)", re.IGNORECASE | re.DOTALL)


def _parse_doc(data: bytes):
    """XML first (like the app's application/xhtml+xml DOMParser), lxml.html on failure."""
    from lxml import etree
    from lxml import html as lhtml
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
        return etree.fromstring(_entities_to_numeric(data), parser), "xml"
    except Exception:
        # libxml2's HTML parser gives up on a malformed <html ...> start tag (KindleUnpack's mobi7
        # output writes `<html xmlns=<meta http-equiv=... />"http://...">`), so normalise it first.
        data = _HTML_START_RE.sub(b"<html>", data, count=1)
        return lhtml.document_fromstring(data), "html"


def _local(el) -> str:
    t = el.tag
    if not isinstance(t, str):
        return ""
    return t.rsplit("}", 1)[-1].lower()


def _find_body(root):
    for el in root.iter():
        if _local(el) == "body":
            return el
    return root


_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\ufeff"))  # soft hyphen, ZWSP, BOM: hints, not text


def _norm_ws(s: str) -> str:
    return unicodedata.normalize("NFC", " ".join((s or "").translate(_INVISIBLE).split()))


def _visible_text(el) -> str:
    parts: list[str] = []

    def walk(e):
        if not isinstance(e.tag, str) or _local(e) in SKIP_TEXT_TAGS:
            return
        if e.text:
            parts.append(e.text)
        for c in e:
            walk(c)
            if c.tail:
                parts.append(c.tail)
    walk(el)
    return _norm_ws("".join(parts))


def _elements(root, names: set[str]):
    return [e for e in root.iter() if isinstance(e.tag, str) and _local(e) in names]


def _attr(el, name: str):
    for k, v in el.attrib.items():
        if k == name or k.rsplit("}", 1)[-1] == name:
            return v
    return None


def _has_scheme(href: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", href))


def _join(base_file: str, href: str) -> str:
    """Resolve href (URL-encoded, no fragment) against a zip/tree path; posix-normalised."""
    p = posixpath.normpath(posixpath.join(posixpath.dirname(base_file), unquote(href)))
    return "" if p.startswith("../") or p == ".." else p.lstrip("/")


def _img_info(data: bytes):
    """[width, height] or None. Only the header is read, so the decompression-bomb limit is lifted
    for this call only (Pillow's global is restored afterwards)."""
    try:
        from PIL import Image
    except Exception:
        return None
    old = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(io.BytesIO(data)) as im:
            return list(im.size)
    except Exception:
        return None
    finally:
        Image.MAX_IMAGE_PIXELS = old


def _empty_doc():
    from lxml import html as lhtml
    return lhtml.document_fromstring("<html><head></head><body></body></html>")


def _parse_or_empty(path: Path, errors: dict, key: str):
    """Parse one document; an unreadable, empty or unparsable one becomes an empty <body> and an
    entry in `errors`, so one bad file does not void the invariants of the whole book."""
    try:
        data = Path(path).read_bytes()
        if not data.strip():
            raise ValueError("empty or whitespace-only document")
        return _parse_doc(data)[0]
    except Exception as e:
        errors[key] = f"{type(e).__name__}: {e}"[:300]
        return _empty_doc()


_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)


def _css_rule_count(css: str) -> int:
    """Number of rule blocks (`{`), comments removed; @media etc. count as one more."""
    return _CSS_COMMENT_RE.sub("", css).count("{")


def _inline_css_rules(markup: str) -> int:
    return sum(_css_rule_count(m.group(1)) for m in _STYLE_BLOCK_RE.finditer(markup))


# ════════════════════════════════════════════════════════════════════════════
# input book
# ════════════════════════════════════════════════════════════════════════════

_UNZIP_VERSION = 2   # bump when the extraction policy changes (2: first of casefold duplicates wins)


def casefold_collisions(names) -> list[list[str]]:
    """Zip member names that differ only in case: on a case-insensitive file system (macOS) they
    land on the same file. Returns [[kept name, dropped name], ...]."""
    seen: dict[str, str] = {}
    out = []
    for n in names:
        n = n.replace("\\", "/")
        if n.endswith("/"):
            continue
        k = n.casefold()
        if k in seen and seen[k] != n:
            out.append([seen[k], n])
        else:
            seen.setdefault(k, n)
    return out


def _safe_unzip(epub: Path, dest: Path) -> None:
    marker = dest / ".unzipped.json"
    sig = {**_file_sig(epub), "unzip_v": _UNZIP_VERSION}
    if marker.exists():
        try:
            if json.loads(marker.read_text(encoding="utf-8")) == sig:
                return
        except Exception:
            pass
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    root = dest.resolve()
    total = 0
    written: set[str] = set()
    with zipfile.ZipFile(epub) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or not name or name.startswith("/") or ".." in name.split("/"):
                continue
            if name.casefold() in written:   # first one wins, deterministically on any file system
                continue
            written.add(name.casefold())
            target = (dest / name).resolve()
            if root not in target.parents:
                continue
            total += info.file_size
            if total > MAX_UNZIP_BYTES:
                raise RuntimeError(f"input inflates beyond {MAX_UNZIP_BYTES} bytes")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as s, open(target, "wb") as d:
                shutil.copyfileobj(s, d)
    marker.write_text(json.dumps(sig), encoding="utf-8")


class InputBook:
    """Parsed input EPUB: spine (with the app's chapter mapping), images, TOC."""

    def __init__(self, entry: dict, out_dir: Path):
        self.epub = entry_path(entry)
        self.dir = out_dir / "input"
        _safe_unzip(self.epub, self.dir)
        with zipfile.ZipFile(self.epub) as z:
            namelist = z.namelist()
        self.names = set(namelist)
        self.casefold_collisions = casefold_collisions(namelist)
        self.doc_errors: dict[str, str] = {}
        cont = self._xml(self.dir / "META-INF/container.xml")
        rf = next((e for e in cont.iter() if _local(e) == "rootfile" and _attr(e, "full-path")), None)
        if rf is None:
            raise RuntimeError("container.xml has no rootfile")
        self.opf_path = _attr(rf, "full-path").lstrip("/")
        opf = self._xml(self.dir / self.opf_path)
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.manifest: dict[str, dict] = {}
        for it in (e for e in opf.iter() if _local(e) == "item"):
            iid, href = _attr(it, "id"), _attr(it, "href")
            if iid is None or href is None:
                continue
            self.manifest[iid] = {"href": href, "mt": (_attr(it, "media-type") or "").strip(),
                                  "props": _attr(it, "properties") or "",
                                  "path": _join(self.opf_path, href.split("#")[0])}
        spine_el = next((e for e in opf.iter() if _local(e) == "spine"), None)
        self.spine_toc_id = _attr(spine_el, "toc") if spine_el is not None else None
        self.fixed_layout = False
        for m in (e for e in opf.iter() if _local(e) == "meta"):
            prop, name = (_attr(m, "property") or "").strip(), (_attr(m, "name") or "").strip()
            if prop == "rendition:layout" and (m.text or "").strip() == "pre-paginated":
                self.fixed_layout = True
            if name in ("fixed-layout", "rendition:layout") and \
                    (_attr(m, "content") or "").strip().lower() in ("true", "pre-paginated"):
                self.fixed_layout = True
        # Spine -> chapters. The app does resolve = opfDir + href.split('#')[0], tries the raw then the
        # URI-decoded name with JSZip (no ../ normalisation), and skips files it cannot find or parse.
        self.spine: list[dict] = []
        for ir in (e for e in (spine_el if spine_el is not None else []) if _local(e) == "itemref"):
            it = self.manifest.get(_attr(ir, "idref") or "")
            if not it:
                continue
            raw = (self.opf_dir + "/" if self.opf_dir else "") + it["href"].split("#")[0]
            app_found = raw in self.names or unquote(raw) in self.names
            present = it["path"] in self.names
            if not present and not app_found:
                continue  # genuinely missing from the zip: not counted
            self.spine.append({"path": it["path"] if present else (raw if raw in self.names else unquote(raw)),
                               "href": it["href"], "mt": it["mt"], "app_found": app_found,
                               "linear": (_attr(ir, "linear") or "yes") != "no"})
        self.spine_paths = {s["path"]: i for i, s in enumerate(self.spine)}
        self.spine_missing = sum(1 for e in (spine_el if spine_el is not None else [])
                                 if _local(e) == "itemref") - len(self.spine)
        self.cover_path = self._cover_path(opf)
        self._docs: dict[str, object] = {}

    def _cover_path(self, opf):
        """Manifest path of the cover image (EPUB 3 properties="cover-image" or EPUB 2
        <meta name="cover" content="<item id>">), or None."""
        for it in self.manifest.values():
            if "cover-image" in it["props"].split() and it["mt"].startswith("image/"):
                return it["path"]
        for m in (e for e in opf.iter() if _local(e) == "meta"):
            if (_attr(m, "name") or "").strip() == "cover":
                it = self.manifest.get((_attr(m, "content") or "").strip())
                if it and it["mt"].startswith("image/"):
                    return it["path"]
        return None

    def _xml(self, path: Path):
        root, _ = _parse_doc(path.read_bytes())
        return root

    def doc(self, path: str):
        if path not in self._docs:
            self._docs[path] = _parse_or_empty(self.dir / path, self.doc_errors, path)
        return self._docs[path]

    def css_rules(self) -> int:
        """Rule blocks in the manifest's text/css items plus inline <style> in spine documents."""
        n = 0
        for it in self.manifest.values():
            f = self.dir / it["path"]
            if it["mt"] == "text/css" and it["path"] in self.names and f.is_file():
                n += _css_rule_count(f.read_text("utf-8", errors="replace"))
        for sp in self.spine:
            f = self.dir / sp["path"]
            if f.is_file():
                n += _inline_css_rules(f.read_text("utf-8", errors="replace"))
        return n

    def mark_skipped(self, skipped: list[str]) -> None:
        """Chapters the app logged as `Skip chapter: <path> ...` produced no skeleton."""
        for s in self.spine:
            if any(x.strip().startswith(s["path"]) for x in skipped):
                s["app_found"] = False

    # images ------------------------------------------------------------------
    def images(self) -> dict[str, dict]:
        """path -> {sha256, dims} for manifest image items present in the zip."""
        out = {}
        for it in self.manifest.values():
            if not it["mt"].startswith("image/") or it["path"] in out:
                continue
            f = self.dir / it["path"]
            if it["path"] in self.names and f.exists():
                b = f.read_bytes()
                out[it["path"]] = {"sha256": hashlib.sha256(b).hexdigest(), "dims": _img_info(b)}
        return out

    # toc ---------------------------------------------------------------------
    def toc(self) -> tuple[list[tuple[str, int]], str]:
        ncx_entries, nav_entries = [], []
        ncx_id = self.spine_toc_id if self.spine_toc_id in self.manifest else next(
            (k for k, v in self.manifest.items() if v["mt"] == "application/x-dtbncx+xml"), None)
        if ncx_id and (self.dir / self.manifest[ncx_id]["path"]).exists():
            ncx_entries = ncx_toc(self.dir / self.manifest[ncx_id]["path"])
        nav_id = next((k for k, v in self.manifest.items() if "nav" in v["props"].split()), None)
        if nav_id and (self.dir / self.manifest[nav_id]["path"]).exists():
            nav_entries = nav_toc(self.dir / self.manifest[nav_id]["path"])
        if len(nav_entries) > len(ncx_entries):
            return nav_entries, "nav"
        return ncx_entries, ("ncx" if ncx_entries else "none")


def ncx_toc(path: Path) -> list[tuple[str, int]]:
    root, _ = _parse_doc(path.read_bytes())
    nav_map = next((e for e in root.iter() if _local(e) == "navmap"), None)
    out: list[tuple[str, int]] = []

    def walk(el, depth):
        for np in el:
            if _local(np) != "navpoint":
                continue
            lab = next((e for e in np.iter() if _local(e) == "navlabel"), None)
            txt = next((e for e in lab.iter() if _local(e) == "text"), None) if lab is not None else None
            out.append((_visible_text(txt) if txt is not None else "", depth))
            walk(np, depth + 1)
    if nav_map is not None:
        walk(nav_map, 1)
    return out


def nav_toc(path: Path) -> list[tuple[str, int]]:
    root, _ = _parse_doc(path.read_bytes())
    navs = [e for e in root.iter() if _local(e) == "nav"]
    toc = next((n for n in navs if "toc" in (_attr(n, "type") or "").split()), navs[0] if navs else None)
    out: list[tuple[str, int]] = []

    def walk(ol, depth):
        for li in ol:
            if _local(li) != "li":
                continue
            lab = next((c for c in li if _local(c) in ("a", "span")), None)
            out.append((_visible_text(lab) if lab is not None else "", depth))
            for c in li:
                if _local(c) == "ol":
                    walk(c, depth + 1)
    if toc is not None:
        ol = next((e for e in toc.iter() if _local(e) == "ol"), None)
        if ol is not None:
            walk(ol, 1)
    return out


# ════════════════════════════════════════════════════════════════════════════
# output (KindleUnpack tree)
# ════════════════════════════════════════════════════════════════════════════

class OutputBook:
    def __init__(self, out_dir: Path, fmt: str, who: str):
        self.dir = out_dir / "unpack" / fmt / who / "kindleunpack"
        if fmt == "azw3":
            self.oebps = self.dir / "mobi8/OEBPS"
            self.docs = sorted((self.oebps / "Text").glob("part*.xhtml"))
            self.ncx = self.oebps / "toc.ncx"
            self.kind = "kf8"
        else:
            self.oebps = self.dir / "mobi7"
            self.docs = [self.oebps / "book.html"] if (self.oebps / "book.html").exists() else []
            self.ncx = self.oebps / "toc.ncx"
            self.kind = "mobi7"
        if not self.docs:
            raise RuntimeError(f"no KindleUnpack output documents under {self.oebps}")
        self._docs: dict[Path, object] = {}
        self.doc_errors: dict[str, str] = {}

    def doc(self, p: Path):
        if p not in self._docs:
            self._docs[p] = _parse_or_empty(p, self.doc_errors, p.name)
        return self._docs[p]

    def css_rules(self) -> int:
        """Rule blocks in the tree's .css files plus inline <style> in its documents."""
        n = 0
        for f in self.oebps.rglob("*"):
            if f.is_file() and f.suffix.lower() == ".css":
                n += _css_rule_count(f.read_text("utf-8", errors="replace"))
        for f in self.docs:
            n += _inline_css_rules(f.read_text("utf-8", errors="replace"))
        return n

    def images(self) -> dict[str, dict]:
        """sha256 -> {names, dims} over every image KindleUnpack extracted (mobi7/Images holds all
        resource records; mobi8/OEBPS/Images only those referenced, cover/thumb excluded)."""
        out: dict[str, dict] = {}
        for d in (self.dir / "mobi7/Images", self.dir / "mobi8/OEBPS/Images"):
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                b = f.read_bytes()
                h = hashlib.sha256(b).hexdigest()
                rec = out.setdefault(h, {"names": [], "dims": _img_info(b)})
                rec["names"].append(f"{d.name if d.name != 'Images' else d.parent.name}/{f.name}")
        return out

    def file_hash(self, p: Path):
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest()
        except Exception:
            return None


def _mapping(book: InputBook, outb: OutputBook):
    """Index-align spine items with output documents.

    Returns (mode, pairs) where pairs[i] = output doc Path for spine item i (None if the app skipped
    it). mode 'aligned' when output parts correspond 1:1 to the chapters the app emitted, else
    'concat' (MOBI v6, or a part-count mismatch: compare concatenations)."""
    emitted = [i for i, s in enumerate(book.spine) if s["app_found"]]
    if outb.kind == "kf8":
        expected = [outb.oebps / "Text" / f"part{k:04d}.xhtml" for k in range(len(emitted))]
        if len(outb.docs) == len(emitted) and all(p.exists() for p in expected):
            pairs: list[Path | None] = [None] * len(book.spine)
            for k, i in enumerate(emitted):
                pairs[i] = expected[k]
            return "aligned", pairs
    return "concat", None


# ════════════════════════════════════════════════════════════════════════════
# invariants
# ════════════════════════════════════════════════════════════════════════════

def _body_text(root) -> str:
    return _visible_text(_find_body(root))


def _excerpt(a: str, b: str, ctx: int = 20, width: int = 80) -> tuple[str, str]:
    k = len(os.path.commonprefix([a, b]))
    s = max(0, k - ctx)
    return a[s:s + width], b[s:s + width]


_CSS_LIKE = re.compile(r"\{[^}]{5,}(display|margin|font|visibility)[^}]{0,50}\}")


def inv_text(book: InputBook, outb: OutputBook, mode: str, pairs) -> dict:
    in_txt = [_body_text(book.doc(s["path"])) for s in book.spine]
    out_docs_txt = [_body_text(outb.doc(p)) for p in outb.docs]
    res = {"spine_items": len(in_txt), "matching_items": 0, "first_diff": None, "mode": mode,
           "output_items": len(outb.docs),
           "app_skipped": sum(1 for s in book.spine if not s["app_found"]),
           "spine_missing_in_zip": book.spine_missing, "whitespace_only_diffs": 0,
           "chars_in": sum(len(t) for t in in_txt), "chars_out": sum(len(t) for t in out_docs_txt)}
    all_in, all_out = " ".join(in_txt), " ".join(out_docs_txt)
    res["fffd_in"], res["fffd_out"] = all_in.count("\ufffd"), all_out.count("\ufffd")
    res["replacement_chars"], res["replacement_chars_input"] = res["fffd_out"], res["fffd_in"]
    res["css_in_text"] = bool(_CSS_LIKE.search(all_out))
    res["css_in_text_input"] = bool(_CSS_LIKE.search(all_in))
    if mode == "aligned":
        for i, t in enumerate(in_txt):
            o = _body_text(outb.doc(pairs[i])) if pairs[i] is not None else ""
            if t == o:
                res["matching_items"] += 1
            elif pairs[i] is not None and "".join(t.split()) == "".join(o.split()):
                res["matching_items"] += 1
                res["whitespace_only_diffs"] += 1
            elif res["first_diff"] is None:
                a, b = _excerpt(o, t)
                res["first_diff"] = {"item": i, "ours_excerpt": a, "input_excerpt": b,
                                     "path": book.spine[i]["path"]}
        return res
    # concat: find each input item, in order, in the whitespace-free concatenation of the output.
    # A match far ahead of the cursor is only taken when the next item's text does not occur in
    # the skipped stretch (otherwise a short item would jump the cursor past items that are there).
    out_ns, out_map = _strip_ws(all_out)
    in_ns = [_strip_ws(t)[0] for t in in_txt]
    pos = 0
    for i, t in enumerate(in_txt):
        t_ns, t_map = _strip_ws(t)
        j = out_ns.find(t_ns, pos)
        if j >= 0 and j - pos > CONCAT_SLACK:
            nxt = next((x[:24] for x in in_ns[i + 1:] if x), "")
            if nxt and out_ns.find(nxt, pos, j) >= 0:
                j = -1
        if j >= 0:
            res["matching_items"] += 1
            pos = j + len(t_ns)
        elif res["first_diff"] is None:
            # anchor on the item's first 24 visible chars if they occur ahead, else on the cursor
            s0 = out_ns.find(t_ns[:24], pos) if t_ns else -1
            s0 = pos if s0 < 0 else s0
            k = len(os.path.commonprefix([out_ns[s0:s0 + len(t_ns) + 1], t_ns]))
            o_at = out_map[s0 + k] if s0 + k < len(out_map) else len(all_out)
            t_at = t_map[k] if k < len(t_map) else len(t)
            res["first_diff"] = {"item": i, "ours_excerpt": all_out[max(0, o_at - 20):max(0, o_at - 20) + 80],
                                 "input_excerpt": t[max(0, t_at - 20):max(0, t_at - 20) + 80],
                                 "path": book.spine[i]["path"]}
    return res


CONCAT_SLACK = 2000   # whitespace-free chars the concat cursor may skip without a sanity check


def _strip_ws(s: str) -> tuple[str, list[int]]:
    keep = [k for k, ch in enumerate(s) if not ch.isspace()]
    return "".join(s[k] for k in keep), keep


def _img_href(e):
    if _local(e) == "img":
        return _attr(e, "src")
    return e.get(f"{{{XLINK_NS}}}href") or _attr(e, "href")


def _text_index(root) -> tuple[str, dict[str, int], list[tuple[int, object]]]:
    """Walk the body in document order. Returns (whitespace-free visible text, {id/name: offset of
    the element's start in that text}, [(offset, element)] for every img / svg image)."""
    buf: list[str] = []
    n = 0
    ids: dict[str, int] = {}
    imgs: list[tuple[int, object]] = []

    def add(s):
        nonlocal n
        if s:
            t = unicodedata.normalize("NFC", "".join(s.translate(_INVISIBLE).split()))
            if t:
                buf.append(t)
                n += len(t)

    def walk(e):
        if not isinstance(e.tag, str) or _local(e) in SKIP_TEXT_TAGS:
            return
        for k in ("id", "name"):
            v = _attr(e, k)
            if v and v not in ids:
                ids[v] = n
        if _local(e) in IMAGE_TAGS:
            imgs.append((n, e))
        add(e.text)
        for c in e:
            walk(c)
            add(c.tail)
    walk(_find_body(root))
    return "".join(buf), ids, imgs


_CTX = 24   # chars of text before/after an image that identify its place in the text


def inv_images(book: InputBook, outb: OutputBook, mode: str, pairs) -> dict:
    """Image presence (by hash) and per-reference correctness.

    References (img@src, svg image@xlink:href) are paired by their place in the text (the visible
    text just before and after them, difflib over the sequence), not blindly by position, so a
    dropped/extra reference does not shift every later pairing; data:, external and non-manifest
    input references are left out. A pair is correct when the output reference resolves to a
    byte-identical copy of the input image.

    `missing` = referenced input images (plus the cover) that are neither present by hash nor
    present-but-changed (paired by reference to an output image that is not an input image, e.g.
    recompressed). Unreferenced manifest images do not count."""
    inp = book.images()
    outp = outb.images()
    in_hashes = {v["sha256"] for v in inp.values()}
    res = {"input": len(inp), "output": len(outp),
           "matched_by_hash": sum(1 for v in inp.values() if v["sha256"] in outp),
           "dimension_mismatch": 0,
           "refs_total": 0, "refs_correct": 0, "refs_wrong_image": 0, "refs_missing": 0,
           "first_wrong_ref": None}

    def in_refs(i):
        """[(context key, input image path)] for one spine item, plus its text length."""
        s = book.spine[i]
        text, _, imgs = _text_index(book.doc(s["path"]))
        out = []
        for off, e in imgs:
            r = (_img_href(e) or "").strip()
            if not r or r.startswith("data:") or _has_scheme(r):
                continue
            ip = _join(s["path"], r.split("#")[0])
            if ip in inp:
                out.append((off, ip))
        return text, out

    def out_refs(p: Path):
        """[(offset, output image hash or None)] for one output document, plus its text."""
        text, _, imgs = _text_index(outb.doc(p))
        out = []
        for off, e in imgs:
            r = (_img_href(e) or "").strip()
            if r.startswith("data:") or _has_scheme(r):
                continue   # kindle:embed left unresolved etc.: not a usable reference
            h = None
            if r:
                f = (p.parent / unquote(r.split("#")[0])).resolve()
                if not f.is_file():
                    # KindleUnpack names a record that is both CoverOffset and ThumbOffset "thumbNNNNN"
                    # and leaves it in mobi7/Images only; the reference itself is still to that record.
                    f = outb.dir / "mobi7/Images" / f.name
                h = outb.file_hash(f) if f.is_file() else None
            out.append((off, h))
        return text, out

    def keyed(parts):
        """Concatenate [(text, [(offset, value)])] and key every value by its text context."""
        full, items, base = [], [], 0
        for text, refs in parts:
            full.append(text)
            items += [(base + off, v) for off, v in refs]
            base += len(text)
        t = "".join(full)
        return [(t[max(0, o - _CTX):o], t[o:o + _CTX]) for o, _ in items], [v for _, v in items]

    if mode == "aligned":
        groups = []
        for i, p in enumerate(pairs):
            ki, vi = keyed([in_refs(i)])
            ko, vo = keyed([out_refs(p)]) if p is not None else ([], [])
            groups.append((i, ki, vi, ko, vo))
    else:
        ki, vi = keyed([in_refs(i) for i in range(len(book.spine))])
        ko, vo = keyed([out_refs(p) for p in outb.docs])
        groups = [(None, ki, vi, ko, vo)]

    referenced = {book.cover_path} if book.cover_path in inp else set()
    changed: set[str] = set()
    resized: set[str] = set()
    for gi, ki, vi, ko, vo in groups:
        referenced.update(vi)
        paired: list[tuple[int, str, str | None]] = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ki, ko, autojunk=False).get_opcodes():
            if tag in ("equal", "replace"):
                paired += [(i1 + d, vi[i1 + d], vo[j1 + d]) for d in range(min(i2 - i1, j2 - j1))]
                paired += [(k, vi[k], None) for k in range(i1 + min(i2 - i1, j2 - j1), i2)]
            elif tag == "delete":
                paired += [(k, vi[k], None) for k in range(i1, i2)]
        for k, ip, got in sorted(paired):
            res["refs_total"] += 1
            want = inp[ip]["sha256"]
            if got == want:
                res["refs_correct"] += 1
                continue
            if got is None:
                res["refs_missing"] += 1
            else:
                res["refs_wrong_image"] += 1
                if res["first_wrong_ref"] is None:
                    res["first_wrong_ref"] = {
                        "item": gi, "img_index": k, "input": ip,
                        "output_is_input_image": next((q for q, v in inp.items() if v["sha256"] == got), None)}
                if got not in in_hashes:
                    changed.add(ip)   # present, but not byte-identical (recompressed/resized)
                    di, do = inp[ip]["dims"], (outp.get(got) or {}).get("dims")
                    if want not in outp and di and do and di != do:
                        resized.add(ip)
    cover = book.cover_path if book.cover_path in inp else None
    if cover and inp[cover]["sha256"] not in outp and any(
            h not in in_hashes and any(("cover" in n or "thumb" in n) for n in v["names"])
            for h, v in outp.items()):
        changed.add(cover)
    present = {q for q in referenced if inp[q]["sha256"] in outp}
    res["dimension_mismatch"] = len(resized)
    res["referenced"] = len(referenced)
    res["referenced_matched_by_hash"] = len(present)
    res["referenced_changed"] = len(changed - present)
    res["missing"] = len(referenced - present - changed)
    res["cover"] = cover
    return res


def inv_toc(book: InputBook, outb: OutputBook) -> dict:
    tin, source = book.toc()
    tout = ncx_toc(outb.ncx) if outb.ncx.exists() else []
    a, b = [t for t, _ in tin], [t for t, _ in tout]
    return {"input_entries": len(tin), "output_entries": len(tout), "matched": _lcs(a, b),
            "depth_in": max((d for _, d in tin), default=0),
            "depth_out": max((d for _, d in tout), default=0),
            "source": source,
            "labels_in": a[:8], "labels_out": b[:8]}


def _lcs(a: list, b: list) -> int:
    if not a or not b:
        return 0
    if len(a) * len(b) > 4_000_000:  # approximate for huge TOCs
        return sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def _ids(root) -> set[str]:
    out = set()
    for e in root.iter():
        if not isinstance(e.tag, str):
            continue
        for k in ("id", "name"):
            v = _attr(e, k)
            if v:
                out.add(v)
    return out


def _anchors(root) -> list[tuple[str, str]]:
    """[(normalised link text, href)] for every <a href> in document order."""
    return [(_visible_text(a)[:60], (_attr(a, "href") or "").strip())
            for a in _elements(_find_body(root), {"a"}) if _attr(a, "href") is not None]


def _pair_anchors(ins: list, outs: list) -> dict[int, int]:
    """Map input anchor index -> output anchor index, aligned on link text (difflib), so anchors
    the writer adds or drops do not shift every later pairing."""
    sm = difflib.SequenceMatcher(None, [t for t, _ in ins], [t for t, _ in outs], autojunk=False)
    m = {}
    for blk in sm.get_matching_blocks():
        for d in range(blk.size):
            m[blk.a + d] = blk.b + d
    return m


def inv_links(book: InputBook, outb: OutputBook, mode: str, pairs) -> dict:
    # A link only works on a Kindle when the writer turned it into kindle:pos:fid (KF8) or filepos
    # (MOBI v6). KindleUnpack rewrites those back into "partNNNN.xhtml[#id]" (always with a file
    # name) resp. "#fileposNNN" (+ an inserted <a id="fileposNNN"/>). Hrefs the writer passed
    # through untouched ("chap2.xhtml#x", bare "#x") are counted as unresolved, the bare ones also
    # in raw_fragment_links. Input and output anchors are paired by link text.
    # Where the target cannot be checked by file (MOBI v6: one book.html; KF8 in concat mode: part
    # boundaries differ from the chapters), a link counts as resolved only when the text at its
    # output target starts like the text at the input target.
    # Links whose fragment does not exist in the input target document are broken in the input
    # itself: counted in broken_in_input and left out of internal_total.
    res = {"internal_total": 0, "resolved": 0, "kindle_pos_left": 0, "raw_fragment_links": 0,
           "unpaired": 0, "broken_in_input": 0, "wrong_target_text": 0, "first_unresolved": None}
    in_anchors = [_anchors(book.doc(s["path"])) for s in book.spine]
    in_idx_cache: dict[int, tuple] = {}

    def in_index(t: int):
        if t not in in_idx_cache:
            in_idx_cache[t] = _text_index(book.doc(book.spine[t]["path"]))
        return in_idx_cache[t]

    links = []  # (spine idx, anchor index in that doc, target spine idx, fragment)
    for i, s in enumerate(book.spine):
        for k, (_, href) in enumerate(in_anchors[i]):
            if not href or _has_scheme(href):
                continue
            path, _, frag = href.partition("#")
            if path:
                tgt = book.spine_paths.get(_join(s["path"], path))
                if tgt is None:
                    continue
            else:
                if not frag:
                    continue
                tgt = i
            frag = unquote(frag)
            if frag and frag not in in_index(tgt)[1]:
                res["broken_in_input"] += 1
                continue
            links.append((i, k, tgt, frag))
    res["internal_total"] = len(links)
    if not links:
        return res
    ids_cache: dict[Path, set] = {}
    out_idx_cache: dict[Path, tuple] = {}

    def ids(p: Path):
        if p not in ids_cache:
            ids_cache[p] = _ids(outb.doc(p)) if p.exists() else set()
        return ids_cache[p]

    def target_text_ok(tgt: int, frag: str, p: Path, oid: str | None) -> bool:
        """Does the output text at p#oid (start of p when oid is None) start like the input target?"""
        t_in, ids_in, _ = in_index(tgt)
        want = t_in[ids_in.get(frag, 0) if frag else 0:][:_CTX]
        if not want:
            return True          # nothing visible to compare (target at the very end)
        if p not in out_idx_cache:
            out_idx_cache[p] = _text_index(outb.doc(p))
        t_out, ids_out, _ = out_idx_cache[p]
        at = ids_out.get(oid) if oid else 0
        if at is None:
            return False
        return want in t_out[at:at + _CTX + 64]

    # output anchor for each input link: (output doc, href) or None
    found: dict[tuple[int, int], tuple[Path, str] | None] = {}
    if mode == "aligned":
        for i in {l[0] for l in links}:
            p = pairs[i]
            if p is None:
                continue
            oa = _anchors(outb.doc(p))
            for k, j in _pair_anchors(in_anchors[i], oa).items():
                found[(i, k)] = (p, oa[j][1])
    else:
        flat_in, owner = [], []
        for i, al in enumerate(in_anchors):
            for k, x in enumerate(al):
                flat_in.append(x)
                owner.append((i, k))
        flat_out = [(p, x) for p in outb.docs for x in _anchors(outb.doc(p))]
        for a_i, b_i in _pair_anchors(flat_in, [x for _, x in flat_out]).items():
            found[owner[a_i]] = (flat_out[b_i][0], flat_out[b_i][1][1])

    for i, k, tgt, frag in links:
        hit = found.get((i, k))
        ok = False
        oh = hit[1] if hit else None
        if hit is None:
            res["unpaired"] += 1
        elif oh.startswith("kindle:"):
            res["kindle_pos_left"] += 1
        elif outb.kind == "mobi7" and oh.startswith("#filepos"):
            oid = unquote(oh[1:])
            ok = oid in ids(hit[0])
            if ok and not target_text_ok(tgt, frag, hit[0], oid):
                ok = False
                res["wrong_target_text"] += 1
        elif oh.startswith("#"):
            res["raw_fragment_links"] += 1
        elif oh and not _has_scheme(oh) and outb.kind == "kf8":
            opath, _, ofrag = oh.partition("#")
            tfile = (hit[0].parent / unquote(opath)).resolve()
            ok = (tfile.exists() and re.fullmatch(r"part\d{4}\.xhtml", tfile.name) is not None
                  and (not ofrag or unquote(ofrag) in ids(tfile))
                  and not (frag and not ofrag))  # a fragment link must land on an anchor
            if ok and mode == "aligned":         # ... in the part that holds the target chapter
                ok = pairs[tgt] is not None and tfile == pairs[tgt].resolve()
            elif ok:                             # concat: part boundaries differ, check the text
                ok = target_text_ok(tgt, frag, tfile, unquote(ofrag) if ofrag else None)
                res["wrong_target_text"] += not ok
        if ok:
            res["resolved"] += 1
        elif res["first_unresolved"] is None:
            res["first_unresolved"] = {"item": i, "input_href": in_anchors[i][k][1],
                                       "input_target": book.spine[tgt]["path"] + ("#" + frag if frag else ""),
                                       "output_href": oh}
    return res


# ── style ─────────────────────────────────────────────────────────────────────

_COLLECT_JS = r"""
(args) => {
  const props = args.props, anchorTags = new Set(args.anchors);
  const perr = document.getElementsByTagNameNS('*', 'parsererror').length > 0;
  const body = document.body || document.documentElement;
  if (!body) return {perr, bodyFS: 16, baseFS: 16, els: []};
  const bodyFS = parseFloat(getComputedStyle(body).fontSize) || 16;
  const idx = new Map();
  const els = [];
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_ELEMENT);
  for (let e = walker.currentNode; e; e = walker.nextNode()) {
    const tag = (e.localName || '').toLowerCase();
    if (tag === 'style' || tag === 'script' || tag === 'parsererror') continue;
    let own = '';
    for (const c of e.childNodes) if (c.nodeType === 3) own += c.data;
    // full text only for alignment anchors (own text, or an image/hr): keeps the payload small
    const full = (own.trim() || anchorTags.has(tag)) ? (e.textContent || '') : '';
    const cs = getComputedStyle(e);
    const parent = e.parentElement && idx.has(e.parentElement) ? idx.get(e.parentElement) : -1;
    idx.set(e, els.length);
    els.push([tag, own, props.map(p => cs.getPropertyValue(p)), parent, e, full]);
  }
  // Baseline: the same DOM with every author style sheet and style attribute removed, i.e. what
  // the UA (plus presentational HTML attributes) gives. A property "carries author CSS" when the
  // authored value differs from this baseline.
  for (const sh of Array.from(document.styleSheets)) { try { sh.disabled = true; } catch (_) {} }
  for (const r of els) if (r[4].removeAttribute) r[4].removeAttribute('style');
  const baseFS = parseFloat(getComputedStyle(body).fontSize) || 16;
  for (const r of els) {
    const cs = getComputedStyle(r[4]);
    r[4] = props.map(p => cs.getPropertyValue(p));
  }
  return {perr, bodyFS, baseFS, els};
}
"""

_PX_RE = re.compile(r"(-?\d+(?:\.\d+)?)px")
_ALL_IDX = tuple(range(len(STYLE_PROPS)))
_INH_IDX = tuple(k for k, p in enumerate(STYLE_PROPS) if p in INHERITED_PROPS)
_DISPLAY = STYLE_PROPS.index("display")
_FALLBACK_WINDOW = 300   # output anchors searched for a container of an unmatched input element


def _norm_prop(prop: str, val: str, body_fs: float):
    v = (val or "").strip()
    if prop == "font-size":
        m = _PX_RE.fullmatch(v)
        return ("ratio", float(m.group(1)) / body_fs) if m and body_fs else v
    if prop == "font-family":
        return v.split(",")[0].strip().strip("'\"").lower()
    return _PX_RE.sub(lambda m: f"{round(float(m.group(1)) * 2) / 2:g}px", v)


def _prop_equal(prop: str, a, b) -> bool:
    if isinstance(a, tuple) and isinstance(b, tuple):
        return abs(a[1] - b[1]) <= 0.05 * max(abs(a[1]), 1e-9)
    return a == b


def _collect(page, url_xhtml: str, url_html: str, xhtml_first: bool = True) -> dict:
    args = {"props": STYLE_PROPS, "anchors": sorted(ANCHOR_TAGS)}
    data = None
    if xhtml_first:
        try:
            # Chromium never fires `load` for an XML document with a fatal parse error (JS disabled),
            # so a timeout here means "not well-formed": fall through to the HTML parser below.
            page.goto(url_xhtml, wait_until="load", timeout=10000)
            data = page.evaluate(_COLLECT_JS, args)
            data["parsed_as"] = "xhtml"
        except Exception as e:
            if "Timeout" not in type(e).__name__:
                raise
            data = None
    if data is None or data["perr"]:
        page.goto(url_html, wait_until="load", timeout=60000)
        data = page.evaluate(_COLLECT_JS, args)
        data["parsed_as"] = "html"
    els = []
    for tag, own, vals, parent, base, full in data["els"]:
        own_n = _norm_ws(own)
        anchored = bool(own_n) or tag in ANCHOR_TAGS
        els.append({"tag": tag, "text": own_n, "full": _norm_ws(full) if anchored else "",
                    "props": [_norm_prop(p, v, data["bodyFS"]) for p, v in zip(STYLE_PROPS, vals, strict=True)],
                    "base": [_norm_prop(p, v, data["baseFS"]) for p, v in zip(STYLE_PROPS, base, strict=True)],
                    "raw": vals, "parent": parent,
                    "inline": vals[_DISPLAY] in ("inline", "contents"),
                    "anchored": anchored})
    return {"els": els, "parsed_as": data["parsed_as"], "body_fs": data["bodyFS"]}


def _authored(e: dict, idx=_ALL_IDX) -> int:
    """Number of properties whose value the input's author CSS changed (vs. the UA baseline)."""
    return sum(1 for pi in idx if not _prop_equal(STYLE_PROPS[pi], e["props"][pi], e["base"][pi]))


class _StyleAcc:
    def __init__(self):
        self.hist: dict[str, int] = {}
        self.examples: dict[str, list] = {}
        self.seen: set = set()
        self.all_scores: dict = {}

    def _pair(self, a: dict, b: dict, idx, key, anchor_text: str) -> tuple[int, int, int, int]:
        """(checked, equal, all_checked, all_equal) over the property indexes idx for one pair.
        `checked` counts a property only when the input's author CSS sets it (differs from the UA
        baseline) or the two sides disagree, so shared browser defaults do not inflate the score."""
        checked = equal = all_checked = all_equal = 0
        for pi in idx:
            prop = STYLE_PROPS[pi]
            same = _prop_equal(prop, a["props"][pi], b["props"][pi])
            all_checked += 1
            all_equal += same
            authored = not _prop_equal(prop, a["props"][pi], a["base"][pi])
            if not authored and same:
                continue
            checked += 1
            if same:
                equal += 1
                continue
            k = (*key, prop)
            if k in self.seen:
                continue
            self.seen.add(k)
            self.hist[prop] = self.hist.get(prop, 0) + 1
            ex = self.examples.setdefault(prop, [])
            item = {"text": a["text"][:40] or anchor_text, "tag": a["tag"],
                    "out_tag": b["tag"], "in": a["raw"][pi], "out": b["raw"][pi]}
            if len(ex) < 3:
                ex.append(item)
            elif item["text"]:  # prefer examples that carry some text
                blank = next((n for n, x in enumerate(ex) if not x["text"]), None)
                if blank is not None:
                    ex[blank] = item
        return checked, equal, all_checked, all_equal

    def compare(self, ein: list, eout: list, i: int, j: int, scope,
                fallback: bool = False) -> tuple[int, int, int, int]:
        """Compare input element i with output element j, then their ancestors.

        The anchor pair is compared on every property when the tags or the display types agree
        (p -> div with the same computed style scores 1.0), otherwise only on the inherited ones
        (an <em> that became a plain run of its <p>). A `fallback` pair (j merely contains i's text)
        is compared on the inherited properties only, without ancestors. Ancestors are then walked
        while their tags agree; an inline element facing a block one is skipped (climbed past), so
        an unwrapped inline or an svg wrapper does not stop the walk."""
        a, b = ein[i], eout[j]
        anchor_text = a["text"][:40] or a["full"][:40]
        full_props = not fallback and (a["tag"] == b["tag"] or a["raw"][_DISPLAY] == b["raw"][_DISPLAY])
        tot = list(self._pair(a, b, _ALL_IDX if full_props else _INH_IDX, (scope, i, j), anchor_text))
        if fallback:
            return tuple(tot)
        if a["tag"] != b["tag"] and a["inline"] != b["inline"]:
            # the inline side's block container corresponds to the block side itself
            if a["inline"]:
                i = a["parent"]
            else:
                j = b["parent"]
        elif a["tag"] == "body" or b["tag"] == "body":
            return tuple(tot)
        else:
            i, j = a["parent"], b["parent"]
        while i >= 0 and j >= 0:
            a, b = ein[i], eout[j]
            if a["tag"] != b["tag"]:
                if a["inline"] and not b["inline"]:
                    i = a["parent"]
                    continue
                if b["inline"] and not a["inline"]:
                    j = b["parent"]
                    continue
                break
            for n, v in enumerate(self._pair(a, b, _ALL_IDX, (scope, i, j), anchor_text)):
                tot[n] += v
            if a["tag"] == "body":
                break
            i, j = a["parent"], b["parent"]
        return tuple(tot)


def _anchor_key(e: dict) -> str:
    if e["tag"] in IMAGE_TAGS:
        return "\x00img"       # pictures align by position among the text anchors
    if e["tag"] == "hr":
        return "\x00hr"
    return e["full"]


def _align_score(ein: list, eout: list, acc: _StyleAcc, scope) -> tuple[dict, int, int, dict]:
    """Returns ({input element index: (checked, equal)}, anchored_in, anchored_out, stats).

    Anchored elements (own text, or img/svg image/hr) are aligned on their normalised full
    textContent, the tag being only a secondary key: difflib first over (text, tag), then, inside
    every region that did not align, over the text alone (a tag change with identical text still
    pairs: p -> div, em -> i, svg image -> img). An input element still unmatched falls back to the
    nearest output anchor whose text contains its text (an unwrapped inline element). Elements
    with no checked property (nothing authored, nothing disputed) are left out; an unmatched input
    element without fallback scores 0 on each of its authored properties."""
    ai = [k for k, e in enumerate(ein) if e["anchored"]]
    ao = [k for k, e in enumerate(eout) if e["anchored"]]
    ki = [(_anchor_key(ein[k]), ein[k]["tag"]) for k in ai]
    ko = [(_anchor_key(eout[k]), eout[k]["tag"]) for k in ao]
    pos: dict[int, int] = {}   # position in ai -> position in ao
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ki, ko, autojunk=False).get_opcodes():
        if tag == "equal":
            pos.update(zip(range(i1, i2), range(j1, j2), strict=True))
        elif tag == "replace":
            sub = difflib.SequenceMatcher(None, [x[0] for x in ki[i1:i2]], [x[0] for x in ko[j1:j2]],
                                          autojunk=False)
            for blk in sub.get_matching_blocks():
                for d in range(blk.size):
                    pos[i1 + blk.a + d] = j1 + blk.b + d
    contrib: dict[int, tuple[int, int]] = {}
    stats = {"matched": 0, "matched_tag_changed": 0, "matched_fallback": 0, "unmatched_in": 0}
    order = sorted(pos)
    for p in range(len(ai)):
        i = ai[p]
        if p in pos:
            j = ao[pos[p]]
            c, e, ac, ae = acc.compare(ein, eout, i, j, scope)
            acc.all_scores[(scope, i)] = ae / ac if ac else 1.0
            stats["matched"] += 1
            stats["matched_tag_changed"] += ein[i]["tag"] != eout[j]["tag"]
        else:
            j = _fallback(ein[i], eout, ao, order, pos, p) if ki[p][0] and not ki[p][0].startswith("\x00") else None
            if j is not None:
                c, e, _, _ = acc.compare(ein, eout, i, j, scope, fallback=True)
                stats["matched_fallback"] += 1
            else:
                c, e = _authored(ein[i]), 0
                stats["unmatched_in"] += 1
        if c:
            contrib[i] = (c, e)
    return contrib, len(ai), len(ao), stats


def _fallback(a: dict, eout: list, ao: list, order: list, pos: dict, p: int):
    """Output element index of the nearest output anchor whose full text contains a's text, looking
    from the output partner of the previous aligned input anchor forwards (up to the next one's),
    then a little backwards."""
    import bisect
    k = bisect.bisect_left(order, p)
    lo = pos[order[k - 1]] if k > 0 else 0
    hi = pos[order[k]] if k < len(order) else len(ao) - 1
    hi = min(hi, lo + _FALLBACK_WINDOW)
    cand = list(range(lo, hi + 1)) + list(range(lo - 1, max(-1, lo - 21), -1))
    needle = a["full"]
    for y in cand:
        if 0 <= y < len(ao) and needle in eout[ao[y]]["full"]:
            return ao[y]
    return None


def inv_style(book: InputBook, outb: OutputBook, mode: str, pairs, page, base_url: str, out_dir: Path) -> dict:
    """Computed-style comparison of input and output (see _align_score). score = equal / checked
    properties over the whole book (1.0 when nothing is authored or disputed); per_chapter the same
    per spine item (None when it has no checked property)."""
    browser = page.context.browser
    if browser is None:  # persistent context: no browser handle to open a dedicated context
        raise RuntimeError("style score needs a page from browser.new_context()/new_page(), "
                           "not a persistent context")
    ctx = browser.new_context(viewport=STYLE_VIEWPORT, device_scale_factor=1, java_script_enabled=False,
                              service_workers="block")
    host = urlparse(base_url).netloc

    def route(r):
        try:
            if urlparse(r.request.url).netloc == host:
                r.continue_()
            else:
                r.abort()
        except Exception:
            pass
    ctx.route("**/*", route)
    pg = ctx.new_page()
    pg.emulate_media(media="screen")
    acc = _StyleAcc()
    n = len(book.spine)
    chk, eq = [0] * n, [0] * n
    tot_in = tot_out = authored_els = 0
    stats_all: dict[str, int] = {}
    parsed = {"input_html_fallback": 0, "output_html_fallback": 0}
    out_xhtml_first = outb.kind == "kf8"

    def add_stats(st):
        for k, v in st.items():
            stats_all[k] = stats_all.get(k, 0) + v
    try:
        def load_in(i):
            p = book.dir / book.spine[i]["path"]
            d = _collect(pg, _url_for(base_url, out_dir, p, "xhtml"), _url_for(base_url, out_dir, p, "html"))
            parsed["input_html_fallback"] += d["parsed_as"] == "html"
            return d["els"]

        def load_out(p):
            d = _collect(pg, _url_for(base_url, out_dir, p, "xhtml"), _url_for(base_url, out_dir, p, "html"),
                         xhtml_first=out_xhtml_first)
            parsed["output_html_fallback"] += d["parsed_as"] == "html" and out_xhtml_first
            return d["els"]

        def shifted(els, off):
            out = []
            for e in els:
                e = dict(e)
                e["parent"] = e["parent"] + off if e["parent"] >= 0 else -1
                out.append(e)
            return out

        if mode == "aligned":
            for i, p in enumerate(pairs):
                ein = load_in(i)
                eout = load_out(p) if p is not None else []
                contrib, ni, no, st = _align_score(ein, eout, acc, i)
                tot_in += ni
                tot_out += no
                authored_els += sum(1 for e in ein if e["anchored"] and _authored(e))
                add_stats(st)
                for c, e in contrib.values():
                    chk[i] += c
                    eq[i] += e
        else:
            ein, owner = [], []
            for i in range(n):
                els = shifted(load_in(i), len(ein))
                ein += els
                owner += [i] * len(els)
            eout = []
            for p in outb.docs:
                eout += shifted(load_out(p), len(eout))
            contrib, tot_in, tot_out, st = _align_score(ein, eout, acc, "book")
            authored_els = sum(1 for e in ein if e["anchored"] and _authored(e))
            add_stats(st)
            for k, (c, e) in contrib.items():
                chk[owner[k]] += c
                eq[owner[k]] += e
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    hist = dict(sorted(acc.hist.items(), key=lambda kv: -kv[1]))
    denom = max(tot_in, tot_out)
    checked, equal = sum(chk), sum(eq)
    return {"score": round(equal / checked, 4) if checked else 1.0,
            "per_chapter": [round(eq[i] / chk[i], 4) if chk[i] else None for i in range(n)],
            "mode": mode, "elements_in": tot_in, "elements_out": tot_out,
            "elements_with_authored_css": authored_els,
            "checked_props": checked, "equal_props": equal,
            **stats_all,
            # naive variant: fraction of all STYLE_PROPS equal over exactly matched anchors, defaults
            # included, unmatched anchors on either side counting 0 (for reference only)
            "score_all_props": round(sum(acc.all_scores.values()) / denom, 4) if denom else None,
            "input_css_rules": book.css_rules(), "output_css_rules": outb.css_rules(),
            "prop_disagreements": hist, "prop_examples": {k: acc.examples[k] for k in hist},
            **parsed}


def _err(e: BaseException) -> str:
    tb = traceback.extract_tb(e.__traceback__)
    where = f" @ {Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
    return f"{type(e).__name__}: {e}"[:600] + where


def invariants(entry: dict, out_dir: Path, fmt: str, page, base_url: str | None = None,
               who: str = "ours", skip_style: bool = False) -> dict:
    """Compute the schema's `invariants` dict for <out_dir>/<who>.<fmt> (via its KindleUnpack tree).

    `page` is any Playwright page (only its browser is used, to open a dedicated JS-disabled context);
    `base_url` must come from start_out_server() on an ancestor of out_dir. Each invariant that fails is
    None and its message is stored in res["errors"][name]. A single unreadable/empty document only
    adds res["errors"]["documents"] (it counts as empty text). Never raises."""
    out_dir = Path(out_dir)
    names = ("text", "images", "toc", "links", "style")
    res: dict = {n: None for n in names}
    errors: dict[str, str] = {}
    try:
        book = InputBook(entry, out_dir)
        meta = out_dir / f"{who}.{fmt}.meta.json"
        if meta.exists():
            try:
                book.mark_skipped(json.loads(meta.read_text(encoding="utf-8")).get("skipped_chapters") or [])
            except Exception:
                pass
        outb = OutputBook(out_dir, fmt, who)
        mode, pairs = _mapping(book, outb)
    except Exception as e:
        return {**res, "fixed_layout": None, "errors": {n: f"setup: {_err(e)}" for n in names}}
    res["fixed_layout"] = book.fixed_layout
    jobs = {
        "text": lambda: inv_text(book, outb, mode, pairs),
        "images": lambda: inv_images(book, outb, mode, pairs),
        "toc": lambda: inv_toc(book, outb),
        "links": lambda: inv_links(book, outb, mode, pairs),
        "style": lambda: (None if skip_style else
                          inv_style(book, outb, mode, pairs, page,
                                    base_url or _server_for(out_dir.parent), out_dir)),
    }
    for n, fn in jobs.items():
        try:
            res[n] = fn()
        except Exception as e:
            res[n] = None
            errors[n] = _err(e)
    if page is None and not skip_style:
        errors.pop("style", None)
        errors["style"] = "no Playwright page given"
    doc_errs = [f"input {k}: {v}" for k, v in book.doc_errors.items()] + \
               [f"output {k}: {v}" for k, v in outb.doc_errors.items()]
    if doc_errs:
        errors["documents"] = "; ".join(doc_errs)[:2000]
    if book.casefold_collisions:
        res["input_casefold_collisions"] = book.casefold_collisions[:20]
        errors["input_casefold"] = (f"{len(book.casefold_collisions)} zip member name(s) differ only in "
                                    f"case; the first of each was used: {book.casefold_collisions[:3]}")
    if errors:
        res["errors"] = errors
    return res


# ════════════════════════════════════════════════════════════════════════════
# CLI: python oracles.py OUT_DIR [--epub X] [--fmt azw3,mobi] [--who ours] [--force] [--no-style]
# ════════════════════════════════════════════════════════════════════════════

def _find_entry(out_dir: Path, epub: str | None) -> dict:
    if epub:
        return {"id": out_dir.name, "path": str(Path(epub).resolve())}
    ej = out_dir / "entry.json"
    if ej.exists():
        return json.loads(ej.read_text(encoding="utf-8"))
    man = ROOT / "tests/corpus/manifest.json"
    if man.exists():
        for e in json.loads(man.read_text(encoding="utf-8")):
            if e.get("sha256") == out_dir.name:
                return e
    raise SystemExit(f"no entry for {out_dir}: pass --epub")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir")
    ap.add_argument("--epub", help="input EPUB (default: out_dir/entry.json or manifest by sha256)")
    ap.add_argument("--fmt", default="azw3,mobi")
    ap.add_argument("--who", default="ours")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-style", action="store_true")
    ap.add_argument("--gate-only", action="store_true")
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir).resolve()
    install_tools(ROOT)
    entry = None if a.gate_only else _find_entry(out_dir, a.epub)
    result = {}
    pw = browser = page = None
    try:
        if not a.gate_only and not a.no_style:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch()
            page = browser.new_page()
        base_url = start_out_server(out_dir.parent)
        for fmt in [f.strip() for f in a.fmt.split(",") if f.strip()]:
            g = gate(out_dir, fmt, a.who, force=a.force)
            r = {"gate": g}
            if not a.gate_only:
                r["invariants"] = (invariants(entry, out_dir, fmt, page, base_url, who=a.who,
                                              skip_style=a.no_style)
                                   if g["kindleunpack"]["ok"] else None)
            result[fmt] = r
    finally:
        for fn in (lambda: browser.close(), lambda: pw.stop()):
            try:
                fn()
            except Exception:
                pass
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
