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

import struct, subprocess, re, sys, threading, difflib, zipfile
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from epub_fixtures import make_epub, MINIMAL_PNG
from kf8_extract import text_bytes, fdst_flows
import fixtures

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


def extract_text(azw3_path: str, html_only: bool = True) -> str:
    """Decompressed text of an AZW3/MOBI file (trailing entries stripped).

    For KF8 the text is `html + stylesheets`; with html_only (default) only FDST
    flow 0 (the HTML) is returned, so checks about the HTML are not confused by
    the CSS flows. MOBI v6 has no FDST and returns the whole text.
    """
    data = Path(azw3_path).read_bytes()
    flows = fdst_flows(data) if html_only else []
    raw = flows[0] if flows else text_bytes(data)
    return raw.decode('utf-8', errors='replace')


def extract_flows(azw3_path: str) -> list[str]:
    """All FDST flows (flow 0 = HTML, 1..N = CSS) of a KF8 file."""
    return [f.decode('utf-8', errors='replace')
            for f in fdst_flows(Path(azw3_path).read_bytes())]


def epub_has_css(epub_path: str) -> bool:
    """True when the EPUB ships at least one .css file."""
    with zipfile.ZipFile(epub_path) as z:
        return any(n.lower().endswith('.css') for n in z.namelist())


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

# Test EPUBs: fixture books are downloaded once into tests/corpus/fixtures/ (see fixtures.py)
EPUBS = []
for name, label in (('sherlock', 'Sherlock Holmes'), ('frankenstein', 'Frankenstein'),
                    ('pride_prejudice', 'Pride & Prejudice')):
    _fx = fixtures.try_fixture(name, f'Calibre comparison: {label}')
    if _fx:
        EPUBS.append((str(_fx), label, None))

# Also test with local EPUBs if present
local_epubs = list(Path(__file__).parent.parent.glob('*.epub'))
for ep in local_epubs:
    EPUBS.append((str(ep), ep.stem[:40], None))

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    for epub_path, label, _ in EPUBS:
        print(f'\n── {label} ─────────────────────────────────────────────')

        # ── Generate reference with Calibre ──
        cal_azw3 = f'/tmp/{Path(epub_path).stem}_calibre_ref.azw3'
        cal_mobi = f'/tmp/{Path(epub_path).stem}_calibre_ref.mobi'
        cal_azw3_ok = calibre_convert(epub_path, cal_azw3)
        cal_mobi_ok = calibre_convert(epub_path, cal_mobi)

        if not cal_azw3_ok:
            test(f'{label}: Calibre reference conversion succeeds', lambda: False)
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
        our_azw3 = f'/tmp/{Path(epub_path).stem}_ours.azw3'
        our_mobi = f'/tmp/{Path(epub_path).stem}_ours.mobi'
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

        # Check no CSS leaked into the HTML (flow 0 only: CSS lives in flows 1..N)
        test(f'{label} AZW3: no CSS rules in HTML flow (flow 0)',
             lambda t=our_text: not re.search(r'\{[^}]{10,}(display|margin|font)[^}]{0,50}\}', t))

        # CSS must be present as FDST flows: flow 0 = HTML, flow 1.. = stylesheets
        if epub_has_css(epub_path):
            our_flows = extract_flows(our_azw3)
            test(f'{label} AZW3: FDST has >1 flow (EPUB has a stylesheet)',
                 lambda f=our_flows: len(f) > 1)
            test(f'{label} AZW3: flow 1 contains CSS rules',
                 lambda f=our_flows: len(f) > 1 and re.search(r'[^{}]+\{[^{}]*:[^{}]*\}', f[1]) is not None)
            test(f'{label} AZW3: HTML flow links the CSS flow (kindle:flow)',
                 lambda t=extract_text(our_azw3): 'kindle:flow:' in t and 'text/css' in t)

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

            our_mobi_raw = extract_text(our_mobi)
            our_mobi_text = strip_markup(our_mobi_raw)
            cal_mobi_text = strip_markup(extract_text(cal_mobi))
            mobi_sim = text_similarity(cal_mobi_text, our_mobi_text)

            test(f'{label} MOBI: decompressed text valid UTF-8',
                 lambda t=our_mobi_text: '\ufffd' not in t)

            test(f'{label} MOBI: text similarity ≥ 85% vs Calibre (got {mobi_sim:.0%})',
                 lambda s=mobi_sim: s >= 0.85)

            # Critical: MOBI v6 must be a single flat HTML document.
            # Multiple <html> tags cause subsequent <head><style> blocks to
            # appear after </html> and render as visible text on Kindle.
            html_count = our_mobi_raw.count('<html')
            test(f'{label} MOBI: single <html> element (flat HTML, not per-chapter)',
                 lambda c=html_count: c == 1)

            # CSS rules must not appear as visible body text
            test(f'{label} MOBI: no CSS rules in decompressed body text',
                 lambda t=our_mobi_text: not re.search(
                     r'\{[^}]{5,}(display|margin|font|visibility)[^}]{0,50}\}', t))

            # <style> must not appear after the closing </html> tag
            first_close_html = our_mobi_raw.find('</html>')
            test(f'{label} MOBI: no <style> after </html> (CSS not leaking as text)',
                 lambda r=our_mobi_raw, fc=first_close_html: (
                     fc == -1 or '<style' not in r[fc:]))

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
print(f'  {passed} passed  {failed} failed  {fixtures.skip_count()} skipped')
if failures:
    print('\nFailed:')
    for name, err in failures:
        print(f'  ✗ {name}'); print(f'    {err}')
print()
sys.exit(1 if failed > 0 else 0)
