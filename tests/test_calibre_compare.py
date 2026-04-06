"""
Calibre comparison tests for the EPUB → AZW3/MOBI converter.

Converts the same EPUBs with both Calibre and our browser app, then
compares the output to verify structural and content correctness.

This catches regressions that simple "Calibre reads it" checks miss —
e.g. the PalmDoc compression bug that corrupted UTF-8 but still produced
a file Calibre could partially parse.

Run:  uv run tests/test_calibre_compare.py

# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""

import struct, subprocess, re, sys, threading, difflib
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from epub_fixtures import make_epub, MINIMAL_PNG

from playwright.sync_api import sync_playwright

# ── Test framework ──────────────────────────────────────────────────────────

passed = 0; failed = 0; failures = []

def test(name, fn):
    global passed, failed
    try:
        r = fn()
        if r is False: raise AssertionError('returned False')
        print(f'  ✓ {name}'); passed += 1
    except Exception as e:
        print(f'  ✗ {name}'); print(f'    {e}')
        failed += 1; failures.append((name, str(e)))

# ── Helpers ─────────────────────────────────────────────────────────────────

class SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_): pass

def start_server():
    docs = str(Path(__file__).parent.parent / 'docs')
    httpd = HTTPServer(('localhost', 0), partial(SilentHandler, directory=docs))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f'http://localhost:{port}'


def calibre_convert(epub_path: str, out_path: str) -> bool:
    """Convert EPUB with Calibre. Returns True on success."""
    r = subprocess.run(
        ['ebook-convert', epub_path, out_path],
        capture_output=True, timeout=120
    )
    return r.returncode == 0 and Path(out_path).exists()


def palmdoc_decompress(data: bytes) -> bytes:
    """PalmDoc decompressor (reference implementation)."""
    out = bytearray(); i = 0
    while i < len(data):
        b = data[i]; i += 1
        if b == 0:
            out.append(0)
        elif b <= 8:
            for _ in range(b):
                if i < len(data): out.append(data[i]); i += 1
        elif b <= 0x7F:
            out.append(b)
        elif b <= 0xBF:
            if i >= len(data): break
            b2 = data[i]; i += 1
            dist = ((b & 0x3F) << 5) | (b2 >> 3)
            ln = (b2 & 7) + 3
            for _ in range(ln):
                out.append(out[-dist] if dist <= len(out) else 0)
        else:
            out.append(0x20); out.append(b & 0x7F)
    return bytes(out)


def extract_text(azw3_path: str) -> str:
    """Extract and decompress all text records from an AZW3/MOBI file."""
    data = Path(azw3_path).read_bytes()
    nrec = struct.unpack_from('>H', data, 76)[0]
    rec_offsets = [struct.unpack_from('>I', data, 78+i*8)[0] for i in range(nrec)]
    r0 = rec_offsets[0]
    compression = struct.unpack_from('>H', data, r0)[0]
    num_text = struct.unpack_from('>H', data, r0+8)[0]

    text_bytes = b''
    for i in range(1, num_text+1):
        s = rec_offsets[i]; e = rec_offsets[i+1] if i+1 < nrec else len(data)
        rec = data[s:e-1]  # strip trailing overlap byte
        if compression == 2:
            rec = palmdoc_decompress(rec)
        text_bytes += rec

    return text_bytes.decode('utf-8', errors='replace')


def header_fields(azw3_path: str) -> dict:
    """Extract key MOBI header fields."""
    data = Path(azw3_path).read_bytes()
    nrec = struct.unpack_from('>H', data, 76)[0]
    r0 = struct.unpack_from('>I', data, 78)[0]
    return {
        'total_records':    nrec,
        'compression':      struct.unpack_from('>H', data, r0)[0],
        'text_length':      struct.unpack_from('>I', data, r0+4)[0],
        'num_text_records': struct.unpack_from('>H', data, r0+8)[0],
        'file_version':     struct.unpack_from('>I', data, r0+36)[0],
        'first_resource':   struct.unpack_from('>I', data, r0+108)[0],
        'ncx_index':        struct.unpack_from('>I', data, r0+244)[0],
    }


def strip_markup(html: str) -> str:
    """Strip HTML tags and normalize whitespace for text comparison."""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def text_similarity(a: str, b: str) -> float:
    """Return 0.0-1.0 similarity between two strings (SequenceMatcher)."""
    # Work on word lists for speed with large texts
    wa = a.split(); wb = b.split()
    return difflib.SequenceMatcher(None, wa[:5000], wb[:5000]).ratio()


def our_convert(page, epub_path: str, fmt: str = 'azw3') -> bytes | None:
    """Convert EPUB using our browser app. Returns AZW3 bytes or None."""
    # Select format
    page.evaluate(f'''
        () => {{
            const radio = document.querySelector('input[name="fmt"][value="{fmt}"]');
            if (radio) radio.click();
        }}
    ''')
    page.set_input_files('#fileInput', {
        'name': Path(epub_path).name,
        'mimeType': 'application/epub+zip',
        'buffer': Path(epub_path).read_bytes(),
    })
    try:
        page.wait_for_function(
            '() => { const s=document.getElementById("status"); '
            'return s && (s.className.includes("ok") || s.className.includes("error")); }',
            timeout=120000
        )
    except Exception:
        return None
    if 'error' in (page.get_attribute('#status', 'class') or ''):
        return None
    raw = page.evaluate('''async () => {
        const r = await fetch(document.getElementById('dlBtn').href);
        return Array.from(new Uint8Array(await r.arrayBuffer()));
    }''')
    return bytes(raw)

# ── Main ─────────────────────────────────────────────────────────────────────

httpd, base_url = start_server()

# Test EPUBs: download if missing
EPUBS = [
    ('/tmp/sherlock.epub',        'Sherlock Holmes',    'https://www.gutenberg.org/ebooks/1661.epub.noimages'),
    ('/tmp/frankenstein.epub',    'Frankenstein',       'https://www.gutenberg.org/ebooks/84.epub.noimages'),
    ('/tmp/pride_prejudice.epub', 'Pride & Prejudice',  'https://www.gutenberg.org/ebooks/1342.epub.noimages'),
]

for path, label, url in EPUBS:
    if not Path(path).exists():
        print(f'Downloading {label}...')
        subprocess.run(['curl', '-sL', url, '-o', path], timeout=30)

# Also test with local EPUBs if present
local_epubs = list(Path(__file__).parent.parent.glob('*.epub'))
for ep in local_epubs:
    EPUBS.append((str(ep), ep.stem[:40], None))

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    for epub_path, label, _ in EPUBS:
        if not Path(epub_path).exists():
            print(f'  ⚠ skip {label} (not found)')
            continue

        print(f'\n── {label} ─────────────────────────────────────────────')

        # ── Generate reference with Calibre ──
        cal_azw3 = epub_path.replace('.epub', '_calibre_ref.azw3')
        cal_mobi = epub_path.replace('.epub', '_calibre_ref.mobi')
        cal_azw3_ok = calibre_convert(epub_path, cal_azw3)
        cal_mobi_ok = calibre_convert(epub_path, cal_mobi)

        if not cal_azw3_ok:
            print(f'  ⚠ Calibre AZW3 conversion failed — skipping comparisons')
            continue

        # ── Convert with our app ──
        page = browser.new_page()
        page.goto(base_url)
        our_azw3_bytes = our_convert(page, epub_path, 'azw3')
        page.goto(base_url)
        our_mobi_bytes = our_convert(page, epub_path, 'mobi')
        page.close()

        if our_azw3_bytes is None:
            test(f'{label}: our AZW3 conversion completes', lambda: False)
            continue

        # Save outputs for inspection
        our_azw3 = epub_path.replace('.epub', '_ours.azw3')
        our_mobi = epub_path.replace('.epub', '_ours.mobi')
        Path(our_azw3).write_bytes(our_azw3_bytes)
        if our_mobi_bytes: Path(our_mobi).write_bytes(our_mobi_bytes)

        # ── AZW3 structural comparison ──
        cal_h = header_fields(cal_azw3)
        our_h = header_fields(our_azw3)

        test(f'{label} AZW3: file_version = 8 (KF8)',
             lambda h=our_h: h['file_version'] == 8)

        test(f'{label} AZW3: compression = 2 (PalmDoc, same as Calibre)',
             lambda ch=cal_h, oh=our_h: oh['compression'] == ch['compression'])

        # We preserve original HTML structure + inline images as base64 (Calibre
        # extracts images as binary records). Known size overhead:
        #   - Image-heavy books: up to 4× Calibre (base64 = +33% over binary)
        #   - Text-only books: 1-1.3× Calibre (structural HTML overhead)
        # Flag only clear bugs (> 6× = likely content duplication).
        test(f'{label} AZW3: text_length not more than 6× Calibre (no duplication)',
             lambda ch=cal_h, oh=our_h: (
                 oh['text_length'] < ch['text_length'] * 6
             ))

        test(f'{label} AZW3: has text content (not empty)',
             lambda oh=our_h: oh['text_length'] > 10000)

        test(f'{label} AZW3: NCX index present (ToC)',
             lambda h=our_h: h['ncx_index'] != 0xffffffff)

        # ── Content comparison ──
        cal_text = strip_markup(extract_text(cal_azw3))
        our_text = strip_markup(extract_text(our_azw3))

        test(f'{label} AZW3: decompressed text is valid UTF-8 (no U+FFFD)',
             lambda t=our_text: '\ufffd' not in t)

        sim = text_similarity(cal_text, our_text)
        test(f'{label} AZW3: text similarity ≥ 85% vs Calibre (got {sim:.0%})',
             lambda s=sim: s >= 0.85)

        # Check no CSS leaked into body text
        test(f'{label} AZW3: no CSS rules in decompressed text',
             lambda t=our_text: not re.search(r'\{[^}]{10,}(display|margin|font)[^}]{0,50}\}', t))

        # ── MOBI v6 comparison ──
        if our_mobi_bytes and cal_mobi_ok:
            cal_mh = header_fields(cal_mobi)
            our_mh = header_fields(our_mobi)

            test(f'{label} MOBI: file_version = 6',
                 lambda h=our_mh: h['file_version'] == 6)

            test(f'{label} MOBI: text_length not more than 6× Calibre',
                 lambda ch=cal_mh, oh=our_mh: (
                     oh['text_length'] < ch['text_length'] * 6
                 ))

            our_mobi_text = strip_markup(extract_text(our_mobi))
            cal_mobi_text = strip_markup(extract_text(cal_mobi))
            mobi_sim = text_similarity(cal_mobi_text, our_mobi_text)

            test(f'{label} MOBI: decompressed text valid UTF-8',
                 lambda t=our_mobi_text: '\ufffd' not in t)

            test(f'{label} MOBI: text similarity ≥ 85% vs Calibre (got {mobi_sim:.0%})',
                 lambda s=mobi_sim: s >= 0.85)

            # Validate with Calibre ebook-meta
            r = subprocess.run(['ebook-meta', our_mobi], capture_output=True, text=True)
            test(f'{label} MOBI: Calibre reads metadata',
                 lambda out=r.stdout: 'Title' in out)

    # ── Synthetic EPUB: precise content verification ──
    print('\n── Synthetic EPUB: precise content verification ─────────────')

    synth = make_epub('Test Boek', [
        ('Hoofdstuk één', '<p aid="1">Vlak voor zijn dood — "Oorlog en terpentijn".</p>'),
        ('Hoofdstuk twee', '<p aid="2">Curly quotes: \u2018hello\u2019 and \u201cworld\u201d.</p>'),
        ('Chapter Three',  '<p aid="3">Em\u2013dash and ellipsis\u2026 test.</p>'),
    ], version='2.0')
    synth_path = '/tmp/synthetic_compare.epub'
    Path(synth_path).write_bytes(synth)
    calibre_convert(synth_path, '/tmp/synthetic_compare_calibre.azw3')

    page = browser.new_page()
    page.goto(base_url)
    our_synth_bytes = our_convert(page, synth_path, 'azw3')
    page.close()

    if our_synth_bytes:
        Path('/tmp/synthetic_compare_ours.azw3').write_bytes(our_synth_bytes)
        our_synth_text = extract_text('/tmp/synthetic_compare_ours.azw3')

        # Exact string checks for non-ASCII characters
        test('Synthetic: Dutch "één" preserved',
             lambda t=our_synth_text: 'één' in t)
        test('Synthetic: em-dash U+2013 preserved',
             lambda t=our_synth_text: '\u2013' in t)
        test('Synthetic: curly quotes U+2018/U+2019 preserved',
             lambda t=our_synth_text: '\u2018' in t and '\u2019' in t)
        test('Synthetic: curly double quotes U+201C/U+201D preserved',
             lambda t=our_synth_text: '\u201c' in t and '\u201d' in t)
        test('Synthetic: ellipsis U+2026 preserved',
             lambda t=our_synth_text: '\u2026' in t)
        test('Synthetic: no replacement chars U+FFFD (compression OK)',
             lambda t=our_synth_text: '\ufffd' not in t)

    browser.close()

httpd.shutdown()

print(f'\n{"═"*60}')
print(f'  {passed} passed  {failed} failed')
if failures:
    print('\nFailed:')
    for name, err in failures:
        print(f'  ✗ {name}'); print(f'    {err}')
print()
sys.exit(1 if failed > 0 else 0)
