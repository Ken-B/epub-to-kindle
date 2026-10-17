"""calibre_diff: structural/textual diff of our AZW3/MOBI output against Calibre's.

    from calibre_diff import diff
    diff(entry, out_dir, "azw3")   # -> dict (see tests/harness/schema.md) or None

Inputs (inside the per-book working dir `out_dir`):
    ours.<fmt>, calibre.<fmt>
    unpack/<fmt>/{ours,calibre}/kindleunpack/        KindleUnpack trees (oracles.gate / cli.py)
Outputs:
    inspect/<fmt>/{ours,calibre}.txt                 text dump (header + index summaries)

`calibre-debug --inspect-mobi FILE` takes no output dir: it writes `decompiled_<basename>` into the
CURRENT WORKING DIRECTORY (deleting an existing one), which makes `ours.azw3`/`calibre.azw3` collide
on `decompiled_ours`/`decompiled_calibre` when run side by side. We therefore call
`calibre.ebooks.mobi.debug.main.inspect_mobi(file, outdir)` ourselves through a tiny helper script
(`calibre-debug -e helper.py -- FILE OUTDIR`) and always run with cwd = the work dir.

Calibre's inspector raises "KF8 Header contains invalid FDST count" when the header's FDST count
does not equal the number of sections in the FDST record. The helper retries with that single check
disabled so that the rest of the dump (header, skel/chunk/NCX indices) is still produced; the
original error is reported as `inspect_error_<who>` together with the two numbers.

Never raises: every sub-computation is guarded and yields None on failure.
Run as a script for a quick look:
    uv run --python 3.13 --with lxml python tests/harness/calibre_diff.py <out_dir> <fmt>
"""
# Broad `except Exception` (and silent cleanup) is deliberate: the harness contract is that one bad
# book or one flaky tool never aborts a corpus run; failures are recorded in the result instead.
# ruff: noqa: BLE001, S110
from __future__ import annotations

import difflib
import html
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_WORDS = 200_000
INSPECT_TIMEOUT_S = 240

# ── calibre-debug inspect ───────────────────────────────────────────────────

_HELPER = r'''
import sys, os, json, traceback
import calibre.ebooks.mobi.debug.mobi8 as m8
from calibre.ebooks.mobi.debug.main import inspect_mobi

src, out = sys.argv[-2], sys.argv[-1]
info = {"error": None, "retried": False, "fdst_sections": None, "fdst_header_count": None}
try:
    inspect_mobi(src, out)
except Exception as e:                      # noqa
    info["error"] = "%s: %s" % (type(e).__name__, e)
    def read_fdst(self):
        self.fdst = None
        if self.header.fdst_idx != m8.NULL_INDEX:
            self.fdst = m8.FDST(self.mf.records[self.header.fdst_idx].raw)
            info["fdst_sections"] = self.fdst.num_sections
            info["fdst_header_count"] = self.header.fdst_count
    m8.MOBIFile.read_fdst = read_fdst
    try:
        inspect_mobi(src, out)
        info["retried"] = True
    except Exception as e2:                 # noqa
        info["error"] = info["error"] + " | retry: %s: %s" % (type(e2).__name__, e2)
with open(os.path.join(os.path.dirname(os.path.abspath(out)), os.path.basename(out) + ".status.json"), "w") as f:
    json.dump(info, f)
'''

_BULKY = ("text_records", "images", "fonts", "binary", "hd-images", "files", "flows",
          "text", "font")
_ENTRY_RE = re.compile(r"Total number of actual Index Entries in all records:\s*(\d+)")


def _run_inspect(src: Path, dest_txt: Path) -> dict:
    """Run inspect-mobi, store the text dump in dest_txt.

    Returns {'header_text', 'skel', 'chunks', 'ncx', 'error'}: the header dump and the number of
    entries in the SKEL/chunk/NCX indices (None when absent)."""
    res = {"header_text": None, "skel": None, "chunks": None, "ncx": None, "error": None}
    dest_txt.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".work_{dest_txt.stem}_", dir=dest_txt.parent))
    outdir = work / "o"
    try:
        helper = work / "helper.py"
        helper.write_text(_HELPER, encoding="utf-8")
        try:
            p = subprocess.run(["calibre-debug", "-e", str(helper), "--", str(src.resolve()), str(outdir)],
                               check=False, cwd=work, capture_output=True, timeout=INSPECT_TIMEOUT_S)
            rc, log = p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
        except FileNotFoundError:
            res["error"] = "calibre-debug not found"
            dest_txt.write_text("calibre-debug not found\n", encoding="utf-8")
            return res
        except subprocess.TimeoutExpired:
            res["error"] = f"calibre-debug timed out after {INSPECT_TIMEOUT_S}s"
            dest_txt.write_text(res["error"] + "\n", encoding="utf-8")
            return res

        status = {}
        sp = work / "o.status.json"
        if sp.exists():
            try:
                status = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                pass
        err = status.get("error")
        if err and status.get("retried"):
            err += (f" (FDST record has {status.get('fdst_sections')} sections, "
                    f"header says {status.get('fdst_header_count')}; dump produced with check disabled)")
        if not sp.exists() and rc != 0:
            err = f"calibre-debug exit {rc}: {log.strip()[-300:]}"
        res["error"] = err

        parts = []
        hp = outdir / "header.txt"
        if hp.exists():
            res["header_text"] = hp.read_text("utf-8", "replace")
            parts.append(res["header_text"])
        else:
            parts.append(f"(no header.txt produced)\n{log[-1500:]}")
        for key, fname in (("skel", "skel.record"), ("chunks", "chunks.record"), ("ncx", "ncx.record")):
            fp = outdir / fname
            if fp.exists():
                t = fp.read_text("utf-8", "replace")
                m = _ENTRY_RE.search(t)
                res[key] = int(m.group(1)) if m else None
                parts.append(f"\n******************** {fname} ********************\n{t}")
        idx = outdir / "index.txt"                       # MOBI v6
        if idx.exists():
            parts.append(f"\n******************** index.txt ********************\n{idx.read_text('utf-8', 'replace')}")
        if err:
            parts.insert(0, f"!!! inspect-mobi error: {err}\n")
        dest_txt.write_text("".join(parts), encoding="utf-8")
    except Exception as e:
        res["error"] = res["error"] or f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return res


# ── header parsing ──────────────────────────────────────────────────────────

_SECTION_RE = re.compile(r"^\*{10,}\s*(.*?)\s*\*{10,}\s*$")
_EXTH_RE = re.compile(r"^(.*?)\s*\((\d+)\):\s?(.*)$")

# Exact MOBI 6/8 header field names (as printed by calibre's inspect-mobi) that are NOT compared:
# record indices/offsets, content-dependent sizes and counts, uids, unused/unknown/reserved bytes.
_IGNORE_FIELDS = frozenset({
    # record indices / offsets
    "First non-book record", "First content record", "Last content record", "First Image index",
    "Full name offset", "Meta Orth Index", "Meta Infl Index", "Secondary index record",
    "FDST Index", "FCIS number", "FLIS number", "SRCS record index", "NCX index", "Sections Index",
    "SKEL Index", "DATP Index", "Other Index", "DRM Offset",
    "Huffman record offset", "Huffman table offset",
    # sizes / counts that depend on the content
    "Text length", "Number of text records", "Full name length", "Huffman record count",
    "Huffman table length",
    # per-file ids and opaque bytes
    "UID", "Unused", "Reserved", "Unknown", "Unknown3", "Unknown4", "Unknown6", "Unknown7", "Unknown9",
})
# Fields that are always compared even if a future edit of the ignore list matched them: the
# writer invariants (a difference is a real writer bug).
_ALWAYS_KEEP = frozenset({"FDST Count", "Text record size", "Compression", "Extra data flags",
                          "Encoding", "File version"})
# EXTH record codes that are not compared: values that legitimately differ (106 published date,
# 108 contributor, 112 source, 113 ASIN, 503 updated title), creator-software stamps (204-207, 535),
# resource counts (125, 131), and every offset/index-valued record (116 StartOffset, 121 KF8
# boundary offset, 129 KF8 cover URI = resource index, 201 CoverOffset, 202 ThumbOffset).
_IGNORE_EXTH = frozenset({106, 108, 112, 113, 503, 204, 205, 206, 207, 535, 125, 131,
                          116, 121, 129, 201, 202})


def _parse_header(text: str) -> dict[str, str]:
    """MOBI 6/8 Header + EXTH Header sections -> {field: value}."""
    fields: dict[str, str] = {}
    sect = None
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            sect = m.group(1)
            continue
        if sect is None or line.startswith("\t") or not line.strip():
            continue
        if sect.startswith("MOBI"):
            if ": " in line:
                k, v = line.split(": ", 1)
                fields[k.strip()] = v.strip()
        elif sect.startswith("EXTH"):
            mm = _EXTH_RE.match(line)
            if mm:
                name, code, val = mm.group(1), int(mm.group(2)), mm.group(3)
                fields[f"EXTH {name} ({code})"] = val.strip()
    return fields


_EXTH_FIELD_RE = re.compile(r"^EXTH .*\((\d+)\)$")


def _ignored(field: str) -> bool:
    """Exact-name ignore logic for both the MOBI header fields and the EXTH records."""
    if field in _ALWAYS_KEEP:
        return False
    m = _EXTH_FIELD_RE.match(field)
    if m:
        return int(m.group(1)) in _IGNORE_EXTH
    return field in _IGNORE_FIELDS


def _short(v):
    if v is None:
        return None
    return v if len(v) <= 100 else v[:97] + "..."


def _header_diff(ours: str | None, cal: str | None):
    if ours is None or cal is None:
        return None
    fo, fc = _parse_header(ours), _parse_header(cal)
    out = []
    for k in list(fo) + [k for k in fc if k not in fo]:
        if _ignored(k):
            continue
        a, b = fo.get(k), fc.get(k)
        if a != b:
            out.append({"field": k, "ours": _short(a), "calibre": _short(b)})
    return out


# ── KindleUnpack tree metrics ───────────────────────────────────────────────

def _tree_root(tree: Path):
    """Return ('kf8', OEBPS dir) or ('mobi7', mobi7 dir) or (None, None)."""
    k8 = tree / "mobi8" / "OEBPS"
    if k8.is_dir():
        return "kf8", k8
    m7 = tree / "mobi7"
    if m7.is_dir():
        return "mobi7", m7
    return None, None


def _read(p: Path) -> str:
    return p.read_text("utf-8", errors="replace")


def _count_chapters(tree: Path):
    kind, root = _tree_root(tree)
    if kind == "kf8":
        text_dir = root / "Text"
        if text_dir.is_dir():
            return sum(1 for p in text_dir.iterdir() if p.suffix.lower() in (".xhtml", ".html", ".htm"))
        return sum(1 for p in root.rglob("*") if p.suffix.lower() in (".xhtml", ".html", ".htm"))
    if kind == "mobi7":
        book = root / "book.html"
        if not book.exists():
            return None
        t = _read(book)
        if not t.strip():
            return 0
        return len(re.findall(r"<mbp:pagebreak\b", t)) + 1
    return None


def _ncx_depth(tree: Path):
    from lxml import etree
    _, root = _tree_root(tree)
    if root is None:
        return None
    ncx = root / "toc.ncx"
    if not ncx.exists():
        return None
    parser = etree.XMLParser(recover=True, resolve_entities=False, huge_tree=True)
    doc = etree.fromstring(ncx.read_bytes(), parser)
    if doc is None:
        return None
    best = 0

    def walk(el, d):
        nonlocal best
        for ch in el:
            if isinstance(ch.tag, str) and etree.QName(ch).localname == "navPoint":
                best = max(best, d + 1)
                walk(ch, d + 1)
            elif isinstance(ch.tag, str):
                walk(ch, d)
    walk(doc, 0)
    return best


_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)


def _css_rules(tree: Path):
    _, root = _tree_root(tree)
    if root is None:
        return None
    n = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf == ".css":
            n += _COMMENT_RE.sub("", _read(p)).count("{")
        elif suf in (".xhtml", ".html", ".htm"):
            for m in _STYLE_RE.finditer(_read(p)):
                n += _COMMENT_RE.sub("", m.group(1)).count("{")
    return n


# ── full text extraction (own copy of the PalmDoc/MOBI reader) ──────────────

def palmdoc_decompress(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        i += 1
        if b == 0 or 9 <= b <= 0x7F:
            out.append(b)
        elif b <= 8:
            out += data[i:i + b]
            i += b
        elif b <= 0xBF:
            if i >= n:
                break
            b2 = data[i]
            i += 1
            dist = ((b & 0x3F) << 5) | (b2 >> 3)
            ln = (b2 & 7) + 3
            if dist == 0 or dist > len(out):
                out += b"\x00" * ln
            elif dist >= ln:
                s = len(out) - dist
                out += out[s:s + ln]
            else:
                for _ in range(ln):
                    out.append(out[-dist])
        else:
            out.append(0x20)
            out.append(b ^ 0x80)
    return bytes(out)


def _trailing_entry_size(rec: bytes) -> int:
    """Size of the trailing entry at the end of rec (Calibre's sizeof_trailing_entry: backward
    7-bit groups, high bit set on the first byte of the entry, at most 4 bytes)."""
    bitpos = result = 0
    idx = len(rec) - 1
    while idx >= 0:
        v = rec[idx]
        result |= (v & 0x7F) << bitpos
        bitpos += 7
        idx -= 1
        if (v & 0x80) or bitpos >= 28 or idx < 0:
            break
    return result


def extract_text(path: Path) -> str:
    """All text records of a MOBI/AZW3 file, decompressed, trailing entries removed. For KF8 only
    flow 0 (the markup; later FDST flows are CSS/SVG).

    Trailing entries are stripped like Calibre's MobiReader.sizeof_trailing_entries: one entry per
    set bit of extra_flags >> 1 (lowest bit first, each read from the current end of the record),
    then the multibyte overlap (bit 0) last."""
    data = Path(path).read_bytes()
    nrec = struct.unpack_from(">H", data, 76)[0]
    offs = [struct.unpack_from(">I", data, 78 + i * 8)[0] for i in range(nrec)] + [len(data)]
    r0 = offs[0]
    compression = struct.unpack_from(">H", data, r0)[0]
    num_text = struct.unpack_from(">H", data, r0 + 8)[0]
    hdr_len = struct.unpack_from(">I", data, r0 + 20)[0]
    version = struct.unpack_from(">I", data, r0 + 36)[0]
    extra = struct.unpack_from(">H", data, r0 + 0xF2)[0] if hdr_len >= 0xE4 else 0
    trailers = (extra >> 1).bit_count()
    multibyte = extra & 1
    chunks = []
    for i in range(1, num_text + 1):
        rec = data[offs[i]:offs[i + 1]]
        for _ in range(trailers):
            sz = _trailing_entry_size(rec)
            if sz <= 0 or sz > len(rec):
                break
            rec = rec[:-sz]
        if multibyte and rec:
            rec = rec[:-((rec[-1] & 3) + 1)]
        if compression == 2:
            rec = palmdoc_decompress(rec)
        elif compression != 1:
            raise ValueError(f"unsupported compression {compression}")
        chunks.append(rec)
    text = b"".join(chunks)
    if version >= 8 and hdr_len >= 0xC8:
        fdst_idx = struct.unpack_from(">I", data, r0 + 0xC0)[0]
        if fdst_idx < nrec:
            rec = data[offs[fdst_idx]:offs[fdst_idx + 1]]
            if rec[:4] == b"FDST" and len(rec) >= 16:
                end = struct.unpack_from(">I", rec, 16)[0]   # first section: (start, end)
                if 0 < end <= len(text):
                    text = text[:end]
    return text.decode("utf-8", errors="replace")


_TAG_RE = re.compile(r"<[^>]*>", re.DOTALL)


def strip_markup(markup: str) -> str:
    t = re.sub(r"<style\b[^>]*>.*?</style>", " ", markup, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<head\b[^>]*>.*?</head>", " ", t, flags=re.DOTALL | re.IGNORECASE)
    t = _TAG_RE.sub(" ", t)
    return html.unescape(t)


def text_similarity(a: str, b: str):
    """-> (similarity, note). Word-level; capped at MAX_WORDS per side.

    quick_ratio() is an upper bound of ratio(). When it is already below 0.5 (texts clearly
    unrelated) that bound is returned and flagged; otherwise the exact ratio() is computed."""
    wa, wb = a.split(), b.split()
    notes = []
    if len(wa) > MAX_WORDS or len(wb) > MAX_WORDS:
        wa, wb = wa[:MAX_WORDS], wb[:MAX_WORDS]
        notes.append(f"truncated to {MAX_WORDS} words")
    if wa == wb:
        return 1.0, "; ".join(notes) or None
    if not wa or not wb:
        return 0.0, "; ".join(notes) or None
    # autojunk=True: ~10x faster on 100k-word books (0.7s vs 6.5s) and within 1e-4 of the exact value;
    # pathological inputs (every 5th word swapped) are still slow, real converter output is not.
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=True)
    qr = sm.quick_ratio()
    if qr < 0.5:
        notes.append("quick_ratio upper bound")
        return round(qr, 4), "; ".join(notes)
    return round(sm.ratio(), 4), "; ".join(notes) or None


# ── public API ──────────────────────────────────────────────────────────────

def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


def diff(entry: dict, out_dir: Path, fmt: str):
    out_dir = Path(out_dir)
    ours_f, cal_f = out_dir / f"ours.{fmt}", out_dir / f"calibre.{fmt}"
    if not ours_f.exists() or not cal_f.exists():
        return None
    errors = []
    insp = out_dir / "inspect" / fmt
    io = _safe(_run_inspect, ours_f, insp / "ours.txt") or {}
    ic = _safe(_run_inspect, cal_f, insp / "calibre.txt") or {}

    r = {"header_fields_diff": _safe(_header_diff, io.get("header_text"), ic.get("header_text"))}

    ut = out_dir / "unpack" / fmt
    to, tc = ut / "ours" / "kindleunpack", ut / "calibre" / "kindleunpack"
    for key, fn in (("chapters", _count_chapters), ("ncx_depth", _ncx_depth), ("css_rules", _css_rules)):
        r[f"{key}_ours"] = _safe(fn, to) if to.exists() else None
        r[f"{key}_cal"] = _safe(fn, tc) if tc.exists() else None

    try:
        sim, note = text_similarity(strip_markup(extract_text(ours_f)), strip_markup(extract_text(cal_f)))
        r["text_similarity"] = sim
        if note:
            r["text_similarity_note"] = note
    except Exception as e:
        r["text_similarity"] = None
        errors.append(f"text_similarity: {type(e).__name__}: {e}")

    r["skel_entries_ours"], r["skel_entries_cal"] = io.get("skel"), ic.get("skel")
    r["chunk_entries_ours"], r["chunk_entries_cal"] = io.get("chunks"), ic.get("chunks")
    r["ncx_entries_ours"], r["ncx_entries_cal"] = io.get("ncx"), ic.get("ncx")
    r["inspect_error_ours"], r["inspect_error_cal"] = io.get("error"), ic.get("error")
    if errors:
        r["error"] = "; ".join(errors)
    return r


if __name__ == "__main__":
    d = Path(sys.argv[1])
    print(json.dumps(diff({}, d, sys.argv[2]), indent=1, ensure_ascii=False))
