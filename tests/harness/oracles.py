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
import math
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
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, quote, unquote, urlparse

import device
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


_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>")


def _parse_doc(data: bytes, utf8: bool = False):
    """XML first (like the app's application/xhtml+xml DOMParser), lxml.html on failure.
    `utf8`: the HTML fallback decodes the bytes as UTF-8 (when valid) instead of lxml's latin-1 guess."""
    from lxml import etree
    from lxml import html as lhtml
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
        return etree.fromstring(_entities_to_numeric(data), parser), "xml"
    except Exception:
        # libxml2's HTML parser gives up on a malformed <html ...> start tag (KindleUnpack's mobi7
        # output writes `<html xmlns=<meta http-equiv=... />"http://...">`), so normalise it first.
        data = _HTML_START_RE.sub(b"<html>", data, count=1)
        if utf8:
            try:
                return lhtml.document_fromstring(_XML_DECL_RE.sub("", data.decode("utf-8"))), "html"
            except (UnicodeDecodeError, ValueError):
                pass
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


def _parse_or_empty(path: Path, errors: dict, key: str, utf8: bool = False):
    """Parse one document; an unreadable, empty or unparsable one becomes an empty <body> and an
    entry in `errors`, so one bad file does not void the invariants of the whole book."""
    try:
        data = Path(path).read_bytes()
        if not data.strip():
            raise ValueError("empty or whitespace-only document")
        return _parse_doc(data, utf8)[0]
    except Exception as e:
        errors[key] = f"{type(e).__name__}: {e}"[:300]
        return _empty_doc()


_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
_FONT_FACE_RE = re.compile(r"@font-face\s*\{[^{}]*\}", re.IGNORECASE)
_CSS_IMPORT_RE = re.compile(r"""@import\s+(?:url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)|"([^"]*)"|'([^']*)')""",
                            re.IGNORECASE)
_CSS_URL_RE = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)""", re.IGNORECASE)


def _css_strip(css: str) -> str:
    """CSS without comments and without @font-face blocks (the writer drops fonts by design)."""
    return _FONT_FACE_RE.sub("", _CSS_COMMENT_RE.sub("", css))


def _css_rule_count(css: str) -> int:
    """Number of rule blocks (`{`), comments and @font-face blocks removed; @media etc. count as one more."""
    return _css_strip(css).count("{")


def _inline_css_blocks(markup: str) -> list[str]:
    return [m.group(1) for m in _STYLE_BLOCK_RE.finditer(markup)]


def _inline_css_rules(markup: str) -> int:
    return sum(_css_rule_count(b) for b in _inline_css_blocks(markup))


def _css_imports(css: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None).strip()
            for m in _CSS_IMPORT_RE.finditer(_CSS_COMMENT_RE.sub("", css))
            if any(g is not None for g in m.groups())]


def _css_urls(css: str) -> list[str]:
    """url(...) targets outside @font-face blocks and @import rules (those are not image references)."""
    c = _CSS_IMPORT_RE.sub("", _css_strip(css))
    return [next(g for g in m.groups() if g is not None).strip()
            for m in _CSS_URL_RE.finditer(c) if any(g is not None for g in m.groups())]


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


XHTML_TYPES = {"application/xhtml+xml", "text/html"}
XHTML_EXT = (".xhtml", ".html", ".htm", ".xht")
# spine items of these types hold bytes, not markup: never parsed
_BINARY_PREFIXES = ("audio/", "video/", "font/", "application/octet-stream", "application/font",
                    "application/vnd.ms-opentype", "application/x-font")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _nfd(s: str) -> str:
    return unicodedata.normalize("NFD", s)


def _redecode(name: str, flag_bits: int) -> str | None:
    """JSZip's view of a zip member name that Python decoded as cp437 (UTF-8 flag bit 11 not set):
    JSZip always decodes names as UTF-8. None when the name is flagged UTF-8 or is not valid UTF-8."""
    if flag_bits & 0x800:
        return None
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None


def _basename(href: str) -> str:
    h = unquote((href or "").split("#")[0].split("?")[0]).strip()
    return posixpath.basename(h) or (href or "").strip()


class InputBook:
    """Parsed input EPUB: spine (with the app's chapter mapping), images, TOC."""

    def __init__(self, entry: dict, out_dir: Path):
        self.epub = entry_path(entry)
        self.dir = out_dir / "input"
        _safe_unzip(self.epub, self.dir)
        with zipfile.ZipFile(self.epub) as z:
            infos = z.infolist()
        namelist = [i.filename for i in infos]
        self.names = set(namelist)
        self.casefold_collisions = casefold_collisions(namelist)
        # name lookup: exact, NFC/NFD and the cp437 -> UTF-8 re-decoding (JSZip's view of the name)
        self.true_name: dict[str, str] = {}
        self._lookup: dict[str, str] = {}
        for info in infos:
            self.true_name[info.filename] = _redecode(info.filename, info.flag_bits) or info.filename
        for n in namelist:
            self._lookup.setdefault(n, n)
        for n in namelist:
            for v in (n, self.true_name[n]):
                for k in (v, _nfc(v), _nfd(v)):
                    self._lookup.setdefault(k, n)
        self.app_names = set(self.true_name.values())
        self.doc_errors: dict[str, str] = {}
        self._junk_errors: dict[str, str] = {}   # documents the oracle does not evaluate (non-XHTML)
        cont = self._xml(self.dir / "META-INF/container.xml")
        rf = next((e for e in cont.iter() if _local(e) == "rootfile" and _attr(e, "full-path")), None)
        if rf is None:
            raise RuntimeError("container.xml has no rootfile")
        opf_raw = _attr(rf, "full-path").lstrip("/")
        self.opf_path = self.canon(opf_raw) or opf_raw
        opf = self._xml(self.dir / self.opf_path)
        self.opf_dir = posixpath.dirname(self.true_name.get(self.opf_path, self.opf_path))
        self.manifest: dict[str, dict] = {}
        self.by_path: dict[str, dict] = {}
        for it in (e for e in opf.iter() if _local(e) == "item"):
            iid, href = _attr(it, "id"), _attr(it, "href")
            if iid is None or href is None:
                continue
            path = self.join(self.opf_path, href.split("#")[0])
            self.manifest[iid] = {"id": iid, "href": href, "mt": (_attr(it, "media-type") or "").strip(),
                                  "props": _attr(it, "properties") or "",
                                  "fallback": (_attr(it, "fallback") or "").strip() or None,
                                  "path": path}
            self.by_path.setdefault(path, self.manifest[iid])
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
        # URI-decoded name with JSZip (names decoded as UTF-8, no ../ normalisation), and skips files it
        # cannot find or parse. The oracle finds the member NFC/NFD- and cp437-insensitively (`path`)
        # but keeps `app_found` strict: whether the app's own lookup succeeds.
        self.spine: list[dict] = []
        for ir in (e for e in (spine_el if spine_el is not None else []) if _local(e) == "itemref"):
            it = self.manifest.get(_attr(ir, "idref") or "")
            if not it:
                continue
            raw = (self.opf_dir + "/" if self.opf_dir else "") + it["href"].split("#")[0]
            app_found = raw in self.app_names or unquote(raw) in self.app_names
            present = it["path"] in self.names
            path = it["path"] if present else (self.canon(raw) or self.canon(unquote(raw)))
            if path is None:
                continue  # genuinely missing from the zip: not counted
            self.spine.append({"path": path, "href": it["href"], "mt": it["mt"], "id": it["id"],
                               "xhtml": self._is_xhtml(it), "fallback_type": self._fallback_type(it),
                               "app_found": app_found, "linear": (_attr(ir, "linear") or "yes") != "no"})
        self.spine_paths = {s["path"]: i for i, s in enumerate(self.spine)}
        self.spine_missing = sum(1 for e in (spine_el if spine_el is not None else [])
                                 if _local(e) == "itemref") - len(self.spine)
        self.cover_path = self._cover_path(opf)
        self._docs: dict[str, object] = {}
        self._css: dict | None = None
        # MOBI v6: per spine path, what prune_hidden removed ({elements, chars, anchors, unmapped})
        self.hidden: dict[str, dict] = {}

    # names -------------------------------------------------------------------
    def canon(self, path: str | None) -> str | None:
        """The zip member name (as Python lists it) for a path, matching exactly, URI-decoded,
        NFC/NFD-normalised, or by the cp437 -> UTF-8 re-decoded name; None when not in the zip."""
        if not path:
            return None
        for cand in (path, unquote(path)):
            for k in (cand, _nfc(cand), _nfd(cand)):
                hit = self._lookup.get(k)
                if hit is not None:
                    return hit
        return None

    def join(self, base_member: str, href: str) -> str:
        """href (URL-encoded, no fragment) resolved against a zip member; the canonical member name
        when it exists in the zip, else the normalised path."""
        p = _join(self.true_name.get(base_member, base_member), href)
        return self.canon(p) or p

    # manifest types ----------------------------------------------------------
    @staticmethod
    def _is_xhtml(it: dict) -> bool:
        """XHTML/HTML by the manifest media-type; a missing or text/* (text/plain, legacy
        text/x-oeb1-document) one on a .xhtml/.html file is a mislabelled document, which the app
        still reads as XHTML."""
        mt = it["mt"].lower()
        if mt in XHTML_TYPES:
            return True
        return (not mt or mt.startswith("text/")) and it["path"].lower().endswith(XHTML_EXT)

    def _fallback_chain(self, it: dict) -> list[dict]:
        chain, seen = [], {it["id"]}
        while it and it.get("fallback") and it["fallback"] not in seen:
            seen.add(it["fallback"])
            it = self.manifest.get(it["fallback"])
            if it:
                chain.append(it)
        return chain

    def _fallback_type(self, it: dict) -> str | None:
        """Media type of the first XHTML/HTML item of the manifest fallback chain, else None."""
        return next((c["mt"] for c in self._fallback_chain(it) if self._is_xhtml(c)), None)

    def image_chain(self, path: str) -> list[str]:
        """[path, its fallback image, the fallback's fallback, ...] while the fallback is an image."""
        chain, it = [path], self.by_path.get(path)
        for c in self._fallback_chain(it) if it else []:
            if not c["mt"].startswith("image/") or c["path"] in chain:
                break
            chain.append(c["path"])
        return chain

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
            sp = next((s for s in self.spine if s["path"] == path), None)
            if sp is not None and not sp["xhtml"] and self.is_binary(sp):
                self._docs[path] = _empty_doc()
            elif sp is not None and not sp["xhtml"]:
                # foreign spine item (svg/xml/json/...): errors are not reported, JSON & co. are UTF-8
                self._docs[path] = _parse_or_empty(self.dir / path, self._junk_errors, path, utf8=True)
            else:
                self._docs[path] = _parse_or_empty(self.dir / path, self.doc_errors, path)
        return self._docs[path]

    def prune_hidden(self, path: str, tags: list[str], hid: list[int]) -> dict:
        """Remove from the parsed document of `path` the elements the author CSS hides, as the MOBI
        v6 writer does (its readers ignore CSS). `tags`/`hid` come from _collect(hidden=True): the
        local names of every element under <body> in document order as Chromium parsed the file,
        and the indexes of the topmost hidden ones; they are mapped onto lxml's elements by aligning
        the two name sequences (identical for XHTML; the parsers may differ in HTML mode). An
        id/name inside a removed subtree stays as an empty <a id|name> (the writer keeps link
        targets the same way); the removed element's tail text stays."""
        root = self.doc(path)
        body = _find_body(root)
        mine = [e for e in body.iter() if isinstance(e.tag, str)]
        names = [_local(e) for e in mine]
        if names == tags:
            m = dict(enumerate(range(len(mine))))
        else:
            m = {}
            for blk in difflib.SequenceMatcher(None, tags, names, autojunk=False).get_matching_blocks():
                m.update((blk.a + d, blk.b + d) for d in range(blk.size))
        st = {"elements": 0, "chars": 0, "anchors": 0, "unmapped": 0}
        for k in hid:
            el = mine[m[k]] if k in m else None
            if el is None:
                st["unmapped"] += 1
                continue
            parent = el.getparent()
            if el is body or parent is None or not any(a is body for a in el.iterancestors()):
                continue        # the body itself, or inside a subtree removed already
            st["elements"] += 1
            st["chars"] += len(_visible_text(el))
            st["anchors"] += sum(1 for a in _elements(el, {"a"}) if _attr(a, "href") is not None)
            ns = el.tag[1:].split("}")[0] if el.tag.startswith("{") else None
            pos = list(parent).index(el)
            keep = []
            for e in el.iter():
                ids = {k2: v for k2 in ("id", "name") if isinstance(e.tag, str) and (v := _attr(e, k2))}
                if ids:
                    keep.append(parent.makeelement(f"{{{ns}}}a" if ns else "a", ids))
            for d, a in enumerate(keep):
                parent.insert(pos + d, a)
            tail = el.tail
            parent.remove(el)
            if tail:
                prev = keep[-1] if keep else (parent[pos - 1] if pos > 0 else None)
                if prev is not None:
                    prev.tail = (prev.tail or "") + tail
                else:
                    parent.text = (parent.text or "") + tail
        self.hidden[path] = st
        return st

    def is_binary(self, sp: dict) -> bool:
        """Spine item whose bytes are not text (raster images, media, fonts): never parsed."""
        mt = sp["mt"].lower()
        return (mt.startswith("image/") and "svg" not in mt) or mt.startswith(_BINARY_PREFIXES)

    def mark_skipped(self, skipped: list[str]) -> None:
        """Chapters the app logged as `Skip chapter: <path> ...` produced no skeleton."""
        for s in self.spine:
            names = {s["path"], self.true_name.get(s["path"], s["path"])}
            if any(x.strip().startswith(n) for x in skipped for n in names):
                s["app_found"] = False

    # css ---------------------------------------------------------------------
    def _link_is_css(self, base: str, el, href: str) -> bool:
        ext = posixpath.splitext(href.split("#")[0].split("?")[0])[1].lower()
        if ext == ".xpgt":
            return False
        t = (_attr(el, "type") or "").strip().lower()
        if t:
            return t.startswith("text/css")
        mt = (self.by_path.get(self.join(base, href.split("#")[0].split("?")[0])) or {}).get("mt", "")
        return not mt or mt == "text/css" or ext == ".css"

    def css_info(self) -> dict:
        """Style sheets reachable from a (XHTML) spine document: <link rel=stylesheet> to CSS (not .xpgt
        or another type), <style>, and @import chains. Rule counts exclude @font-face blocks;
        `unreferenced` counts the manifest's other text/css items. `urls` lists [base member, url()]
        of the reachable CSS outside @font-face (image references)."""
        if self._css is not None:
            return self._css
        rules: dict[str, int] = {}
        inline = 0
        urls: list[tuple[str, str]] = []

        def follow(base: str, href: str) -> None:
            href = (href or "").strip()
            if not href or _has_scheme(href) or href.startswith("//"):
                return
            t = self.join(base, href.split("#")[0].split("?")[0])
            if t not in rules and t in self.names and (self.dir / t).is_file():
                css = (self.dir / t).read_text("utf-8", errors="replace")
                rules[t] = _css_rule_count(css)
                urls.extend((t, u) for u in _css_urls(css))
                for imp in _css_imports(css):
                    follow(t, imp)

        for sp in self.spine:
            if not sp["xhtml"]:
                continue
            doc = self.doc(sp["path"])
            for el in _elements(doc, {"link"}):
                if "stylesheet" in (_attr(el, "rel") or "").lower().split():
                    href = (_attr(el, "href") or "").strip()
                    if href and not _has_scheme(href) and self._link_is_css(sp["path"], el, href):
                        follow(sp["path"], href)
            for el in _elements(doc, {"style"}):
                if (_attr(el, "type") or "text/css").strip().lower().startswith("text/css"):
                    css = "".join(el.itertext())
                    inline += _css_rule_count(css)
                    urls.extend((sp["path"], u) for u in _css_urls(css))
                    for imp in _css_imports(css):
                        follow(sp["path"], imp)
        unref, seen = 0, set(rules)
        for it in self.manifest.values():
            f = self.dir / it["path"]
            if it["mt"] == "text/css" and it["path"] not in seen and it["path"] in self.names and f.is_file():
                seen.add(it["path"])
                unref += _css_rule_count(f.read_text("utf-8", errors="replace"))
        self._css = {"referenced": sum(rules.values()) + inline, "unreferenced": unref,
                     "urls": sorted(set(urls))}
        return self._css

    def css_rules(self) -> int:
        """Rule blocks in style sheets reachable from a spine document (see css_info)."""
        return self.css_info()["referenced"]

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
        """The TOC the writer would read: the nav document when it has entries, else the NCX (when
        both exist and the nav is empty the NCX wins, as the longer one)."""
        ncx_entries, nav_entries = [], []
        ncx_id = self.spine_toc_id if self.spine_toc_id in self.manifest else next(
            (k for k, v in self.manifest.items() if v["mt"] == "application/x-dtbncx+xml"), None)
        if ncx_id and (self.dir / self.manifest[ncx_id]["path"]).exists():
            ncx_entries = ncx_toc(self.dir / self.manifest[ncx_id]["path"])
        nav_id = next((k for k, v in self.manifest.items() if "nav" in v["props"].split()), None)
        if nav_id and (self.dir / self.manifest[nav_id]["path"]).exists():
            nav_entries = nav_toc(self.dir / self.manifest[nav_id]["path"])
        if nav_entries:
            return nav_entries, "nav"
        return ncx_entries, ("ncx" if ncx_entries else "none")


def _toc_label(label_el, href: str | None, title: str | None = None) -> str:
    """Visible text of a TOC label; for an image-only one (nothing visible) the first <img> alt, then
    the title, then the target's file name, as a reader would show it."""
    txt = _visible_text(label_el) if label_el is not None else ""
    if txt or label_el is None:
        return txt
    imgs = [e for e in label_el.iter() if isinstance(e.tag, str) and _local(e) in ("img", "image")]
    for im in imgs:
        alt = _norm_ws(_attr(im, "alt") or "")
        if alt:
            return alt
    for t in [title, _attr(label_el, "title"), *(_attr(im, "title") for im in imgs)]:
        t = _norm_ws(t or "")
        if t:
            return t
    return _basename(href) if href else ""


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
            label = _visible_text(txt) if txt is not None else ""
            if not label and lab is not None:
                label = _toc_label(lab, None)   # an <img alt/title> label; an empty one stays empty
            out.append((label, depth))
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
            out.append((_toc_label(lab, _attr(lab, "href") if lab is not None else None)
                        if lab is not None else "", depth))
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


def _non_xhtml_handling(book: InputBook, outb: OutputBook, mode: str, pairs) -> list[dict]:
    """One record per spine item whose manifest type is not XHTML/HTML (svg, raster image, xml, json,
    ...): not compared as text. `output_has_img`: the output chapter holds an <img>; `output_has_content`:
    an <img> or any visible text (None in concat mode, where chapters cannot be told apart)."""
    out = []
    for i, s in enumerate(book.spine):
        if s["xhtml"]:
            continue
        rec = {"item": i, "path": s["path"], "type": s["mt"], "fallback_type": s["fallback_type"],
               "app_found": s["app_found"], "output_has_img": None, "output_has_content": None}
        if mode == "aligned":
            p = pairs[i]
            if p is None:
                rec["output_has_img"] = rec["output_has_content"] = False
            else:
                d = outb.doc(p)
                rec["output_has_img"] = bool(_elements(_find_body(d), IMAGE_TAGS))
                rec["output_has_content"] = rec["output_has_img"] or bool(_body_text(d))
        out.append(rec)
    return out


def inv_text(book: InputBook, outb: OutputBook, mode: str, pairs) -> dict:
    # Only spine items whose manifest media-type is XHTML/HTML are compared as text. Others (svg,
    # raster images, xml, json, ... whatever their fallback) are listed in non_xhtml_handling.
    xi = [i for i, s in enumerate(book.spine) if s["xhtml"]]
    in_txt = [_body_text(book.doc(book.spine[i]["path"])) for i in xi]
    out_docs_txt = [_body_text(outb.doc(p)) for p in outb.docs]
    handling = _non_xhtml_handling(book, outb, mode, pairs)
    res = {"spine_items": len(in_txt), "matching_items": 0, "first_diff": None, "mode": mode,
           "output_items": len(outb.docs),
           "non_xhtml_spine_items": len(handling), "non_xhtml_handling": handling,
           "app_skipped": sum(1 for s in book.spine if not s["app_found"]),
           "spine_missing_in_zip": book.spine_missing, "whitespace_only_diffs": 0,
           "chars_in": sum(len(t) for t in in_txt), "chars_out": sum(len(t) for t in out_docs_txt)}
    all_in, all_out = " ".join(in_txt), " ".join(out_docs_txt)
    res["fffd_in"], res["fffd_out"] = all_in.count("\ufffd"), all_out.count("\ufffd")
    res["replacement_chars"], res["replacement_chars_input"] = res["fffd_out"], res["fffd_in"]
    res["css_in_text"] = bool(_CSS_LIKE.search(all_out))
    res["css_in_text_input"] = bool(_CSS_LIKE.search(all_in))
    if mode == "aligned":
        for i, t in zip(xi, in_txt, strict=True):
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
    for n, (i, t) in enumerate(zip(xi, in_txt, strict=True)):
        t_ns, t_map = _strip_ws(t)
        j = out_ns.find(t_ns, pos)
        if j >= 0 and j - pos > CONCAT_SLACK:
            nxt = next((x[:24] for x in in_ns[n + 1:] if x), "")
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


# elements that carry an image reference: img@src/@srcset, svg image@href, <source srcset> (picture),
# video@poster, object@data
REF_TAGS = {"img", "image", "source", "video", "object"}


def _ref_attr(e) -> str | None:
    """The attribute holding the element's primary (single) image reference."""
    t = _local(e)
    if t == "img":
        return _attr(e, "src")
    if t == "image":
        return e.get(f"{{{XLINK_NS}}}href") or _attr(e, "href")
    if t == "video":
        return _attr(e, "poster")
    if t == "object":
        return _attr(e, "data")
    return None


def _parse_srcset(value: str | None) -> list[str]:
    """Candidate URLs of a srcset attribute (HTML spec tokenisation, descriptors dropped)."""
    out: list[str] = []
    s, i, n = value or "", 0, len(value or "")
    while i < n:
        while i < n and (s[i].isspace() or s[i] == ","):
            i += 1
        j = i
        while j < n and not s[j].isspace():
            j += 1
        url = s[i:j]
        i = j
        if not url:
            break
        if url.endswith(","):
            out.append(url.rstrip(","))
            continue
        out.append(url)
        depth = 0                      # skip the descriptor up to the next comma outside parentheses
        while i < n and not (s[i] == "," and depth == 0):
            depth += (s[i] == "(") - (s[i] == ")")
            i += 1
    return [u for u in out if u]


def _text_index(root) -> tuple[str, dict[str, int], list[tuple[int, object]]]:
    """Walk the body in document order. Returns (whitespace-free visible text, {id/name: offset of
    the element's start in that text}, [(offset, element)] for every REF_TAGS element)."""
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
        if _local(e) in REF_TAGS:
            imgs.append((n, e))
        add(e.text)
        for c in e:
            walk(c)
            add(c.tail)
    walk(_find_body(root))
    return "".join(buf), ids, imgs


_CTX = 24   # chars of text before/after an image that identify its place in the text
_KIND = {"img": "src", "image": "src", "video": "poster", "object": "object", "source": "srcset"}


def _raw_record_hashes(path: Path | None) -> set[str]:
    """sha256 of every PalmDB record of the output file: a resource the writer stored as raw bytes
    is in here even when KindleUnpack does not extract it."""
    if path is None or not Path(path).is_file():
        return set()
    try:
        return {hashlib.sha256(r).hexdigest() for r in _pdb_records(Path(path).read_bytes())}
    except Exception:
        return set()


_EMBED_RE = re.compile(r"^kindle:embed:([0-9A-Va-v]+)(?:\?.*)?$")


def _embed_index(url: str) -> int | None:
    """1-based resource index of a kindle:embed:XXXX[?mime=...] URL (XXXX is base 32: 0-9, A-V)."""
    m = _EMBED_RE.match(url.strip())
    return int(m.group(1), 32) if m else None


def _first_resource(path: Path | None) -> int | None:
    """PalmDB record number of the first resource record, as KindleUnpack computes it
    (`mh.firstresource`): the 'first image index' of the (KF8) MOBI header plus the record where
    that header starts (0, or the one after a BOUNDARY record of a combined file)."""
    if path is None or not Path(path).is_file():
        return None
    try:
        recs = _pdb_records(Path(path).read_bytes())
        start = next((i + 1 for i, r in enumerate(recs) if r[:8] == b"BOUNDARY"), 0)
        ofst = struct.unpack_from(">L", recs[start], 0x6C)[0]   # offset from the record start
        return None if ofst == 0xFFFFFFFF else ofst + start
    except Exception:
        return None


def _embed_file(outb: OutputBook, first_res: int | None, url: str) -> Path | None:
    """The file KindleUnpack extracted for a kindle:embed:XXXX URL it left unrewritten (it rewrites
    only <img>/<image> tags, style attributes and url() in CSS: not video@poster, object@data,
    <source srcset>, ...). KindleUnpack keeps `rscnames[XXXX - 1]` for the resource records from
    `first_res` on and names every image after its record number (image%05d / cover%05d /
    thumb%05d). None when the record is not an extracted image."""
    n = _embed_index(url)
    if n is None or first_res is None or n < 1:
        return None
    rec = first_res + n - 1
    for d in (outb.dir / "mobi8/OEBPS/Images", outb.dir / "mobi7/Images"):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.is_file() and not f.name.startswith("HD") and re.fullmatch(
                        rf"(?:image|cover|thumb){rec:05d}\..+", f.name):
                    return f
    return None


def inv_images(book: InputBook, outb: OutputBook, mode: str, pairs, raw_file: Path | None = None) -> dict:
    """Image presence (by hash) and per-reference correctness.

    References are img@src, svg image@href, video@poster, object@data, img/source@srcset, and url()
    in the style sheets reachable from the spine (AZW3 only: MOBI v6 has no style sheets). They are
    paired by their place in the text (the visible text just before and after the element, difflib
    over the sequence), not blindly by position, so a dropped/extra reference does not shift every
    later pairing; data:, external and non-manifest input references are left out. A pair is correct
    when the output reference resolves to a byte-identical copy of the input image. When the
    referenced manifest item has a `fallback` image, that image (the end of the chain) is the
    expected one, and any image of the chain is accepted.
    srcset: one reference per element; it is correct when the writer dropped the attribute and an
    <img>'s src still resolves (a <source> may simply go), or when every candidate left in the
    output resolves to a file; a candidate that is still a dangling relative path (`../images/x.png`)
    makes it a missing reference.
    A reference to an image that is in the output file as a raw record but that KindleUnpack does
    not extract (svg, avif, jxl, ...) is `refs_unextractable`, neither correct nor missing.

    `missing` = referenced input images (plus the cover) that are neither present by hash,
    present-but-changed (paired by reference to an output image that is not an input image, e.g.
    recompressed) nor `unextractable` (raw record in the output file). Unreferenced manifest images
    and srcset-only candidates do not count."""
    inp = book.images()
    outp = outb.images()
    raw = _raw_record_hashes(raw_file)
    in_hashes = {v["sha256"] for v in inp.values()}
    res = {"input": len(inp), "output": len(outp),
           "matched_by_hash": sum(1 for v in inp.values() if v["sha256"] in outp),
           "dimension_mismatch": 0,
           "refs_total": 0, "refs_correct": 0, "refs_wrong_image": 0, "refs_missing": 0,
           "refs_unextractable": 0, "refs_by_kind": {}, "refs_missing_by_kind": {},
           "first_wrong_ref": None, "first_missing_ref": None}

    res_start = _first_resource(raw_file)
    first_res = res_start if outb.kind == "kf8" else None
    try:
        raw_recs = _pdb_records(Path(raw_file).read_bytes()) if res_start is not None else []
    except Exception:
        raw_recs = []

    def record_exists(n: int | None, start: int | None) -> bool:
        return n is not None and start is not None and 1 <= n and start + n - 1 < len(raw_recs) \
            and len(raw_recs[start + n - 1]) > 0

    def embed_resolves(url: str) -> bool:
        """kindle:embed:XXXX names a resource record that exists in the file (whether or not
        KindleUnpack could extract it, e.g. svg/xyz): the reference itself is sound."""
        return record_exists(_embed_index(url), first_res)

    def recindex_resolves(e) -> bool:
        """MOBI v6: an <img recindex="NNNNN"> KindleUnpack left as is (it rewrites recindex to a src
        only for the images it extracted) that names an existing resource record: as sound as an
        unrewritten kindle:embed in KF8."""
        ri = (_attr(e, "recindex") or "").strip()
        return outb.kind == "mobi7" and ri.isdigit() and record_exists(int(ri), res_start)

    def in_info(base: str, e):
        """(primary manifest path | None, [manifest paths of the srcset candidates]) of one input
        element."""
        tag = _local(e)
        prim = None
        if tag != "source" and not (tag == "object" and any(
                _local(c) in IMAGE_TAGS for c in e.iter() if c is not e and isinstance(c.tag, str))):
            r = (_ref_attr(e) or "").strip()
            if r and not r.startswith("data:") and not _has_scheme(r):
                ip = book.join(base, r.split("#")[0].split("?")[0])
                if ip in inp:
                    prim = ip
        cands = []
        if tag in ("img", "source"):
            for u in _parse_srcset(_attr(e, "srcset")):
                if not u.startswith("data:") and not _has_scheme(u):
                    ip = book.join(base, u.split("#")[0].split("?")[0])
                    if ip in inp:
                        cands.append(ip)
        return prim, cands

    def in_refs(i):
        """(text, primary records, srcset records) of one spine item, each as [(offset, record)].
        Primary records (img src, svg image href, video poster, object data) are paired with the
        output's primary records. An <img>/<image> without a manifest reference (data: URI, remote,
        missing src) takes part in the pairing as a placeholder (primary None, never evaluated), just
        as the output side lists every <img>/<image> without a usable src: otherwise the output's
        src-less counterpart of a data: image steals the pairing of a real image that has the same
        (e.g. empty) text context. The srcset records (every <img>, every <source> with candidates)
        are paired apart: a <source> shares its text context with the <img> next to it and must
        never be paired with it."""
        s = book.spine[i]
        if not s["xhtml"]:
            return "", [], []
        text, _, els = _text_index(book.doc(s["path"]))
        prim, ss, by_el = [], [], {}
        for off, e in els:
            p, cands = in_info(s["path"], e)
            tag = _local(e)
            if p or tag in IMAGE_TAGS:
                prim.append((off, {"tag": tag, "primary": p}))
            if cands or tag == "img":
                rec = {"tag": tag, "primary": p, "cands": cands or None, "sib": None, "el": e}
                ss.append((off, rec))
                by_el[e] = rec
        for _, rec in ss:
            par = rec["el"].getparent()
            if rec["tag"] == "source" and par is not None and _local(par) == "picture":
                rec["sib"] = next((by_el[c] for c in par if c in by_el and _local(c) == "img"), None)
        return text, prim, ss

    def out_file(p: Path, r: str):
        if _embed_index(r) is not None:      # left unrewritten by KindleUnpack (poster, object, ...)
            return _embed_file(outb, first_res, r)
        f = (p.parent / unquote(r.split("#")[0].split("?")[0])).resolve()
        if not f.is_file():
            # KindleUnpack names a record that is both CoverOffset and ThumbOffset "thumbNNNNN"
            # and leaves it in mobi7/Images only; the reference itself is still to that record.
            f = outb.dir / "mobi7/Images" / f.name
        return f if f.is_file() else None

    def out_refs(p: Path):
        """(text, primary records, srcset records) of one output document."""
        text, _, els = _text_index(outb.doc(p))
        prim, ss = [], []
        for off, e in els:
            tag = _local(e)
            r = (_ref_attr(e) or "").strip()
            usable = bool(r) and not r.startswith("data:") and (not _has_scheme(r) or _embed_index(r) is not None)
            h = None
            if usable:
                f = out_file(p, r)
                h = outb.file_hash(f) if f else None
            # an <img>/<image> without a src still takes part in the pairing (it is a lost image);
            # other element kinds only when they carry a reference of their own
            ok = h is not None or (usable and embed_resolves(r)) or (not r and tag == "img" and recindex_resolves(e))
            if usable or (not r and tag in IMAGE_TAGS):
                prim.append((off, {"tag": tag, "primary": h}))
            ss_attr = _attr(e, "srcset") if tag in ("img", "source") else None
            if tag == "img" or ss_attr is not None:
                cands = None
                if ss_attr is not None:
                    cands = []
                    for u in _parse_srcset(ss_attr):
                        if u.startswith("data:"):
                            cands.append(True)
                        elif _embed_index(u) is not None:
                            cands.append(out_file(p, u) is not None or embed_resolves(u))
                        elif _has_scheme(u):
                            cands.append(not u.lower().startswith("kindle:"))
                        else:
                            cands.append(out_file(p, u) is not None)
                ss.append((off, {"tag": tag, "primary": h, "resolved": ok, "ss": cands}))
        return text, prim, ss

    def keyed(parts, with_tag: bool = False):
        """Concatenate [(text, [(offset, value)])] and key every value by its text context (and,
        for the srcset records, its tag)."""
        full, items, base = [], [], 0
        for text, refs in parts:
            full.append(text)
            items += [(base + off, v) for off, v in refs]
            base += len(text)
        t = "".join(full)
        keys = [(t[max(0, o - _CTX):o], t[o:o + _CTX]) + ((v["tag"],) if with_tag else ()) for o, v in items]
        return keys, [v for _, v in items]

    def pair(ki, ko):
        """[(input index, output index | None)] from a difflib alignment of the two key sequences."""
        out: list[tuple[int, int | None]] = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ki, ko, autojunk=False).get_opcodes():
            if tag in ("equal", "replace"):
                n = min(i2 - i1, j2 - j1)
                out += [(i1 + d, j1 + d) for d in range(n)] + [(k, None) for k in range(i1 + n, i2)]
            elif tag == "delete":
                out += [(k, None) for k in range(i1, i2)]
        return sorted(out, key=lambda x: x[0])

    def group(gi, ins, outs):
        """ins/outs: [(text, primary records, srcset records)] of the group's documents."""
        ki, vi = keyed([(t, a) for t, a, _ in ins])
        ko, vo = keyed([(t, a) for t, a, _ in outs])
        kis, vis = keyed([(t, b) for t, _, b in ins], True)
        kos, vos = keyed([(t, b) for t, _, b in outs], True)
        return gi, ki, vi, ko, vo, kis, vis, kos, vos

    if mode == "aligned":
        groups = [group(i, [in_refs(i)], [out_refs(p)] if p is not None else []) for i, p in enumerate(pairs)]
    else:
        groups = [group(None, [in_refs(i) for i in range(len(book.spine))], [out_refs(p) for p in outb.docs])]

    referenced = {book.cover_path} if book.cover_path in inp else set()
    changed: set[str] = set()
    resized: set[str] = set()

    def expected(ip: str):
        """(expected image path, hashes accepted) for a referenced manifest image."""
        chain = [q for q in book.image_chain(ip) if q in inp]
        return chain[-1], {inp[q]["sha256"] for q in chain}

    def count(kind: str, status: str, gi, desc) -> None:
        res["refs_total"] += 1
        res["refs_by_kind"][kind] = res["refs_by_kind"].get(kind, 0) + 1
        if status == "correct":
            res["refs_correct"] += 1
        elif status == "unextractable":
            res["refs_unextractable"] += 1
        else:
            res["refs_missing"] += 1
            res["refs_missing_by_kind"][kind] = res["refs_missing_by_kind"].get(kind, 0) + 1
            if res["first_missing_ref"] is None:
                res["first_missing_ref"] = {"item": gi, "kind": kind, **desc}

    for gi, ki, vi, ko, vo, kis, vis, kos, vos in groups:
        for a in vi:
            if a["primary"]:
                referenced.add(expected(a["primary"])[0])
        for k, j in pair(ki, ko):
            a, b = vi[k], (vo[j] if j is not None else None)
            if not a["primary"]:
                continue        # placeholder (data:/remote/missing src): pairing only
            kind = _KIND[a["tag"]]
            ip, accept = expected(a["primary"])
            want = inp[ip]["sha256"]
            got = b["primary"] if b else None
            if got is not None and got in accept:
                count(kind, "correct", gi, {})
            elif got is None:
                unext = want in raw and want not in outp
                count(kind, "unextractable" if unext else "missing", gi, {"input": ip})
            else:
                res["refs_total"] += 1
                res["refs_by_kind"][kind] = res["refs_by_kind"].get(kind, 0) + 1
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
        # srcset: one reference per element carrying candidates
        match = {id(vis[k]): (vos[j] if j is not None else None) for k, j in pair(kis, kos)}
        for a in vis:
            if not a["cands"]:
                continue
            b = match.get(id(a))
            if b is not None and b["ss"] is not None:
                ok = all(b["ss"])                 # candidates kept: each must resolve
            elif a["tag"] == "source":
                # a dropped <source> is fine as long as the <img> next to it resolves
                sb = match.get(id(a["sib"])) if a["sib"] is not None else None
                ok = a["sib"] is None or (sb is not None and sb["resolved"])
            else:
                ok = b is not None and b["resolved"]    # srcset dropped, src resolves
            count("srcset", "correct" if ok else "missing", gi, {"input": a["cands"][:3]})

    # url() in the reachable style sheets (AZW3: the writer keeps style sheets; MOBI v6 has none)
    if outb.kind == "kf8":
        css_hashes: set[str] = set()
        blocks = [(f, f.read_text("utf-8", errors="replace")) for f in outb.oebps.rglob("*.css")]
        blocks += [(f, "\n".join(_inline_css_blocks(f.read_text("utf-8", errors="replace")))) for f in outb.docs]
        for f, css in blocks:
            for u in _css_urls(css):
                t = None
                if _embed_index(u) is not None:      # left unrewritten by KindleUnpack
                    t = _embed_file(outb, first_res, u)
                elif not u.startswith("data:") and not _has_scheme(u):
                    t = (f.parent / unquote(u.split("#")[0].split("?")[0])).resolve()
                if t is not None and t.is_file() and (h := outb.file_hash(t)):
                    css_hashes.add(h)
        for base, u in book.css_info()["urls"]:
            if not u or u.startswith(("data:", "#")) or _has_scheme(u):
                continue
            ip0 = book.join(base, u.split("#")[0].split("?")[0])
            if ip0 not in inp:
                continue
            ip, accept = expected(ip0)
            referenced.add(ip)
            want = inp[ip]["sha256"]
            if accept & css_hashes:
                count("css", "correct", None, {})
            else:
                unext = want in raw and want not in outp
                count("css", "unextractable" if unext else "missing", None, {"input": ip, "css": base})

    cover = book.cover_path if book.cover_path in inp else None
    if cover and inp[cover]["sha256"] not in outp and any(
            h not in in_hashes and any(("cover" in n or "thumb" in n) for n in v["names"])
            for h, v in outp.items()):
        changed.add(cover)
    present = {q for q in referenced if inp[q]["sha256"] in outp}
    unextractable = {q for q in referenced - present - changed if inp[q]["sha256"] in raw}
    res["dimension_mismatch"] = len(resized)
    res["referenced"] = len(referenced)
    res["referenced_matched_by_hash"] = len(present)
    res["referenced_changed"] = len(changed - present)
    res["unextractable"] = len(unextractable)
    res["missing"] = len(referenced - present - changed - unextractable)
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
    in_anchors = [_anchors(book.doc(s["path"])) if s["xhtml"] else [] for s in book.spine]
    in_idx_cache: dict[int, tuple] = {}

    def in_index(t: int):
        if t not in in_idx_cache:
            in_idx_cache[t] = _text_index(book.doc(book.spine[t]["path"]))
        return in_idx_cache[t]

    body_ids: dict[int, set[str]] = {}

    def body_frag(t: int, frag: str) -> bool:
        """Is frag the id/name of the target document's <body> (its link target is the chapter start)?"""
        if t not in body_ids:
            b = _find_body(book.doc(book.spine[t]["path"]))
            body_ids[t] = {v for v in (_attr(b, "id"), _attr(b, "name")) if v}
        return frag in body_ids[t]

    links = []  # (spine idx, anchor index in that doc, target spine idx, fragment)
    for i, s in enumerate(book.spine):
        for k, (_, href) in enumerate(in_anchors[i]):
            if not href or _has_scheme(href):
                continue
            path, _, frag = href.partition("#")
            if path:
                tgt = book.spine_paths.get(book.join(s["path"], path))
                if tgt is None or not book.spine[tgt]["xhtml"]:
                    continue    # not a spine item, or one that is not compared as XHTML
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
                  # a fragment link must land on an anchor (or, for <body id>, on the chapter start)
                  and not (frag and not ofrag and not body_frag(tgt, frag)))
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
  if (!body) return {perr, bodyFS: 16, baseFS: 16, els: [], tags: [], hid: [], vt: []};
  let mobiBase = null;
  if (args.mobiCss != null) {
    // MOBI v6 output: a MOBI 6 reader's defaults and the presentational markup it honours, as CSS
    // (see MOBI_BASE_CSS, MOBI_CSS)
    const sheet = css => {
      const st = document.createElementNS('http://www.w3.org/1999/xhtml', 'style');
      st.textContent = css;
      (document.head || document.documentElement).appendChild(st);
      return st;
    };
    mobiBase = sheet(args.mobiBaseCss);
    sheet(args.mobiCss);
    const skip = new Set(args.mobiNoBox);
    const unit = v => /\d$/.test(v) ? v + 'px' : v;    // Calibre ensure_unit: a bare number is px
    for (const e of body.querySelectorAll('[width], [height]')) {
      if (skip.has((e.localName || '').toLowerCase()) || !e.style) continue;
      const w = (e.getAttribute('width') || '').trim(), h = (e.getAttribute('height') || '').trim();
      if (/\d/.test(w)) e.style.textIndent = unit(w);
      if (/\d/.test(h)) e.style.marginTop = unit(h);
    }
  }
  const bodyFS = parseFloat(getComputedStyle(body).fontSize) || 16;
  const idx = new Map();
  const els = [], all = [];
  // Visibility record (see _vis_*): [own text, rendered visibly] per element with text of its own,
  // measured with every author rule applied, before the baseline pass below disables them
  const vt = [], rng = document.createRange(), vw = window.innerWidth || 600;
  const clipMemo = new Map();
  const pcts = v => Array.from(v.matchAll(/(-?[\d.]+)%/g), m => parseFloat(m[1]));
  const selfClips = (e, cs) => {
    const pos = cs.position;
    if ((pos === 'absolute' || pos === 'fixed') && /^rect\(/.test(cs.clip || '')) {    // clip: rect(1px,1px,1px,1px)
      const n = (cs.clip.match(/^rect\((.*)\)$/) || [, ''])[1].split(/[,\s]+/).map(parseFloat);
      if (n.length === 4 && !n.some(isNaN) && (n[1] - n[3] <= 1 || n[2] - n[0] <= 1)) return true;
    }
    const cp = cs.clipPath || '';
    if (/^inset\(/.test(cp)) {                                                      // clip-path: inset(50%)
      const v = pcts(cp.replace(/\bround\b.*$/, ''));
      if (v.length) {
        const [t, r = t, b = t, l = r] = v;
        if (t + b >= 100 || l + r >= 100) return true;
      }
    } else if (/^circle\(\s*0(px|%)?[\s)]/.test(cp)) return true;
    if ((cs.overflowX !== 'visible' || cs.overflowY !== 'visible') && cs.display !== 'inline' &&
        cs.display !== 'contents') {                                                // 1px box, overflow hidden
      const r = e.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) return true;
    }
    return false;
  };
  const clippedUp = (e, cs) => {
    if (!e || e === document.documentElement) return false;
    if (clipMemo.has(e)) return clipMemo.get(e);
    cs = cs || getComputedStyle(e);
    const v = selfClips(e, cs) || clippedUp(e.parentElement, null);
    clipMemo.set(e, v);
    return v;
  };
  const rendered = (e, cs) => {
    if (cs.visibility !== 'visible' || clippedUp(e, cs)) return false;
    for (const c of e.childNodes) {
      if (c.nodeType !== 3 || !/\S/.test(c.data)) continue;
      rng.selectNodeContents(c);
      for (const r of rng.getClientRects())
        if (r.width > 0 && r.height > 0 && r.right > -500 && r.bottom > -500 && r.left < vw + 500) return true;
    }
    return false;
  };
  const isHidden = cs => cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse';
  // MOBI v6 hidden set (the writer's cssHiddenOffPage, only for position absolute|fixed): a side moved
  // 500 px or more off the page, clip: rect() with every side <= 1 px, clip-path inset(>= 50 %) or
  // circle(0), a width or height <= 1 px with overflow hidden|clip
  const writerHidden = (e, cs) => {
    if (cs.position !== 'absolute' && cs.position !== 'fixed') return false;
    // computed values (computedStyleMap), not the resolved ones getComputedStyle gives a positioned
    // element: `bottom: auto` resolves to a negative px far down a long page
    const sm = e.computedStyleMap();
    const px = k => {
      const v = sm.get(k);
      return v instanceof CSSUnitValue ? (v.unit === 'px' ? v.value : v.unit === 'percent' ? v.value * 6 : NaN) : NaN;
    };
    if (['left', 'top', 'right', 'bottom'].some(k => px(k) <= -500)) return true;
    const clip = /^rect\(([^)]*)\)$/i.exec((cs.clip || '').trim());
    if (clip && clip[1].split(/[\s,]+/).filter(Boolean).every(v => /^auto$/i.test(v) ? false : parseFloat(v) <= 1)) return true;
    const cp = (cs.clipPath || '').trim().toLowerCase();
    if (/^inset\(\s*(?:5\d|[6-9]\d|100)(?:\.\d+)?%/.test(cp) || /^circle\(\s*0(?:px|%)?\s*(?:at\b|\))/.test(cp)) return true;
    return (px('width') <= 1 || px('height') <= 1) && /^(hidden|clip)$/i.test(cs.overflowX) && /^(hidden|clip)$/i.test(cs.overflowY);
  };
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_ELEMENT);
  for (let e = walker.currentNode; e; e = walker.nextNode()) {
    const tag = (e.localName || '').toLowerCase();
    all.push(tag);
    if (tag === 'style' || tag === 'script' || tag === 'parsererror') continue;
    let own = '';
    for (const c of e.childNodes) if (c.nodeType === 3) own += c.data;
    // full text only for alignment anchors (own text, or an image/hr): keeps the payload small
    const full = (own.trim() || anchorTags.has(tag)) ? (e.textContent || '') : '';
    const cs = getComputedStyle(e);
    if (own.trim()) vt.push([own, rendered(e, cs) ? 1 : 0]);
    const parent = e.parentElement && idx.has(e.parentElement) ? idx.get(e.parentElement) : -1;
    idx.set(e, els.length);
    els.push([tag, own, props.map(p => cs.getPropertyValue(p)), parent, e, full, all.length - 1,
              args.hidden && e !== body && (isHidden(cs) || writerHidden(e, cs))]);
  }
  // Baseline: the same DOM with every author style sheet and style attribute removed, i.e. what
  // the UA (plus presentational HTML attributes) gives. A property "carries author CSS" when the
  // authored value differs from this baseline.
  for (const sh of Array.from(document.styleSheets)) { try { sh.disabled = true; } catch (_) {} }
  // MOBI v6 output: the baseline is the MOBI reader's defaults (its "UA" sheet stays on)
  if (mobiBase && mobiBase.sheet) mobiBase.sheet.disabled = false;
  for (const r of els) if (r[4].removeAttribute) r[4].removeAttribute('style');
  const baseFS = parseFloat(getComputedStyle(body).fontSize) || 16;
  for (const r of els) {
    const cs = getComputedStyle(r[4]);
    // hidden by the author CSS (or the hidden attribute, which the writer removes too), not by another UA rule
    r[7] = r[7] && (!isHidden(cs) || r[4].hasAttribute('hidden'));
    r[4] = props.map(p => cs.getPropertyValue(p));
  }
  if (!args.hidden) return {perr, bodyFS, baseFS, els: els.map(r => r.slice(0, 6)), tags: [], hid: [], vt};
  // An element the author CSS hides goes with its whole subtree (as the MOBI writer removes it);
  // hid: its index in `all` (every element under body, document order), for the caller's mapping
  const gone = new Array(els.length).fill(false), newIdx = new Array(els.length).fill(-1);
  const kept = [], hid = [];
  els.forEach((r, k) => {
    const up = r[3] >= 0 && gone[r[3]];
    gone[k] = up || r[7];
    if (r[7] && !up) hid.push(r[6]);
    if (gone[k]) return;
    newIdx[k] = kept.length;
    kept.push([r[0], r[1], r[2], r[3] >= 0 ? newIdx[r[3]] : -1, r[4], r[5]]);
  });
  return {perr, bodyFS, baseFS, els: kept, tags: all, hid, vt};
}
"""

# MOBI v6 output: a MOBI 6 reader's defaults (Calibre's MobiReader base CSS; `body {text-align:
# justify}` left out, justification is a reader setting) and what it makes of the writer's
# presentational markup (upshift_markup: align -> text-align, height -> margin-top, width ->
# text-indent, applied by _COLLECT_JS; <font size=N> keeps the HTML legacy sizes, which are the
# writer's own, FONT_PX 10/13/16/18/24/32/48, 3 = normal)
MOBI_BASE_CSS = "p { margin: 0; text-indent: 1.5em }\nblockquote { margin: 0 0 0 2em }"
# properties whose MOBI reader default differs from a browser's: not a conversion difference when
# the input leaves them at the browser default and the output at the MOBI default
MOBI_READER_DEFAULT_PROPS = ("margin-top", "text-indent")
_MOBI_ALIGN_TAGS = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dd", "dt", "td", "th")
MOBI_CSS = "\n".join([
    *(f'{",".join(f"{t}[align={a!r} i]" for t in _MOBI_ALIGN_TAGS)} {{ text-align: {a} }}'
      for a in ("left", "right", "center", "justify")),
    *(f'font[size="{n}"] {{ font-size: {k} }}' for n, k in enumerate(
        ("x-small", "small", "medium", "large", "x-large", "xx-large", "xxx-large"), 1)),
])
# elements whose width/height attributes are box sizes, not MOBI indents/spacing (Calibre skips
# table, tr, td and img)
MOBI_NO_BOX = ["img", "table", "tr", "td", "th", "col", "colgroup", "hr", "iframe", "video", "audio",
               "object", "embed", "canvas", "input", "svg", "image"]
# STYLE_PROPS a MOBI v6 file cannot carry (no CSS; the MobiML markup has nothing for them): left
# out of the MOBI style score, listed in style.props_excluded_for_format. padding-left and
# margin-bottom are not lost but folded (see _mobi_box): padding-left into the left inset that
# margin-left measures, margin-bottom into the next block's space above (margin-top).
MOBI_EXCLUDED_PROPS = ("display", "font-family", "font-variant", "line-height", "white-space",
                       "margin-right", "padding-right", "padding-left", "margin-bottom")
_WEBKIT_ALIGN = {"-webkit-center": "center", "-webkit-left": "left", "-webkit-right": "right",
                 "-moz-center": "center"}

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


def _collect(page, url_xhtml: str, url_html: str, xhtml_first: bool = True, *, hidden: bool = False,
             mobi_out: bool = False, mobi: bool = False) -> dict:
    """Load one document and collect the computed STYLE_PROPS of every element under <body>.
    hidden: leave out the elements the author CSS hides (display:none, visibility:hidden|collapse)
    with their subtrees and return `tags` (every element under body, document order) and `hid` (the
    indexes in `tags` of the topmost hidden ones). mobi_out: apply MOBI_CSS and the width/height
    attributes first (MOBI v6 output). mobi: text-align -webkit-center/left/right read as
    center/left/right (the presentational align attribute's values)."""
    args = {"props": STYLE_PROPS, "anchors": sorted(ANCHOR_TAGS), "hidden": hidden,
            "mobiCss": MOBI_CSS if mobi_out else None, "mobiBaseCss": MOBI_BASE_CSS,
            "mobiNoBox": MOBI_NO_BOX}
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
    rows = data["els"]
    if mobi:
        rows = _mobi_box(rows)
    els = []
    for tag, own, vals, parent, base, full, *raw in rows:
        own_n = _norm_ws(own)
        anchored = bool(own_n) or tag in ANCHOR_TAGS
        full_n = _norm_ws(full) if anchored else ""
        # not rendered: display:none on the element or an ancestor (parents come first)
        hid = vals[_DISPLAY] == "none" or (parent >= 0 and els[parent]["hid"])
        els.append({"tag": tag, "text": own_n, "full": full_n,
                    # alignment key: the full text without any whitespace, so the writer's whitespace
                    # hygiene (newline after <br/>, trimmed runs) does not unmatch an anchor
                    "key": "".join(full_n.split()), "hid": hid,
                    "props": [_norm_prop(p, v, data["bodyFS"]) for p, v in zip(STYLE_PROPS, vals, strict=True)],
                    "base": [_norm_prop(p, v, data["baseFS"]) for p, v in zip(STYLE_PROPS, base, strict=True)],
                    "raw": raw[0] if raw else vals, "parent": parent,
                    "inline": vals[_DISPLAY] in ("inline", "contents"),
                    "anchored": anchored})
    return {"els": els, "parsed_as": data["parsed_as"], "body_fs": data["bodyFS"],
            "tags": data["tags"], "hid": data["hid"], "vt": data["vt"]}


# ── visibility ────────────────────────────────────────────────────────────────
# _COLLECT_JS records, per element with text of its own, whether that text is rendered visibly
# (computed visibility, a box for the text, not clipped to nothing by the screen-reader patterns, not
# positioned >= 500 px off the page; `display:none` on the element or an ancestor leaves no box). The
# style pass compares input and output: text hidden in the input but visible in the output (a regression
# such as a writer pinning `h2 {display: block}` over the UA rule `[hidden] {display: none}`), and the
# reverse. Matching is by text, not by structure: for every text T (non-space characters, at least
# VIS_MIN_CHARS) that an element hides on side A, the number of times it is shown more often on side B
# than on side A -- count(T in B's visible text) - count(T in A's visible text), where the visible text
# is the whitespace-free concatenation of the visible elements' own text -- bounded by the number of
# hidden elements carrying T, is the number of hidden elements that changed. Text that is simply absent
# from the other side (text loss) is not a visibility change, and a text that is visible on both sides
# as often cancels out. Cost bound: at most VIS_MAX_TEXTS distinct hidden texts are looked up per unit
# (a chapter, or the whole book in concat mode).
VIS_MIN_CHARS = 4
VIS_MAX_TEXTS = 2000
VIS_EXAMPLES = 5
VIS_EXAMPLE_CHARS = 80


def _vis_prep(rows) -> tuple[str, dict]:
    """rows: (chapter, own text, visible 0/1) -> (visible text without whitespace, {key: [display
    text, hidden element count, first chapter]} of the hidden texts long enough to be matched)."""
    vis: list[str] = []
    hid: dict[str, list] = {}
    for ch, own, v in rows:
        n = _norm_ws(own)
        if not n:
            continue
        k = "".join(n.split())
        if v:
            vis.append(k)
        elif len(k) >= VIS_MIN_CHARS:
            h = hid.get(k)
            if h is None:
                hid[k] = [n, 1, ch]
            else:
                h[1] += 1
    return "".join(vis), hid


def _vis_flip(hid: dict, vis_a: str, vis_b: str) -> list[tuple]:
    """Texts hidden on side A (hid) that side B shows more often than A does: [(chapter, display,
    elements, chars)], longest texts first, at most VIS_MAX_TEXTS looked up."""
    out = []
    for k, (disp, cnt, ch) in sorted(hid.items(), key=lambda kv: -len(kv[0]))[:VIS_MAX_TEXTS]:
        n = min(cnt, vis_b.count(k) - vis_a.count(k))
        if n > 0:
            out.append((ch, disp, n, n * len(k)))
    return out


class _VisAcc:
    """Visibility changes between input and output, accumulated per unit (chapter, or book)."""

    def __init__(self):
        self.d = {"hidden_in_input_shown_out": [0, 0, []], "shown_in_input_hidden_out": [0, 0, []]}
        self.truncated = False

    def add(self, rows_in, rows_out) -> None:
        """rows_in: (chapter, own, visible) of the input unit, rows_out: (None, own, visible) of the
        output unit. An output element has no chapter: one hidden there takes the chapter of the first
        input element (visible, or hidden) with the same text."""
        vin, hin = _vis_prep(rows_in)
        vout, hout = _vis_prep(rows_out)
        self.truncated |= len(hin) > VIS_MAX_TEXTS or len(hout) > VIS_MAX_TEXTS
        chap = None
        for key, hid, a, b in (("hidden_in_input_shown_out", hin, vin, vout),
                               ("shown_in_input_hidden_out", hout, vout, vin)):
            for ch, disp, n, chars in _vis_flip(hid, a, b):
                if ch is None:
                    if chap is None:
                        chap = {}
                        for c, own, _v in rows_in:
                            chap.setdefault("".join(_norm_ws(own).split()), c)
                    ch = chap.get("".join(disp.split()))
                slot = self.d[key]
                slot[0] += chars
                slot[1] += n
                slot[2].append({"chapter": ch, "text": disp[:VIS_EXAMPLE_CHARS], "chars": chars})

    def result(self) -> dict:
        hi, si = self.d["hidden_in_input_shown_out"], self.d["shown_in_input_hidden_out"]

        def ex(slot):
            return sorted(slot[2], key=lambda e: (-1 if e["chapter"] is None else e["chapter"]))[:VIS_EXAMPLES]
        res = {"hidden_in_input_shown_out_chars": hi[0], "hidden_in_input_shown_out_elements": hi[1],
               "shown_in_input_hidden_out_chars": si[0], "shown_in_input_hidden_out_elements": si[1],
               "examples": {"hidden_in_input_shown_out": ex(hi), "shown_in_input_hidden_out": ex(si)}}
        if self.truncated:
            res["texts_capped"] = True
        return res


_TA, _ML, _PL = STYLE_PROPS.index("text-align"), STYLE_PROPS.index("margin-left"), STYLE_PROPS.index("padding-left")
_MT, _MB = STYLE_PROPS.index("margin-top"), STYLE_PROPS.index("margin-bottom")
_VA, _TD = STYLE_PROPS.index("vertical-align"), STYLE_PROPS.index("text-decoration-line")


def _inset_level(px: float) -> int:
    """MOBI v6 expresses a left inset only as nested <blockquote>s of 2em (32 px) each, at most 3:
    the writer's own rounding (none below 8 px)."""
    return 0 if px < 8 else min(3, max(1, math.floor(px / 32 + 0.5)))


def _mobi_box(rows: list) -> list:
    """MOBI v6 reading of _COLLECT_JS rows [tag, own, vals, parent, base, full] (same on both
    sides), returning [tag, own, vals, parent, base, full, raw]:
    * text-align -webkit-center/left/right (what the align attribute computes to) reads as
      center/left/right;
    * margin-left becomes the left inset level (_inset_level) of margin-left + padding-left, plus
      those of the single-child <blockquote>s directly around the element (the writer's indent
      wrappers; such a wrapper itself counts 0), so a paragraph indented by CSS and one wrapped in a
      <blockquote> compare equal;
    * margin-top of a block becomes the space above it, max(margin-top, margin-bottom of the
      previous block sibling) (non-negative margins collapse; the writer moves the space below a
      block onto the next paragraph's height, so margin-bottom is not scored on its own);
    * <body>/<html> margin-top/margin-left read as one constant: they are the page margins, a
      reader setting in MOBI 6;
    * vertical-align and text-decoration-line read as what the text shows: the first raised/lowered
      value among the element and its inline ancestors, and the union of the decoration lines of
      the element and its ancestors (MobiML expresses them with <sup>/<sub>/<u>/<s> wrappers that
      can sit inside or outside the element that had the CSS).
    `raw` keeps the px behind the level for the examples."""
    n = len(rows)
    kids: list[list[int]] = [[] for _ in range(n)]
    for k, r in enumerate(rows):
        if r[3] >= 0:
            kids[r[3]].append(k)
    pos = {k: i for ks in kids for i, k in enumerate(ks)}
    wrap = [r[0] == "blockquote" and len(kids[k]) == 1 and not r[1].strip() for k, r in enumerate(rows)]

    def px(v: str) -> float:
        m = _PX_RE.fullmatch((v or "").strip())
        return float(m.group(1)) if m else 0.0

    def inline(v) -> bool:
        return v[_DISPLAY] in ("inline", "contents")

    out = [[*r[:6], None] for r in rows]
    for side in (2, 4):
        new = [list(r[side]) for r in rows]
        raw = [list(r[side]) for r in rows] if side == 2 else None
        for k, r in enumerate(rows):
            v, nv = r[side], new[k]
            nv[_TA] = _WEBKIT_ALIGN.get(v[_TA], v[_TA])
            par = r[3]
            if v[_VA] == "baseline" and inline(v) and par >= 0 and inline(rows[par][side]):
                nv[_VA] = new[par][_VA]           # parents come first (document order)
            lines = {t for t in v[_TD].split() if t != "none"}
            if par >= 0:
                lines |= {t for t in new[par][_TD].split() if t != "none"}
            nv[_TD] = " ".join(sorted(lines)) or "none"
            if raw is not None:
                raw[k][_VA], raw[k][_TD] = nv[_VA], nv[_TD]
            if r[0] in ("body", "html"):
                nv[_ML] = nv[_MT] = "page"
                if raw is not None:
                    raw[k][_ML] = raw[k][_MT] = "page"
                continue
            inset, top = 0.0, k
            if not wrap[k]:
                inset = px(v[_ML]) + px(v[_PL])
                while rows[top][3] >= 0 and wrap[rows[top][3]]:
                    top = rows[top][3]
                    inset += px(rows[top][side][_ML]) + px(rows[top][side][_PL])
            nv[_ML] = f"L{_inset_level(inset)}"
            if raw is not None:
                raw[k][_TA] = nv[_TA]
                raw[k][_ML] = f"{inset:g}px (L{_inset_level(inset)})"
            par = rows[top][3]
            if not inline(v) and par >= 0 and pos[top] > 0:
                prev = rows[kids[par][pos[top] - 1]][side]
                mt, mb = px(v[_MT]), px(prev[_MB])
                if not inline(prev) and mt >= 0 and mb > mt:
                    nv[_MT] = f"{mb:g}px"
                    if raw is not None:
                        raw[k][_MT] = f"{mb:g}px (collapsed)"
        for k in range(n):
            out[k][side] = new[k]
            if raw is not None:
                out[k][6] = raw[k]
    return out


def _authored(e: dict, idx=_ALL_IDX) -> int:
    """Number of properties whose value the input's author CSS changed (vs. the UA baseline)."""
    return sum(1 for pi in idx if not _prop_equal(STYLE_PROPS[pi], e["props"][pi], e["base"][pi]))


# margin/padding of <html>/<body>: the page margins, which a Kindle owns (left out of the device score)
_PAGE_BOX_IDX = frozenset(STYLE_PROPS.index(p) for p in ("margin-top", "margin-bottom", "margin-left",
                                                          "margin-right", "padding-left", "padding-right"))


class _StyleAcc:
    def __init__(self, excluded=(), box_only_ancestors: bool = False, reader_default=(),
                 page_box_free: bool = False):
        # property indexes scored (all), compared across element kinds (inherited), and compared on
        # the ancestors of an anchor pair (all; MOBI v6: the non-inherited box properties only, as
        # MobiML puts the inherited formatting on the text itself, where the anchor pair checks it)
        self.all_idx = tuple(k for k in _ALL_IDX if STYLE_PROPS[k] not in excluded)
        self.inh_idx = tuple(k for k in _INH_IDX if STYLE_PROPS[k] not in excluded)
        self.anc_idx = tuple(k for k in self.all_idx if not box_only_ancestors or k not in _INH_IDX)
        # properties left at the reader's default on both sides count as agreeing (MOBI v6: the
        # output's baseline is the MOBI reader's defaults, which differ from a browser's)
        self.reader_default = {STYLE_PROPS.index(x) for x in reader_default}
        # device score: html/body box properties are not compared (the device owns the page margins)
        self.page_box_free = page_box_free
        self.hist: dict[str, int] = {}
        self.examples: dict[str, list] = {}
        self.seen: set = set()
        self.all_scores: dict = {}

    def _pair(self, a: dict, b: dict, idx, key, anchor_text: str) -> tuple[int, int, int, int]:
        """(checked, equal, all_checked, all_equal) over the property indexes idx for one pair.
        `checked` counts a property only when the input's author CSS sets it (differs from the UA
        baseline) or the two sides disagree, so shared browser defaults do not inflate the score;
        a `reader_default` property the input leaves at the browser's default and the output at its
        own baseline (the MOBI reader's default) is not checked either."""
        checked = equal = all_checked = all_equal = 0
        if a["hid"] and b["hid"]:    # not rendered on either side: its computed style is noise
            return 0, 0, 0, 0
        page = self.page_box_free and (a["tag"] in ("html", "body") or b["tag"] in ("html", "body"))
        for pi in idx:
            if page and pi in _PAGE_BOX_IDX:
                continue
            prop = STYLE_PROPS[pi]
            same = _prop_equal(prop, a["props"][pi], b["props"][pi])
            all_checked += 1
            all_equal += same
            authored = not _prop_equal(prop, a["props"][pi], a["base"][pi])
            if not authored and (same or (pi in self.reader_default
                                          and _prop_equal(prop, b["props"][pi], b["base"][pi]))):
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
        tot = list(self._pair(a, b, self.all_idx if full_props else self.inh_idx, (scope, i, j), anchor_text))
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
            for n, v in enumerate(self._pair(a, b, self.anc_idx, (scope, i, j), anchor_text)):
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
    return e["key"]


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
                c, e = (0 if ein[i]["hid"] else _authored(ein[i], acc.all_idx)), 0
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
    needle = a["key"]
    for y in cand:
        if 0 <= y < len(ao) and needle in eout[ao[y]]["key"]:
            return ao[y]
    return None


def _device_response(url, resource_type: str, root: Path, state: dict):
    """(body, content type) the device context serves for one request instead of the file server,
    or None to let the request through. A document URL with `device=1` gets device.device_document
    (Kindle UA sheet first, inline <style> rewritten); every style sheet (a .css file, or any
    request Chromium makes for a stylesheet) gets device.device_css, memoised per file. A document
    URL with `devin=1` (served in any context with a state, rewrite or not) gets
    device.input_reference_document: the input with html/body side margins/paddings zeroed."""
    q = parse_qs(url.query)
    if not ("devin" in q or state.get("rewrite", True)):
        return None
    f = (root / unquote(url.path).lstrip("/")).resolve()
    if not f.is_relative_to(root) or not f.is_file():
        return None
    mode = q.get("as", [None])[0]
    ctype = ("application/xhtml+xml" if mode == "xhtml" or (mode is None and f.suffix.lower() in (".xhtml", ".xht"))
             else "text/html; charset=utf-8")
    if "devin" in q:      # the device score's input reference (author CSS untouched)
        return device.input_reference_document(f.read_bytes(), state["stats"]), ctype
    if not state.get("rewrite", True):
        return None
    if "device" in q:
        return device.device_document(f.read_bytes(), state["stats"]), ctype
    if resource_type == "stylesheet" or f.suffix.lower() == ".css":
        s = f.stat()
        key = (str(f), s.st_mtime_ns, s.st_size)
        if key not in state["css"]:
            state["css"][key] = device.device_css(f.read_bytes().decode("utf-8", "replace"),
                                                  state["stats"]).encode("utf-8")
        return state["css"][key], "text/css; charset=utf-8"
    return None


def _style_page(page, base_url: str, device_state: dict | None = None, root: Path | None = None):
    """(context, page) of a dedicated Chromium context: JavaScript disabled, 600 x 800 screen, every
    request that does not go to base_url's host aborted. With `device_state` ({"stats": Counter,
    "css": {}, "errors": []}) and the server's `root`, the context reads documents and style sheets
    through the device model (_device_response)."""
    browser = page.context.browser
    if browser is None:  # persistent context: no browser handle to open a dedicated context
        raise RuntimeError("style score needs a page from browser.new_context()/new_page(), "
                           "not a persistent context")
    ctx = browser.new_context(viewport=STYLE_VIEWPORT, device_scale_factor=1, java_script_enabled=False,
                              service_workers="block")
    host = urlparse(base_url).netloc
    root = Path(root).resolve() if root is not None else None

    def route(r):
        try:
            u = urlparse(r.request.url)
            if u.netloc != host:
                r.abort()
                return
            if device_state is not None and root is not None:
                try:
                    resp = _device_response(u, r.request.resource_type, root, device_state)
                except Exception as e:
                    device_state["errors"].append(_err(e))
                    resp = None
                if resp is not None:
                    r.fulfill(status=200, body=resp[0],
                              headers={"Content-Type": resp[1], "Cache-Control": "no-store"})
                    return
            r.continue_()
        except Exception:
            pass
    ctx.route("**/*", route)
    pg = ctx.new_page()
    pg.emulate_media(media="screen")
    return ctx, pg


def _input_urls(book: InputBook, i: int, base_url: str, out_dir: Path) -> tuple[str, str]:
    p = book.dir / book.spine[i]["path"]
    return _url_for(base_url, out_dir, p, "xhtml"), _url_for(base_url, out_dir, p, "html")


def hidden_pass(book: InputBook, page, base_url: str, out_dir: Path) -> None:
    """MOBI v6 without the style pass: load every XHTML spine item not pruned yet in the style
    context only to find (and prune) the elements its author CSS hides."""
    if all(s["path"] in book.hidden for s in book.spine if s["xhtml"]):
        return
    ctx, pg = _style_page(page, base_url)
    try:
        for i, s in enumerate(book.spine):
            if s["xhtml"] and s["path"] not in book.hidden:
                d = _collect(pg, *_input_urls(book, i, base_url, out_dir), hidden=True, mobi=True)
                book.prune_hidden(s["path"], d["tags"], d["hid"])
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def inv_style(book: InputBook, outb: OutputBook, mode: str, pairs, page, base_url: str, out_dir: Path) -> dict:
    """Computed-style comparison of input and output (see _align_score). score = equal / checked
    properties over the whole book (1.0 when nothing is authored or disputed); per_chapter the same
    per spine item (None when it has no checked property).

    AZW3 score is page-neutral: the output (as authored, no device model) is aligned against the
    device pass's input reference (html/body side margins/paddings zeroed, see below) and html/body
    box properties (margins, side paddings) are not compared, as the writer leaves the page margins to
    the Kindle; `page_neutral` is False when the reference was unavailable (device pass failed) and the
    plain input was used. score_page_dependent is the old number (plain input, page margins counted).
    MOBI v6 is unchanged (score == score_page_dependent).

    MOBI v6 (no CSS in the file): the output is read with MOBI_CSS and its width/height attributes
    applied, MOBI_EXCLUDED_PROPS are not scored, and the input elements the author CSS hides are
    left out (the writer removes them); the same load prunes them from book's documents for the
    text/links/images invariants (InputBook.prune_hidden).

    AZW3 only, the device score (device_*): every output document is loaded a second time, in a
    context that serves it through the Kindle device model (device.py: KINDLE_UA_CSS as the first
    sheet, @media/@supports/@namespace/@layer and the selectors a Kindle is assumed not to match
    removed), and aligned and scored against a second load of each input chapter with its html/body
    side margins and paddings forced to 0 (device.INPUT_PAGE_CSS, after the author sheets: the
    device owns the page margins, so percentages resolve against the same content box on both
    sides), html/body margins and paddings left out. A failure of that pass leaves device_score None (device_error says why)."""
    mobi = outb.kind == "mobi7"
    dev = {"on": not mobi, "error": None, "stats": Counter(), "css": {}, "errors": []}
    srv_root = _SERVERS.get(base_url, out_dir.resolve().parent)
    # the plain context serves files as they are, except the device pass's input reference (devin=1)
    ctx, pg = _style_page(page, base_url, {**dev, "rewrite": False}, srv_root)
    # AZW3: page-neutral (html/body box properties skipped, input = the device pass's zeroed-margin
    # reference); `accp` is the old page-dependent comparison over the plain input, kept for
    # score_page_dependent. MOBI v6 has no page-margin zeroing: its score is unchanged.
    acc = _StyleAcc(MOBI_EXCLUDED_PROPS if mobi else (), box_only_ancestors=mobi,
                    reader_default=MOBI_READER_DEFAULT_PROPS if mobi else (), page_box_free=not mobi)
    accp = _StyleAcc()
    pchk = peq = 0
    neutral_basis = {"zeroed": 0, "plain": 0}   # chapters whose reference was the zeroed input / the plain one
    n = len(book.spine)
    chk, eq = [0] * n, [0] * n
    dacc = _StyleAcc(page_box_free=True)
    dchk, deq = [0] * n, [0] * n
    vis, dvis = _VisAcc(), _VisAcc()
    dctx = dpg = None
    if dev["on"]:
        try:
            dctx, dpg = _style_page(page, base_url, dev, srv_root)
        except Exception as e:
            dev.update(on=False, error=_err(e))
    tot_in = tot_out = authored_els = 0
    stats_all: dict[str, int] = {}
    parsed = {"input_html_fallback": 0, "output_html_fallback": 0}
    out_xhtml_first = outb.kind == "kf8"
    vt: dict[str, list] = {}      # visibility rows of the last load_in / load_out / load_dev
    vis_err: list[str] = []

    def add_stats(st):
        for k, v in st.items():
            stats_all[k] = stats_all.get(k, 0) + v
    try:
        def load_in(i):
            vt["in"] = []
            if not book.spine[i]["xhtml"]:
                return []   # foreign spine item (svg, image, xml, ...): not evaluated, see text.non_xhtml_handling
            d = _collect(pg, *_input_urls(book, i, base_url, out_dir), hidden=mobi, mobi=mobi)
            parsed["input_html_fallback"] += d["parsed_as"] == "html"
            if mobi and book.spine[i]["path"] not in book.hidden:
                book.prune_hidden(book.spine[i]["path"], d["tags"], d["hid"])
            vt["in"] = [(i, o, v) for o, v in d["vt"]]
            return d["els"]

        def load_out(p):
            d = _collect(pg, _url_for(base_url, out_dir, p, "xhtml"), _url_for(base_url, out_dir, p, "html"),
                         xhtml_first=out_xhtml_first, mobi_out=mobi, mobi=mobi)
            parsed["output_html_fallback"] += d["parsed_as"] == "html" and out_xhtml_first
            vt["out"] = [(None, o, v) for o, v in d["vt"]]
            return d["els"]

        def load_in_dev(i):
            """Input chapter i as the device pass's reference (page side margins zeroed); None once
            the device pass has failed."""
            if not book.spine[i]["xhtml"]:
                return []
            if not dev["on"]:
                return None
            try:
                ux, uh = _input_urls(book, i, base_url, out_dir)
                return _collect(pg, ux + "&devin=1", uh + "&devin=1")["els"]
            except Exception as e:
                dev.update(on=False, error=_err(e))
                return None

        def load_dev(p):
            """Output document p under the device model; None once the device pass has failed."""
            if not dev["on"]:
                return None
            try:
                d = _collect(dpg, _url_for(base_url, out_dir, p, "xhtml") + "&device=1",
                             _url_for(base_url, out_dir, p, "html") + "&device=1")
                vt["dev"] = [(None, o, v) for o, v in d["vt"]]
                return d["els"]
            except Exception as e:
                dev.update(on=False, error=_err(e))
                return None

        def vis_add(acc, rows_in, rows_out):
            try:
                acc.add(rows_in, rows_out)
            except Exception as e:   # pure python on collected rows: must not sink the style score
                vis_err.append(_err(e))

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
                vin = vt["in"]
                vt["out"] = []
                eout = load_out(p) if p is not None else []
                vis_add(vis, vin, vt["out"])
                eind = load_in_dev(i) if dev["on"] else None
                # AZW3: the primary score reads the page-neutral input reference (the device pass's
                # zeroed-margin load); the plain load only feeds score_page_dependent
                if eind is None:
                    neutral_basis["plain"] += 1
                else:
                    neutral_basis["zeroed"] += 1
                contrib, ni, no, st = _align_score(ein if eind is None else eind, eout, acc, i)
                tot_in += ni
                tot_out += no
                authored_els += sum(1 for e in ein if e["anchored"] and _authored(e, acc.all_idx))
                add_stats(st)
                for c, e in contrib.values():
                    chk[i] += c
                    eq[i] += e
                if not mobi:
                    for c, e in _align_score(ein, eout, accp, i)[0].values():
                        pchk += c
                        peq += e
                if dev["on"]:
                    vt["dev"] = []
                    edev = (load_dev(p) if p is not None else []) if eind is not None else None
                    if edev is not None:
                        vis_add(dvis, vin, vt["dev"])
                        for c, e in _align_score(eind, edev, dacc, i)[0].values():
                            dchk[i] += c
                            deq[i] += e
        else:
            ein, owner = [], []
            vin = []
            for i in range(n):
                els = shifted(load_in(i), len(ein))
                vin += vt["in"]
                ein += els
                owner += [i] * len(els)
            eout = []
            vout = []
            for p in outb.docs:
                eout += shifted(load_out(p), len(eout))
                vout += vt["out"]
            vis_add(vis, vin, vout)
            eind, downer = [], []
            for i in range(n):
                d = load_in_dev(i) if dev["on"] else None
                if d is None:
                    break
                eind += shifted(d, len(eind))
                downer += [i] * len(d)
            neutral = dev["on"]
            neutral_basis["zeroed" if neutral else "plain"] += n
            contrib, tot_in, tot_out, st = _align_score(eind if neutral else ein, eout, acc, "book")
            authored_els = sum(1 for e in ein if e["anchored"] and _authored(e, acc.all_idx))
            add_stats(st)
            for k, (c, e) in contrib.items():
                chk[(downer if neutral else owner)[k]] += c
                eq[(downer if neutral else owner)[k]] += e
            if not mobi:
                for c, e in _align_score(ein, eout, accp, "book")[0].values():
                    pchk += c
                    peq += e
            if dev["on"]:
                edev = []
                vdev = []
                for p in outb.docs:
                    d = load_dev(p)
                    if d is None:
                        break
                    edev += shifted(d, len(edev))
                    vdev += vt["dev"]
                if dev["on"]:
                    vis_add(dvis, vin, vdev)
                    for k, (c, e) in _align_score(eind, edev, dacc, "book")[0].items():
                        dchk[downer[k]] += c
                        deq[downer[k]] += e
    finally:
        for c in (ctx, dctx):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
    hist = dict(sorted(acc.hist.items(), key=lambda kv: -kv[1]))
    denom = max(tot_in, tot_out)
    checked, equal = sum(chk), sum(eq)
    if mobi:
        device_res: dict = {"device_score": None, "device_visibility": None}
    elif not dev["on"]:
        device_res = {"device_score": None, "device_visibility": None,
                      "device_error": dev["error"] or "device pass failed"}
    else:
        dh = dict(sorted(dacc.hist.items(), key=lambda kv: -kv[1]))
        dc, de = sum(dchk), sum(deq)
        device_res = {
            "device_score": round(de / dc, 4) if dc else 1.0,
            "device_per_chapter": [round(deq[i] / dchk[i], 4) if dchk[i] else None for i in range(n)],
            "device_checked_props": dc, "device_equal_props": de,
            "device_prop_disagreements": dh,
            "device_prop_examples": {k: dacc.examples[k][:2] for k in list(dh)[:8]},
            "device_visibility": dvis.result(),
            "device_model": device.DEVICE_MODEL,
            "device_css_removed": dict(sorted(dev["stats"].items())),
        }
        if dev["errors"]:
            device_res["device_route_errors"] = dev["errors"][:3]
    if mobi:
        pchk, peq = checked, equal
    return {"score": round(equal / checked, 4) if checked else 1.0,
            # the old comparison (html/body page margins counted, plain input): AZW3 only differs from score
            "score_page_dependent": round(peq / pchk, 4) if pchk else 1.0,
            "page_neutral": (not mobi) and not neutral_basis["plain"],
            "per_chapter": [round(eq[i] / chk[i], 4) if chk[i] else None for i in range(n)],
            "mode": mode, "elements_in": tot_in, "elements_out": tot_out,
            "elements_with_authored_css": authored_els,
            "checked_props": checked, "equal_props": equal,
            **stats_all,
            # naive variant: fraction of all STYLE_PROPS equal over exactly matched anchors, defaults
            # included, unmatched anchors on either side counting 0 (for reference only)
            "score_all_props": round(sum(acc.all_scores.values()) / denom, 4) if denom else None,
            "input_css_rules": book.css_rules(),
            "input_css_rules_unreferenced": book.css_info()["unreferenced"],
            "output_css_rules": outb.css_rules(),
            "prop_disagreements": hist, "prop_examples": {k: acc.examples[k] for k in hist},
            "props_excluded_for_format": list(MOBI_EXCLUDED_PROPS) if mobi else [],
            "visibility": vis.result() if not vis_err else None,
            **({"visibility_error": vis_err[0]} if vis_err else {}),
            **parsed, **device_res}


# ── layout hygiene ──────────────────────────────────────────────────────────

def _doc_css_texts(root, resolve) -> list[str]:
    """Texts of the style sheets one document uses: <link rel=stylesheet> (resolve(href) -> Path or
    None), their @import targets (one level) and <style> blocks."""
    texts: list[str] = []

    def read(href: str, base=None):
        href = (href or "").strip().split("#")[0].split("?")[0]
        if not href or _has_scheme(href):
            return None
        f = resolve(href, base)
        if f is None or not f.is_file():
            return None
        return f, f.read_bytes().decode("utf-8", "replace")
    for el in _elements(root, {"link", "style"}):
        if _local(el) == "style":
            texts.append("".join(el.itertext()))
            continue
        if "stylesheet" not in (_attr(el, "rel") or "").lower().split():
            continue
        got = read(_attr(el, "href") or "")
        if got:
            texts.append(got[1])
            for imp in _css_imports(got[1]):
                sub = read(imp, got[0])
                if sub:
                    texts.append(sub[1])
    return texts


def inv_layout_hygiene(book: InputBook, outb: OutputBook) -> tuple[dict, dict]:
    """(layout_hygiene, layout_hygiene_input): device.layout_hygiene_doc counts over the output
    documents (KindleUnpack parts / mobi7 book.html) and over the input XHTML spine documents, with
    `pre` elements and empty marker/spacer blocks recognised by tag, style attribute and tag/class
    rules of the document's sheets (device.pre_selectors, device.marker_selectors). Static (lxml), no browser."""
    memo: dict = {}

    def sel_of(texts: list[str]):
        key = tuple(texts)
        if key not in memo:
            memo[key] = (device.pre_selectors(texts), device.marker_selectors(texts))
        return memo[key]

    keys = device.HYGIENE_KEYS + device.HYGIENE_EXTRA_KEYS

    def run(docs) -> dict:
        counts, ex, n = Counter(), {}, 0
        for root, resolve, name in docs:
            pre, markers = sel_of(_doc_css_texts(root, resolve))
            device.layout_hygiene_doc(_find_body(root), pre, counts, ex, name, markers=markers)
            n += 1
        return {**{k: counts[k] for k in keys}, "documents": n,
                "examples": {k: ex[k] for k in keys if k in ex}}

    def out_docs():
        for p in outb.docs:
            yield outb.doc(p), (lambda h, base, p=p: (base or p).parent / unquote(h)), p.name

    def in_docs():
        for sp in book.spine:
            if not sp["xhtml"]:
                continue

            def resolve(h, base, path=sp["path"]):
                if base is not None:
                    return base.parent / unquote(h)
                return book.dir / book.join(path, h)
            yield book.doc(sp["path"]), resolve, sp["path"]
    return run(out_docs()), run(in_docs())


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
        return {**res, "fixed_layout": None, "layout_hygiene": None, "layout_hygiene_input": None,
                "errors": {n: f"setup: {_err(e)}" for n in names}}
    res["fixed_layout"] = book.fixed_layout
    # static, before anything prunes the input documents (MOBI v6 hidden content)
    try:
        res["layout_hygiene"], res["layout_hygiene_input"] = inv_layout_hygiene(book, outb)
    except Exception as e:
        res["layout_hygiene"] = res["layout_hygiene_input"] = None
        errors["layout_hygiene"] = _err(e)
    mobi = outb.kind == "mobi7"
    base = base_url or _server_for(out_dir.parent)
    jobs = {
        "text": lambda: inv_text(book, outb, mode, pairs),
        "images": lambda: inv_images(book, outb, mode, pairs, out_dir / f"{who}.{fmt}"),
        "toc": lambda: inv_toc(book, outb),
        "links": lambda: inv_links(book, outb, mode, pairs),
        "style": lambda: (None if skip_style else
                          inv_style(book, outb, mode, pairs, page, base, out_dir)),
    }
    order = list(jobs)
    if mobi:
        # MOBI v6 drops what the author CSS hides: the style pass (which loads every input chapter
        # in Chromium anyway) prunes those elements from the input documents first; without it a
        # hidden-only pass does. text/links/images then compare against the pruned input.
        order = ["style"] + [n for n in order if n != "style"]
    hidden_err = None
    for n in order:
        if mobi and n == "text" and page is not None:
            try:
                hidden_pass(book, page, base, out_dir)     # chapters the style pass did not prune
            except Exception as e:
                hidden_err = _err(e)
        try:
            res[n] = jobs[n]()
        except Exception as e:
            res[n] = None
            errors[n] = _err(e)
    if mobi:
        tot = {k: sum(h[k] for h in book.hidden.values()) for k in ("elements", "chars", "anchors", "unmapped")}
        info = {"method": "chromium" if page is not None and hidden_err is None else None,
                "items": sum(1 for h in book.hidden.values() if h["elements"]), **tot}
        if hidden_err:
            errors["hidden"] = hidden_err
        if res["text"] is not None:
            res["text"]["hidden_excluded"] = info
        if res["links"] is not None:
            res["links"]["hidden_anchors_excluded"] = tot["anchors"]
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
        fmts = [f.strip() for f in a.fmt.split(",") if f.strip()]
        if not a.gate_only and (not a.no_style or "mobi" in fmts):   # mobi: hidden_pass needs it
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch()
            page = browser.new_page()
        base_url = start_out_server(out_dir.parent)
        for fmt in fmts:
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
