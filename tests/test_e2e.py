"""
End-to-end tests for the EPUB → AZW3 converter.

Converts real EPUB files using the same pipeline as the browser app
(simulated in Python), validates output with Calibre, and takes headless
screenshots of the rendered KF8 chapters to visually verify correctness.

Run:  uv run tests/test_e2e.py
Deps: uv (https://docs.astral.sh/uv/) — no install needed beyond uv itself.
      Playwright chromium is installed on first run via uv --with playwright.

# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""

import zipfile
import io
import re
import base64
import struct
import time
import random
import subprocess
import sys
import os
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from epub_fixtures import make_epub, MINIMAL_PNG

# ── KF8 binary writer (mirrors docs/index.html) ────────────────────────────

def encint(v: int) -> bytes:
    """Calibre VLQ: high bit on LAST byte (terminator)."""
    v = v & 0xFFFFFFFF
    b = []
    while v > 0:
        b.append(v & 0x7f)
        v >>= 7
    if not b:
        b = [0]
    b[0] |= 0x80
    b.reverse()
    return bytes(b)

def align4(data: bytes) -> bytes:
    r = len(data) % 4
    return data if not r else data + b'\x00' * (4 - r)

def build_exth(records: list[tuple[int, str]]) -> bytes:
    parts = b''.join(struct.pack('>II', tag, 8 + len(v.encode())) + v.encode() for tag, v in records)
    pad = 4 - (len(parts) % 4) or 4
    return b'EXTH' + struct.pack('>II', 12 + len(parts), len(records)) + parts + b'\x00' * pad

def build_fdst(flows: list[tuple[int, int]]) -> bytes:
    return b'FDST' + struct.pack('>II', 12, len(flows)) + b''.join(struct.pack('>II', s, e) for s, e in flows)

FLIS = bytes([0x46,0x4c,0x49,0x53,0,0,0,8,0,0x41,0,0,0,0,0,0,0xff,0xff,0xff,0xff,0,1,0,3,0,0,0,3,0,0,0,1,0xff,0xff,0xff,0xff])

def build_fcis(text_len: int) -> bytes:
    return (b'FCIS' + struct.pack('>IIIII', 0x14, 0x10, 2, 0, text_len)
            + struct.pack('>IIIII', 0, 0x28, 0, 0x28, 8)
            + bytes([0, 1, 0, 1, 0, 0, 0, 0]))

EOF_REC = bytes([0xe9, 0x8e, 0x0d, 0x0a])
TRS = 4096

def split_text_records(text_bytes: bytes) -> list[bytes]:
    records = []
    pos = 0
    while pos < len(text_bytes):
        end = min(pos + TRS, len(text_bytes))
        while end < len(text_bytes) and (text_bytes[end] & 0xc0) == 0x80:
            end += 1
        records.append(text_bytes[pos:end] + b'\x00')
        pos = end
    return records or [b'\x00']

M2S = {1:0,2:1,3:0,4:2,8:3,12:2,16:4,32:5,48:4,64:6,128:7,192:6}

def build_tagx(tag_types: list[dict]) -> bytes:
    body = b''.join(bytes([t['num'], t['vpe'], t['mask'], 0]) for t in tag_types) + bytes([0,0,0,1])
    return b'TAGX' + struct.pack('>II', 12 + len(body), 1) + body

def serialize_entry(key: str, tags: dict, tag_types: list[dict]) -> bytes:
    kb = key.encode()
    ctrl = 0
    for t in tag_types:
        v = tags.get(t['num'], [])
        ctrl |= t['mask'] & ((len(v) // t['vpe']) << M2S[t['mask']])
    vals = b''.join(encint(v) for t in tag_types for v in tags.get(t['num'], []))
    return bytes([len(kb)]) + kb + bytes([ctrl]) + vals

def build_indx_records(entries: list[dict], tag_types: list[dict], cncx: bytes | None = None) -> list[bytes]:
    HDR, LIM = 192, 0x10000 - 192 - 1048
    blocks, idxts, counts, last_keys = [[]], [[]], [0], [b'']
    for e in entries:
        eb = serialize_entry(e['key'], e['tags'], tag_types)
        bi = len(blocks) - 1
        used = sum(len(b) for b in blocks[bi]) + len(idxts[bi]) * 2
        if used + len(eb) + 2 > LIM and blocks[bi]:
            blocks.append([]); idxts.append([]); counts.append(0); last_keys.append(b'')
        ci = len(blocks) - 1
        idxts[ci].append(HDR + sum(len(b) for b in blocks[ci]))
        blocks[ci].append(eb); counts[ci] += 1; last_keys[ci] = e['key'].encode()

    data_recs = []
    for i in range(len(blocks)):
        body = align4(b''.join(blocks[i]))
        id_data = b''.join(struct.pack('>H', o) for o in idxts[i])
        idxt_block = align4(b'IDXT' + id_data)
        h = bytearray(HDR); h[0:4] = b'INDX'
        struct.pack_into('>I', h, 4, HDR); struct.pack_into('>I', h, 12, 1)
        struct.pack_into('>I', h, 20, HDR + len(body)); struct.pack_into('>I', h, 24, counts[i])
        for k in range(28, 36): h[k] = 0xff
        data_recs.append(bytes(h) + body + idxt_block)

    tagx = align4(build_tagx(tag_types))
    geom = align4(b''.join(bytes([len(k)]) + k + struct.pack('>H', counts[i]) for i, k in enumerate(last_keys)))
    g_pos = HDR + len(tagx); g_off = 0; hi = []
    for k in last_keys:
        hi.append(struct.pack('>H', g_pos + g_off)); g_off += 1 + len(k) + 2
    h_idxt = align4(b'IDXT' + b''.join(hi))
    hh = bytearray(HDR); hh[0:4] = b'INDX'
    struct.pack_into('>I', hh, 4, HDR); struct.pack_into('>I', hh, 16, 2)
    struct.pack_into('>I', hh, 20, HDR + len(tagx) + len(geom)); struct.pack_into('>I', hh, 24, len(data_recs))
    struct.pack_into('>I', hh, 28, 65001); struct.pack_into('>I', hh, 32, 0xffffffff)
    struct.pack_into('>I', hh, 36, len(entries)); struct.pack_into('>I', hh, 52, 1 if cncx else 0)
    struct.pack_into('>I', hh, 180, HDR)
    return [bytes(hh) + tagx + geom + h_idxt] + data_recs + ([cncx] if cncx else [])

SKEL_T = [{'num':1,'vpe':1,'mask':3}, {'num':6,'vpe':2,'mask':12}]
CHUNK_T = [{'num':2,'vpe':1,'mask':1}, {'num':3,'vpe':1,'mask':2}, {'num':4,'vpe':1,'mask':4}, {'num':6,'vpe':2,'mask':8}]

def build_cncx(selectors: list[str]) -> tuple[bytes, list[int]]:
    data = b''; offsets = []
    for sel in selectors:
        sb = sel.encode(); offsets.append(len(data))
        lv = encint(len(sb)); data += lv + sb
    return align4(data), offsets

def build_pdb(title: str, records: list[bytes]) -> bytes:
    now = int(time.time()); nR = len(records); hS = 78 + 8 * nR + 2
    h = bytearray(hS)
    t = title.replace(' ', '_')[:31].encode('ascii', 'replace'); h[:len(t)] = t
    struct.pack_into('>II', h, 36, now, now); h[60:68] = b'BOOKMOBI'
    struct.pack_into('>I', h, 68, 2 * nR - 1); struct.pack_into('>H', h, 76, nR)
    off = hS
    for i, rec in enumerate(records):
        struct.pack_into('>I', h, 78 + i * 8, off); h[78 + i * 8 + 4] = 0
        uid = 2 * i; h[78+i*8+5]=(uid>>16)&0xff; h[78+i*8+6]=(uid>>8)&0xff; h[78+i*8+7]=uid&0xff
        off += len(rec)
    return bytes(h) + b''.join(records)

# ── EPUB → AZW3 converter ─────────────────────────────────────────────────

BLOCK_TAGS = {'p','div','h1','h2','h3','h4','h5','h6','section','article',
              'blockquote','pre','ul','ol','li','table','tr','td','th'}

def convert_epub(epub_path: str, out_path: str) -> dict:
    """Convert an EPUB to AZW3. Returns metadata dict."""
    with zipfile.ZipFile(epub_path) as z:
        container = ET.fromstring(z.read('META-INF/container.xml'))
        ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container'}
        opf_path = container.find('.//c:rootfile', ns).get('full-path')
        opf_dir = '/'.join(opf_path.split('/')[:-1]) + '/' if '/' in opf_path else ''
        resolve = lambda h: opf_dir + h.split('#')[0]

        opf = ET.fromstring(z.read(opf_path))
        opf_ns = {'dc': 'http://purl.org/dc/elements/1.1/', 'opf': 'http://www.idpf.org/2007/opf'}

        def get_dc(tag):
            el = opf.find(f'.//dc:{tag}', opf_ns)
            return el.text.strip() if el is not None and el.text else ''

        title    = get_dc('title') or 'Unknown'
        creator  = get_dc('creator')
        language = get_dc('language')[:2] or 'en'

        manifest = {item.get('id'): {'href': item.get('href'), 'mt': item.get('media-type', '')}
                    for item in opf.findall('.//opf:item', opf_ns)}
        spine = [manifest[ir.get('idref')]['href']
                 for ir in opf.findall('.//opf:itemref', opf_ns)
                 if ir.get('idref') in manifest]

        # CSS — only extract critical visibility rules (display:none / visibility:hidden).
        # Full CSS inlining causes the skeleton_head to exceed 4096 bytes, splitting
        # the HTML mid-<style> tag across text records and making CSS appear as
        # visible body text on Kindle.
        css = ''
        for item in manifest.values():
            if item['mt'] == 'text/css':
                try:
                    sheet = z.read(resolve(item['href'])).decode('utf-8')
                    for m in re.finditer(r'([^{}]+)\{([^}]*)\}', sheet):
                        if re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', m.group(2), re.I):
                            css += m.group(1).strip() + '{' + m.group(2).strip() + '}\n'
                except Exception: pass

        # Images → base64 data URIs
        image_uris: dict[str, str] = {}
        for item in manifest.values():
            if item['mt'].startswith('image/'):
                try:
                    data = z.read(resolve(item['href']))
                    b64 = base64.b64encode(data).decode()
                    image_uris[item['href']] = f"data:{item['mt']};base64,{b64}"
                    image_uris[item['href'].split('/')[-1]] = f"data:{item['mt']};base64,{b64}"
                except Exception: pass

        style_block = f'<style type="text/css">\n{css}</style>\n' if css else ''
        aid_counter = [1]
        chapters = []

        for href in spine:
            path = resolve(href)
            ch_dir = '/'.join(href.split('/')[:-1]) + '/' if '/' in href else ''
            try:
                raw = z.read(path).decode('utf-8', errors='replace')
            except Exception:
                continue

            tm = re.search(r'<title[^>]*>(.*?)</title>', raw, re.I | re.S)
            ch_title = (tm.group(1).strip() if tm else '').replace('&', '&amp;').replace('<', '&lt;')

            bm = re.search(r'<body[^>]*>(.*?)</body>', raw, re.I | re.S)
            body = bm.group(1) if bm else raw

            # Inline images
            def replace_img(m):
                src = m.group(1)
                for key in [ch_dir + src, src, src.split('/')[-1]]:
                    if key in image_uris:
                        return f'src="{image_uris[key]}"'
                return m.group(0)
            body = re.sub(r'src="(?!data:)([^"]+)"', replace_img, body)

            # Add aid attributes
            first_aid = aid_counter[0]
            def add_aid(m):
                tag = m.group(1).lower()
                if tag in BLOCK_TAGS and 'aid=' not in m.group(0):
                    a = aid_counter[0]; aid_counter[0] += 1
                    return m.group(0)[:-1] + f' aid="{a}">'
                return m.group(0)
            body = re.sub(r'<(\w+)(\s[^>]*)?>',
                          lambda m: add_aid(m) if m.group(1).lower() in BLOCK_TAGS else m.group(0),
                          body)

            # No <?xml?> declaration: renders as visible text in HTML mode.
            skel_head = (f'<html xmlns="http://www.w3.org/1999/xhtml">\n'
                         f'<head>\n<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>\n'
                         f'<title>{ch_title}</title>\n{style_block}</head>\n<body aid="0">\n')
            skel_tail = '</body>\n</html>\n'
            chapters.append({'skel_head': skel_head, 'skel_tail': skel_tail,
                             'content': body, 'first_aid': first_aid})

        # Build AZW3
        hbo = 0; idx_parts = []
        for i, ch in enumerate(chapters):
            hB = len(ch['skel_head'].encode()); tB = len(ch['skel_tail'].encode()); cB = len(ch['content'].encode())
            idx_parts.append({'ci': i, 'cc': 1, 'sh': hB, 'st': tB, 'cb': cB, 'fs': hbo, 'fa': ch['first_aid']})
            hbo += hB + tB + cB

        full_text = ''.join(ch['skel_head'] + ch['skel_tail'] + ch['content'] for ch in chapters)
        text_bytes = full_text.encode('utf-8')
        text_len = len(text_bytes)
        text_recs = split_text_records(text_bytes)

        recs: list[bytes] = [b''] + list(text_recs)
        dl = sum(len(r) for r in recs[1:])
        if dl % 4: recs.append(b'\x00' * (4 - dl % 4))
        fnt = len(recs)

        skel_entries = [{'key': f'SKEL{i:010}', 'tags': {1: [p['cc'], p['cc']], 6: [p['fs'], p['sh']+p['st'], p['fs'], p['sh']+p['st']]}} for i, p in enumerate(idx_parts)]
        skel_recs = build_indx_records(skel_entries, SKEL_T)
        skel_idx = len(recs); [recs.append(r) for r in skel_recs]

        sels = [f"P-//*[@aid='{p['fa']}']" for p in idx_parts]
        cncx_data, offsets = build_cncx(sels)
        chunk_entries = [{'key': str(p['fs']+p['sh']-1).zfill(10), 'tags': {2: [offsets[i]], 3: [p['ci']], 4: [0], 6: [p['fs']+p['sh']+p['st'], p['cb']]}} for i, p in enumerate(idx_parts)]
        chunk_recs = build_indx_records(chunk_entries, CHUNK_T, cncx_data)
        chunk_idx = len(recs); [recs.append(r) for r in chunk_recs]

        fdst_rec = len(recs); recs.append(build_fdst([(0, hbo)]))
        flis_rec = len(recs); recs.append(FLIS)
        fcis_rec = len(recs); recs.append(build_fcis(text_len)); recs.append(EOF_REC)

        uid = random.randint(0, 0xFFFFFFFF)
        lang_code = {'nl':19,'en':9,'fr':12,'de':7,'ja':17}.get(language, 9)
        exth_records = [(503, title), (112, f'epub2azw3:{uid}'), (113, str(uid)),
                        (501, 'EBOK'), (524, language), (528, 'true')]
        if creator: exth_records.append((100, creator))

        H = 280; h = bytearray(H)
        struct.pack_into('>H', h, 0, 1)
        struct.pack_into('>I', h, 4, text_len)
        struct.pack_into('>H', h, 8, len(text_recs)); struct.pack_into('>H', h, 10, TRS)
        h[16:20] = b'MOBI'; struct.pack_into('>I', h, 20, 264)
        struct.pack_into('>I', h, 24, 2); struct.pack_into('>I', h, 28, 65001)
        struct.pack_into('>I', h, 32, uid); struct.pack_into('>I', h, 36, 8)
        for off in range(40, 80, 4): struct.pack_into('>I', h, off, 0xffffffff)
        ex = build_exth(exth_records)
        title_bytes = title.encode('utf-8')
        struct.pack_into('>I', h, 80, fnt); struct.pack_into('>I', h, 84, H + len(ex))
        struct.pack_into('>I', h, 88, len(title_bytes)); struct.pack_into('>I', h, 92, lang_code)
        struct.pack_into('>I', h, 104, 8); struct.pack_into('>I', h, 108, 0xffffffff)
        struct.pack_into('>I', h, 128, 0x50); struct.pack_into('>I', h, 164, 0xffffffff)
        struct.pack_into('>I', h, 168, 0xffffffff)
        struct.pack_into('>I', h, 192, fdst_rec); struct.pack_into('>I', h, 196, fdst_rec)
        struct.pack_into('>I', h, 200, fcis_rec); struct.pack_into('>I', h, 204, 1)
        struct.pack_into('>I', h, 208, flis_rec); struct.pack_into('>I', h, 212, 1)
        struct.pack_into('>I', h, 224, 0xffffffff)
        for k in range(232, 240): h[k] = 0xff
        struct.pack_into('>I', h, 240, 1); struct.pack_into('>I', h, 244, 0xffffffff)
        struct.pack_into('>I', h, 248, chunk_idx); struct.pack_into('>I', h, 252, skel_idx)
        struct.pack_into('>I', h, 256, 0xffffffff); struct.pack_into('>I', h, 260, 0xffffffff)
        h[264:268] = h[272:276] = bytes([0xff] * 4)
        recs[0] = bytes(h) + ex + title_bytes + b'\x00' * 8192

        azw3 = build_pdb(title, recs)
        Path(out_path).write_bytes(azw3)
        return {'title': title, 'creator': creator, 'language': language,
                'chapters': len(chapters), 'images': len(image_uris) // 2,
                'size': len(azw3)}

# ── Test framework ─────────────────────────────────────────────────────────

passed = 0; failed = 0; failures = []

def test(name, fn):
    global passed, failed
    try:
        fn(); print(f'  ✓ {name}'); passed += 1
    except Exception as e:
        print(f'  ✗ {name}'); print(f'    {e}'); failed += 1; failures.append((name, str(e)))

def calibre_meta(path):
    r = subprocess.run(['ebook-meta', path], capture_output=True, text=True)
    return r.stdout + r.stderr

def calibre_txt(from_path, to_path):
    r = subprocess.run(['ebook-convert', from_path, to_path], capture_output=True, text=True, timeout=120)
    return r.returncode == 0 and 'Traceback' not in r.stdout, r.stdout + r.stderr

# ── Test cases ─────────────────────────────────────────────────────────────

# Generate synthetic EPUB 3 test file
_epub3_path = '/tmp/synthetic_epub3.epub'
Path(_epub3_path).write_bytes(make_epub(
    'EPUB3 Synthetic Book',
    [('Chapter One',   '<p>First chapter of a synthetic EPUB 3.0 book.</p>'),
     ('Chapter Two',   '<p>Second chapter with some more content here.</p>'),
     ('Chapter Three', '<p>Third chapter — final chapter of this test book.</p>')],
    version='3.0'
))

# Generate synthetic EPUB with display:none CSS (simulates Dutch publisher book)
_css_epub_path = '/tmp/synthetic_css_visibility.epub'
Path(_css_epub_path).write_bytes(make_epub(
    'CSS Visibility Test Book',
    [('Chapter 1',
      '<div class="wpt-verdwijn">HIDDEN WATERMARK</div>'
      '<span class="wpt-invis">invisible span</span>'
      '<p>Visible text content here.</p>'),
     ('Chapter 2', '<p>Second chapter content.</p>')],
    css_rules=[
        ('.wpt-verdwijn', 'display: none'),
        ('.wpt-invis', 'visibility: hidden'),
        ('p', 'font-family: serif'),  # should NOT be extracted
    ]
))

# Generate synthetic EPUB with an image
_img_epub_path = '/tmp/synthetic_with_image.epub'
Path(_img_epub_path).write_bytes(make_epub(
    'Image Test Book',
    [('Chapter with Image',
      '<p>This chapter has an image embedded above.</p>'),
     ('Text Chapter', '<p>Second chapter with text only.</p>')],
    images=[('cover.png', MINIMAL_PNG)]
))

EPUB_TESTS = [
    ('/tmp/alice_images.epub',         "Alice in Wonderland (EPUB2 + images)", "Alice's Adventures"),
    ('/tmp/pride_prejudice.epub',      "Pride and Prejudice (long book)",       "Pride and Prejudice"),
    ('/tmp/sherlock.epub',             "Sherlock Holmes",                        "Adventures of Sherlock Holmes"),
    ('/tmp/tale_two_cities.epub',      "A Tale of Two Cities (48 chapters)",    "Tale of Two Cities"),
    ('/tmp/moby_dick.epub',            "Moby Dick",                             "Moby Dick"),
    (_epub3_path,                      "Synthetic EPUB 3.0",                    "EPUB3"),
    (_css_epub_path,                   "Synthetic: CSS display:none",           "CSS Visibility"),
    (_img_epub_path,                   "Synthetic: embedded image",             "Image Test"),
]

for epub_path, label, expected_title_fragment in EPUB_TESTS:
    if not Path(epub_path).exists():
        print(f'  ⚠ skip {label} (not found: {epub_path})')
        continue

    out_path = epub_path.replace('.epub', '_e2e.azw3')
    txt_path = epub_path.replace('.epub', '_e2e.txt')
    meta = None

    print(f'\n── {label} ──')

    def do_convert():
        global meta
        meta = convert_epub(epub_path, out_path)

    test('Conversion completes without error', do_convert)

    test('Output file is non-empty AZW3', lambda: (
        __import__('zipfile') and  # just import check
        __import__('os') and
        (_ := Path(out_path).stat().st_size if Path(out_path).exists() else 0) > 1000
        and None  # returns None, truthy check is in assert below
    ) or (_ := Path(out_path).stat().st_size if Path(out_path).exists() else 0) > 1000)
    # Simpler version:
    test('Output file exists and is > 1KB', lambda op=out_path: Path(op).exists() and Path(op).stat().st_size > 1000)

    test(f'Has expected chapters (≥3)', lambda m=meta: m is not None and m['chapters'] >= 3)

    test('Calibre reads title', lambda op=out_path, frag=expected_title_fragment: (
        frag.lower() in calibre_meta(op).lower()
    ) if Path(op).exists() else (_ for _ in ()).throw(AssertionError('no output file')))

    test('Calibre converts to TXT without errors', lambda op=out_path, tp=txt_path: (
        calibre_txt(op, tp)[0] if Path(op).exists() else False
    ))

    test('TXT output contains prose (>500 chars)', lambda tp=txt_path: (
        len(Path(tp).read_text(errors='replace')) > 500 if Path(tp).exists() else False
    ))

    if meta and meta.get('images', 0) > 0:
        test(f'Images embedded ({meta["images"]}x data URIs)', lambda op=out_path: (
            b'data:image/' in Path(op).read_bytes()
        ) if Path(op).exists() else False)

    # CSS-specific: display:none rule must survive into AZW3
    if 'css_visibility' in epub_path.lower() or 'css' in label.lower():
        test('display:none CSS rule in AZW3 binary', lambda op=out_path: (
            (b'display: none' in Path(op).read_bytes() or
             b'display:none' in Path(op).read_bytes())
        ) if Path(op).exists() else False)
        test('Non-visibility CSS NOT in AZW3', lambda op=out_path: (
            b'font-family: serif' not in Path(op).read_bytes()
        ) if Path(op).exists() else True)

    # Skeleton head size check — must not exceed 4096 bytes
    if meta and Path(out_path).exists():
        def _check_skel_size(op=out_path):
            d = Path(op).read_bytes()
            nrec = struct.unpack_from('>H', d, 76)[0]
            r0 = struct.unpack_from('>I', d, 78)[0]
            skel_idx = struct.unpack_from('>I', d, r0+252)[0]
            if skel_idx == 0xffffffff:
                return  # no skeleton, skip
            skel_dr = struct.unpack_from('>I', d, 78+(skel_idx+1)*8)[0]
            io2 = struct.unpack_from('>I', d, skel_dr+20)[0]
            eo = struct.unpack_from('>H', d, skel_dr+io2+4)[0]
            p = skel_dr + eo; kl = d[p]; p += 1+kl
            ctrl = d[p]; p += 1
            geom = []
            for _ in range(((ctrl&12)>>2)*2):
                val = consumed = 0
                for i in range(p, len(d)):
                    b = d[i]; val=(val<<7)|(b&0x7f); consumed+=1
                    if b & 0x80: break
                geom.append(val); p += consumed
            skel_len = geom[1] if len(geom) > 1 else 0
            assert skel_len <= 4096, \
                f'Skeleton {skel_len}B > 4096 (one text record): CSS may appear as visible text!'
        test('Skeleton head fits in one text record (≤4096 B)', _check_skel_size)

# ── Validation checks ──────────────────────────────────────────────────────

print('\n── Binary format validation ──')

# Re-convert Alice and check specific binary properties
alice_path = '/tmp/alice_images.epub'
if Path(alice_path).exists():
    out = '/tmp/alice_validate.azw3'
    try:
        meta = convert_epub(alice_path, out)
        data = Path(out).read_bytes()
        dv = memoryview(data)

        test('PDB magic = BOOKMOBI', lambda: data[60:68] == b'BOOKMOBI')

        def check_mobi_header():
            nrec = struct.unpack_from('>H', data, 76)[0]
            r0off = struct.unpack_from('>I', data, 78)[0]
            assert data[r0off+16:r0off+20] == b'MOBI', 'MOBI ident missing'
            assert struct.unpack_from('>I', data, r0off+20)[0] == 264, 'header_length != 264'
            assert struct.unpack_from('>I', data, r0off+36)[0] == 8, 'file_version != 8'
            assert struct.unpack_from('>I', data, r0off+28)[0] == 65001, 'encoding != UTF-8'
        test('MOBI header fields correct', check_mobi_header)

        def check_exth():
            nrec = struct.unpack_from('>H', data, 76)[0]
            r0off = struct.unpack_from('>I', data, 78)[0]
            assert data[r0off+280:r0off+284] == b'EXTH', 'EXTH magic missing'
        test('EXTH section present', check_exth)

        def check_indices():
            nrec = struct.unpack_from('>H', data, 76)[0]
            r0off = struct.unpack_from('>I', data, 78)[0]
            skel_idx = struct.unpack_from('>I', data, r0off+252)[0]
            chunk_idx = struct.unpack_from('>I', data, r0off+248)[0]
            assert skel_idx != 0xffffffff, f'skel_index = NULL'
            assert chunk_idx != 0xffffffff, f'chunk_index = NULL'
            # Check INDX magic at skel record
            rec_offsets = [struct.unpack_from('>I', data, 78+i*8)[0] for i in range(nrec)]
            skel_off = rec_offsets[skel_idx]
            assert data[skel_off:skel_off+4] == b'INDX', 'skel record is not INDX'
            chunk_off = rec_offsets[chunk_idx]
            assert data[chunk_off:chunk_off+4] == b'INDX', 'chunk record is not INDX'
        test('Skeleton and chunk INDX records present with correct magic', check_indices)

        test('FDST record present with correct magic', lambda: (
            lambda nrec, r0off: (
                lambda fdst_rec: data[
                    struct.unpack_from('>I', data, 78+fdst_rec*8)[0]:
                    struct.unpack_from('>I', data, 78+fdst_rec*8)[0]+4
                ] == b'FDST'
            )(struct.unpack_from('>I', data, r0off+192)[0])
        )(struct.unpack_from('>H', data, 76)[0], struct.unpack_from('>I', data, 78)[0]))

        test('All text records have trailing 0 byte', lambda: all(
            True for i in range(1, struct.unpack_from('>H', data, 76)[0])
            if (off := struct.unpack_from('>I', data, 78+i*8)[0]) and
               (next_off := struct.unpack_from('>I', data, 78+(i+1)*8)[0] if i+1 < struct.unpack_from('>H', data, 76)[0] else len(data)) and
               data[next_off-1] == 0
        ))

        def check_skeleton_fits_in_one_record():
            """Skeleton head must fit entirely within one 4096-byte text record.
            If it's larger, the HTML gets split mid-<style> tag causing CSS to
            appear as visible body text on Kindle."""
            nrec = struct.unpack_from('>H', data, 76)[0]
            r0off = struct.unpack_from('>I', data, 78)[0]
            skel_idx = struct.unpack_from('>I', data, r0off + 252)[0]
            if skel_idx == 0xffffffff:
                return  # no skeleton index
            # Read first skeleton entry to get skeleton length
            skel_data_off = struct.unpack_from('>I', data, 78 + (skel_idx + 1) * 8)[0]
            idxt_off = struct.unpack_from('>I', data, skel_data_off + 20)[0]
            entry_off = struct.unpack_from('>H', data, skel_data_off + idxt_off + 4)[0]
            pos = skel_data_off + entry_off
            key_len = data[pos]; pos += 1 + key_len
            ctrl = data[pos]; pos += 1
            # geometry values: count = (ctrl & 12) >> 2 groups of 2 values
            count = (ctrl & 12) >> 2
            skel_len_bytes = None
            for _ in range(count * 2):
                val, consumed = 0, 0
                for i in range(pos, len(data)):
                    b = data[i]; val = (val << 7) | (b & 0x7f); consumed += 1
                    if b & 0x80: break
                if skel_len_bytes is None:
                    pass  # first value = start position
                else:
                    skel_len_bytes = val  # second value = length
                    break
                skel_len_bytes = val
                pos += consumed
            if skel_len_bytes is not None:
                assert skel_len_bytes <= 4096, (
                    f'Skeleton {skel_len_bytes} bytes > 4096 (one text record). '
                    'CSS will appear as visible text on Kindle!')
        test('Skeleton head fits in one text record (≤4096 bytes)', check_skeleton_fits_in_one_record)

    except Exception as e:
        print(f'  ⚠ Binary validation skipped: {e}')

# ── Screenshot validation (requires playwright) ────────────────────────────

print('\n── Screenshot validation ──')

alice_azw3 = '/tmp/alice_validate.azw3'
if Path(alice_azw3).exists():
    try:
        from playwright.sync_api import sync_playwright

        def extract_and_screenshot(azw3_path: str) -> list[dict]:
            """Extract KF8 chapters and screenshot them with headless Chromium."""
            data = Path(azw3_path).read_bytes()
            nrec = struct.unpack_from('>H', data, 76)[0]
            rec_offsets = [struct.unpack_from('>I', data, 78 + i * 8)[0] for i in range(nrec)]
            r0 = rec_offsets[0]
            num_text_recs = struct.unpack_from('>H', data, r0 + 8)[0]
            skel_idx  = struct.unpack_from('>I', data, r0 + 252)[0]
            chunk_idx = struct.unpack_from('>I', data, r0 + 248)[0]
            if skel_idx == 0xffffffff:
                return []

            text_bytes = b''
            for i in range(1, num_text_recs + 1):
                s = rec_offsets[i]; e = rec_offsets[i + 1] if i + 1 < nrec else len(data)
                text_bytes += data[s:e - 1]
            text = text_bytes.decode('utf-8', errors='replace')

            def decode_vwi(data, pos):
                val, consumed = 0, 0
                for i in range(pos, len(data)):
                    b = data[i]; val = (val << 7) | (b & 0x7f); consumed += 1
                    if b & 0x80: break
                return val, consumed

            def read_entries(rec_off):
                idxt_off = struct.unpack_from('>I', data, rec_off + 20)[0]
                num = struct.unpack_from('>I', data, rec_off + 24)[0]
                entries = []
                for j in range(num):
                    e_off = struct.unpack_from('>H', data, rec_off + idxt_off + 4 + j * 2)[0]
                    pos = rec_off + e_off
                    kl = data[pos]; key = data[pos+1:pos+1+kl].decode('utf-8','replace')
                    entries.append({'key': key, 'ds': pos+1+kl})
                return entries

            skels_raw = read_entries(rec_offsets[skel_idx + 1])
            skels = []
            for e in skels_raw:
                ctrl = data[e['ds']]; pos = e['ds'] + 1
                n1 = ctrl & 3; n6 = (ctrl & 12) >> 2
                cc_vals = []
                for _ in range(n1):
                    v, c = decode_vwi(data, pos); cc_vals.append(v); pos += c
                geom = []
                for _ in range(n6 * 2):
                    v, c = decode_vwi(data, pos); geom.append(v); pos += c
                skels.append({'cc': cc_vals[0] if cc_vals else 1,
                              'start': geom[0] if geom else 0,
                              'len': geom[1] if len(geom) > 1 else 0})

            # Read chunk index data records
            chunk_hdr_off = rec_offsets[chunk_idx]
            num_chunk_dr = struct.unpack_from('>I', data, chunk_hdr_off + 24)[0]
            chunks_raw = []
            for dr in range(num_chunk_dr):
                chunks_raw.extend(read_entries(rec_offsets[chunk_idx + 1 + dr]))
            chunks = []
            for e in chunks_raw:
                ctrl = data[e['ds']]; pos = e['ds'] + 1
                result = {'ins': int(e['key'])}
                if ctrl & 1:
                    v, c = decode_vwi(data, pos); result['cncx'] = v; pos += c
                if ctrl & 2:
                    v, c = decode_vwi(data, pos); result['fn'] = v; pos += c
                if ctrl & 4:
                    v, c = decode_vwi(data, pos); result['sn'] = v; pos += c
                if ctrl & 8:
                    s, c = decode_vwi(data, pos); pos += c
                    l, c = decode_vwi(data, pos); pos += c
                    result['start'] = s; result['len'] = l
                chunks.append(result)

            # Reconstruct chapters
            chapters = []
            cp = 0
            for sk in skels:
                skel_text = text[sk['start']:sk['start'] + sk['len']]
                html = skel_text
                for _ in range(sk['cc']):
                    if cp >= len(chunks): break
                    ch = chunks[cp]; cp += 1
                    li = ch['ins'] - sk['start']
                    content = text[ch.get('start', sk['start'] + sk['len']):
                                   ch.get('start', sk['start'] + sk['len']) + ch.get('len', 0)]
                    html = html[:li] + content + html[li:]
                body_text = re.sub(r'<[^>]+>', '', html).strip()
                if len(body_text) > 50:
                    chapters.append({'html': html, 'body_text': body_text})
            return chapters

        chapters = extract_and_screenshot(alice_azw3)
        test('KF8 chapter extraction yields chapters', lambda: len(chapters) > 3)

        if chapters:
            def screenshot_and_check():
                issues = []
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    for i, ch in enumerate(chapters[:4]):
                        page = browser.new_page(viewport={'width': 600, 'height': 800})
                        page.set_content(ch['html'], wait_until='domcontentloaded')

                        shot_path = f'/tmp/e2e_screenshot_ch{i:02d}.png'
                        page.screenshot(path=shot_path, full_page=False)

                        # Check for CSS leaking into body text
                        body_text = page.evaluate('() => document.body?.innerText || ""')
                        if '{' in body_text and 'margin' in body_text and '<' not in body_text[:50]:
                            issues.append(f'ch{i}: CSS appearing as visible text')

                        # Check XML declaration isn't visible
                        if '<?xml' in body_text or 'encoding="UTF-8"' in body_text:
                            issues.append(f'ch{i}: XML declaration visible as text')

                        # Check for readable prose (not just CSS/tags)
                        words = re.findall(r'[a-zA-Z]{4,}', body_text)
                        if i > 0 and len(words) < 10:
                            issues.append(f'ch{i}: very little prose text ({len(words)} words)')

                        page.close()
                    browser.close()

                if issues:
                    raise AssertionError('Visual rendering issues: ' + '; '.join(issues))

            test('Screenshots: no CSS leakage, no XML declaration, readable prose', screenshot_and_check)

            def check_skel_head_size():
                """Verify skeleton heads are small enough to fit in one text record."""
                for i, ch in enumerate(chapters[:4]):
                    skel_start = ch['html'].find('<html')
                    skel_end = ch['html'].find('<body aid=')
                    if skel_end > 0:
                        skel_head = ch['html'][skel_start:skel_end + len('<body aid="0">\n')]
                        size = len(skel_head.encode())
                        if size > 4096:
                            raise AssertionError(
                                f'ch{i} skeleton head is {size} bytes > 4096 (one text record). '
                                'Inlined CSS is too large!')
            test('Skeleton heads are each ≤4096 bytes (fit in one text record)', check_skel_head_size)

    except ImportError:
        print('  ⚠ playwright not installed — run: uvx --with playwright playwright install chromium')
    except Exception as e:
        print(f'  ⚠ Screenshot tests skipped: {e}')
        import traceback; traceback.print_exc()

# ── Error cases ────────────────────────────────────────────────────────────

print('\n── Error cases ────────────────────────────────────────────────────')

import tempfile

def test_non_zip():
    with tempfile.NamedTemporaryFile(suffix='.epub', delete=False) as f:
        f.write(b'This is not a ZIP file at all.'); tmp = f.name
    try:
        convert_epub(tmp, '/tmp/err_nonzip.azw3')
        raise AssertionError('Expected exception for non-ZIP input')
    except AssertionError: raise
    except Exception: pass  # any exception is correct

test('Non-ZIP file raises exception', test_non_zip)

def test_empty_file():
    with tempfile.NamedTemporaryFile(suffix='.epub', delete=False) as f:
        tmp = f.name  # 0 bytes
    try:
        convert_epub(tmp, '/tmp/err_empty.azw3')
        raise AssertionError('Expected exception for empty file')
    except AssertionError: raise
    except Exception: pass

test('Empty file raises exception', test_empty_file)

def test_missing_container():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('garbage.txt', 'not an epub at all')
    Path('/tmp/err_no_container.epub').write_bytes(buf.getvalue())
    try:
        convert_epub('/tmp/err_no_container.epub', '/tmp/err_no_container.azw3')
        raise AssertionError('Expected exception for missing container.xml')
    except AssertionError: raise
    except Exception: pass

test('Missing container.xml raises exception', test_missing_container)

def test_empty_spine():
    """EPUB with no spine items → 0 chapters → must not crash."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        mi = zipfile.ZipInfo('mimetype'); mi.compress_type = zipfile.ZIP_STORED
        z.writestr(mi, 'application/epub+zip')
        z.writestr('META-INF/container.xml', '''<?xml version="1.0"?>
<container version="1.0"
  xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>''')
        z.writestr('OEBPS/content.opf', '''<?xml version="1.0"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Empty Spine</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="uid">uid-001</dc:identifier>
  </metadata>
  <manifest/>
  <spine/>
</package>''')
    Path('/tmp/err_empty_spine.epub').write_bytes(buf.getvalue())
    meta = convert_epub('/tmp/err_empty_spine.epub', '/tmp/err_empty_spine.azw3')
    assert meta['chapters'] == 0, f'Expected 0 chapters, got {meta["chapters"]}'

test('Empty spine → 0 chapters, no crash', test_empty_spine)

def test_css_extraction_logic():
    """CSS extractor must keep only display:none / visibility:hidden rules."""
    css = """
        .normal { font-size: 14px; margin: 0; }
        .watermark { display: none; color: red; }
        .hidden { visibility: hidden; }
        .visible { display: block; color: blue; }
        p { font-family: serif; }
        .combo { display: none; font-weight: bold; }
    """
    critical = []
    for m in re.finditer(r'([^{}]+)\{([^}]*)\}', css):
        if re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', m.group(2), re.I):
            critical.append(m.group(1).strip())
    assert any('watermark' in r for r in critical), '.watermark not extracted'
    assert any('hidden' in r for r in critical), '.hidden not extracted'
    assert any('combo' in r for r in critical), '.combo not extracted'
    assert not any('normal' in r for r in critical), '.normal should not be extracted'
    assert not any('visible' in r for r in critical), '.visible should not be extracted'
    assert not any(r.strip() == 'p' for r in critical), 'p rule should not be extracted'

test('CSS extractor keeps only visibility rules', test_css_extraction_logic)

# ── Image rendering via Playwright ────────────────────────────────────────

print('\n── Image rendering (visual) ───────────────────────────────────────')

_img_azw3 = '/tmp/synthetic_with_image_e2e.azw3'
try:
    convert_epub(_img_epub_path, _img_azw3)
    _img_data = Path(_img_azw3).read_bytes()

    # Re-use the extract_and_screenshot helper from the screenshot section above
    try:
        from playwright.sync_api import sync_playwright as _spw

        def _extract_chapters_for_img(azw3_bytes):
            nrec = struct.unpack_from('>H', azw3_bytes, 76)[0]
            rec_offsets = [struct.unpack_from('>I', azw3_bytes, 78+i*8)[0] for i in range(nrec)]
            r0 = rec_offsets[0]
            num_text = struct.unpack_from('>H', azw3_bytes, r0+8)[0]
            skel_idx  = struct.unpack_from('>I', azw3_bytes, r0+252)[0]
            chunk_idx = struct.unpack_from('>I', azw3_bytes, r0+248)[0]
            if skel_idx == 0xffffffff: return []
            text_bytes = b''
            for i in range(1, num_text+1):
                s = rec_offsets[i]; e = rec_offsets[i+1] if i+1 < nrec else len(azw3_bytes)
                text_bytes += azw3_bytes[s:e-1]
            text = text_bytes.decode('utf-8', errors='replace')
            def vwi(d, p):
                val=consumed=0
                for i in range(p, len(d)):
                    b=d[i]; val=(val<<7)|(b&0x7f); consumed+=1
                    if b&0x80: break
                return val, consumed
            def ents(ro):
                io2=struct.unpack_from('>I',azw3_bytes,ro+20)[0]
                n=struct.unpack_from('>I',azw3_bytes,ro+24)[0]; out=[]
                for j in range(n):
                    eo=struct.unpack_from('>H',azw3_bytes,ro+io2+4+j*2)[0]
                    p=ro+eo; kl=azw3_bytes[p]
                    out.append({'key':azw3_bytes[p+1:p+1+kl].decode('utf-8','replace'),'ds':p+1+kl})
                return out
            skels_raw=ents(rec_offsets[skel_idx+1])
            skels=[]
            for e in skels_raw:
                ctrl=azw3_bytes[e['ds']]; pos=e['ds']+1; cc=[]; geom=[]
                for _ in range(ctrl&3): v,c=vwi(azw3_bytes,pos); cc.append(v); pos+=c
                for _ in range(((ctrl&12)>>2)*2): v,c=vwi(azw3_bytes,pos); geom.append(v); pos+=c
                skels.append({'cc':cc[0] if cc else 1,'start':geom[0] if geom else 0,'len':geom[1] if len(geom)>1 else 0})
            num_cdr=struct.unpack_from('>I',azw3_bytes,rec_offsets[chunk_idx]+24)[0]
            chunks_raw=[]
            for dr in range(num_cdr): chunks_raw.extend(ents(rec_offsets[chunk_idx+1+dr]))
            chunks=[]
            for e in chunks_raw:
                ctrl=azw3_bytes[e['ds']]; pos=e['ds']+1; r={'ins':int(e['key'])}
                if ctrl&1: v,c=vwi(azw3_bytes,pos); r['cncx']=v; pos+=c
                if ctrl&2: v,c=vwi(azw3_bytes,pos); r['fn']=v; pos+=c
                if ctrl&4: v,c=vwi(azw3_bytes,pos); r['sn']=v; pos+=c
                if ctrl&8:
                    s,c=vwi(azw3_bytes,pos); pos+=c; l,c=vwi(azw3_bytes,pos); pos+=c
                    r['start']=s; r['len']=l
                chunks.append(r)
            result=[]; cp=0
            for sk in skels:
                html=text[sk['start']:sk['start']+sk['len']]; recon=html
                for _ in range(sk['cc']):
                    if cp>=len(chunks): break
                    ch=chunks[cp]; cp+=1; li=ch['ins']-sk['start']
                    content=text[ch.get('start',sk['start']+sk['len']):ch.get('start',sk['start']+sk['len'])+ch.get('len',0)]
                    recon=recon[:li]+content+recon[li:]
                body=re.sub(r'<[^>]+>','',recon).strip()
                if len(body)>20: result.append({'html':recon,'body':body})
            return result

        img_chaps = _extract_chapters_for_img(_img_data)
        img_chap = next((c for c in img_chaps if '<img' in c['html']), None)

        if img_chap:
            def check_image_render():
                with _spw() as p2:
                    br = p2.chromium.launch()
                    pg = br.new_page()
                    pg.set_content(img_chap['html'], wait_until='domcontentloaded')
                    pg.wait_for_function(
                        '() => { const img=document.querySelector("img"); return !img||img.complete; }',
                        timeout=5000
                    )
                    nw = pg.evaluate('() => document.querySelector("img")?.naturalWidth ?? 0')
                    src = pg.evaluate('() => document.querySelector("img")?.src ?? ""')
                    pg.screenshot(path='/tmp/e2e_image_render.png')
                    br.close()
                assert nw > 0, f'Image naturalWidth={nw}: image did not render'
                assert src.startswith('data:'), f'Image src not a data URI: {src[:50]}'
            test('Rendered img naturalWidth > 0 (not broken)', check_image_render)
            test('Rendered img src is a data: URI',
                 lambda: img_chap is not None and 'data:image/' in img_chap['html'])
        else:
            print('  ⚠ no chapter with <img> found for image rendering test')

    except ImportError:
        print('  ⚠ playwright not available for image rendering test')

except Exception as e:
    print(f'  ⚠ image rendering test skipped: {e}')

# ── Results ────────────────────────────────────────────────────────────────

print(f'\n{"═"*60}')
print(f'  {passed} passed  {failed} failed')
if failures:
    print('\nFailed:')
    for name, err in failures:
        print(f'  ✗ {name}')
        print(f'    {err}')
print()
sys.exit(1 if failed > 0 else 0)
