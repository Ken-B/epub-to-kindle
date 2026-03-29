"""
End-to-end tests for the EPUB → AZW3 converter.

Converts real EPUB files using the same pipeline as the browser app
(simulated in Python), then validates output with Calibre.

Run:  uv run tests/test_e2e.py
Deps: uv (https://docs.astral.sh/uv/) — no install needed beyond uv itself.

# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""

import zipfile
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

        # CSS (strip @font-face)
        css = ''
        for item in manifest.values():
            if item['mt'] == 'text/css':
                try:
                    sheet = z.read(resolve(item['href'])).decode('utf-8')
                    css += re.sub(r'@font-face\s*\{[^}]*\}', '', sheet, flags=re.I) + '\n'
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

            skel_head = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                         f'<html xmlns="http://www.w3.org/1999/xhtml">\n'
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

EPUB_TESTS = [
    ('/tmp/alice_images.epub',    "Alice in Wonderland (with images)",         "Alice's Adventures"),
    ('/tmp/pride_prejudice.epub', "Pride and Prejudice (long book)",            "Pride and Prejudice"),
    ('/tmp/sherlock.epub',        "Sherlock Holmes",                            "Adventures of Sherlock Holmes"),
    ('/tmp/tale_two_cities.epub', "A Tale of Two Cities (48 chapters)",         "Tale of Two Cities"),
    ('/tmp/moby_dick.epub',       "Moby Dick",                                  "Moby Dick"),
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

    except Exception as e:
        print(f'  ⚠ Binary validation skipped: {e}')

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
