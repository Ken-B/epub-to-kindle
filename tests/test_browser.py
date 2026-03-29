"""
Browser automation tests for the EPUB → AZW3 converter.

Loads the real docs/index.html in headless Chromium via Playwright,
exercising the actual JavaScript: JSZip, parseEpub(), convertToAzw3(),
handleFile(), blob download, and the sw.js service worker.

Run:  uv run tests/test_browser.py

# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""

import io, re, struct, subprocess, sys, threading, time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial

sys.path.insert(0, str(Path(__file__).parent))
from epub_fixtures import make_epub, MINIMAL_PNG

from playwright.sync_api import sync_playwright

# ── Test framework ──────────────────────────────────────────────────────────

passed = 0; failed = 0; failures = []

def test(name, fn):
    global passed, failed
    try:
        result = fn()
        if result is False:
            raise AssertionError('returned False')
        print(f'  ✓ {name}'); passed += 1
    except Exception as e:
        print(f'  ✗ {name}'); print(f'    {e}')
        failed += 1; failures.append((name, str(e)))

# ── HTTP server ──────────────────────────────────────────────────────────────

class SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

def start_server(docs_dir: str) -> tuple[HTTPServer, int]:
    handler = partial(SilentHandler, directory=docs_dir)
    httpd = HTTPServer(('localhost', 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port

# ── Helpers ──────────────────────────────────────────────────────────────────

def upload_and_wait(page, epub_bytes: bytes, filename: str, timeout: int = 20000):
    """Upload an EPUB via the file input and wait for #dlBtn to appear."""
    page.set_input_files('#fileInput', {
        'name': filename,
        'mimeType': 'application/epub+zip',
        'buffer': epub_bytes,
    })
    page.wait_for_selector('#dlBtn', state='visible', timeout=timeout)

def fetch_azw3(page) -> bytes:
    """Extract the AZW3 bytes from the blob URL in #dlBtn."""
    raw = page.evaluate('''async () => {
        const href = document.getElementById('dlBtn').href;
        const r = await fetch(href);
        const ab = await r.arrayBuffer();
        return Array.from(new Uint8Array(ab));
    }''')
    return bytes(raw)

def calibre_meta(path: str) -> str:
    r = subprocess.run(['ebook-meta', path], capture_output=True, text=True)
    return r.stdout + r.stderr

def wait_for_sw(page, timeout_ms=15000):
    """Wait for service worker to be controlling the page."""
    page.wait_for_function(
        '() => navigator.serviceWorker && navigator.serviceWorker.controller !== null',
        timeout=timeout_ms
    )

def extract_azw3_chapters(azw3: bytes) -> list[dict]:
    """Reconstruct HTML chapters from KF8 skeleton+chunk indices."""
    nrec = struct.unpack_from('>H', azw3, 76)[0]
    rec_offsets = [struct.unpack_from('>I', azw3, 78+i*8)[0] for i in range(nrec)]
    r0 = rec_offsets[0]
    num_text = struct.unpack_from('>H', azw3, r0+8)[0]
    skel_idx  = struct.unpack_from('>I', azw3, r0+252)[0]
    chunk_idx = struct.unpack_from('>I', azw3, r0+248)[0]
    if skel_idx == 0xffffffff:
        return []

    text_bytes = b''
    for i in range(1, num_text+1):
        s = rec_offsets[i]; e = rec_offsets[i+1] if i+1 < nrec else len(azw3)
        text_bytes += azw3[s:e-1]
    text = text_bytes.decode('utf-8', errors='replace')

    def vwi(data, pos):
        val = consumed = 0
        for i in range(pos, len(data)):
            b = data[i]; val = (val << 7) | (b & 0x7f); consumed += 1
            if b & 0x80: break
        return val, consumed

    def entries(rec_off):
        io2 = struct.unpack_from('>I', azw3, rec_off+20)[0]
        n   = struct.unpack_from('>I', azw3, rec_off+24)[0]
        out = []
        for j in range(n):
            eo = struct.unpack_from('>H', azw3, rec_off+io2+4+j*2)[0]
            p  = rec_off + eo; kl = azw3[p]
            key = azw3[p+1:p+1+kl].decode('utf-8','replace')
            out.append({'key': key, 'ds': p+1+kl})
        return out

    skels_raw = entries(rec_offsets[skel_idx+1])
    skels = []
    for e in skels_raw:
        ctrl = azw3[e['ds']]; pos = e['ds']+1
        cc = []; geom = []
        for _ in range(ctrl & 3):
            v,c = vwi(azw3,pos); cc.append(v); pos+=c
        for _ in range(((ctrl&12)>>2)*2):
            v,c = vwi(azw3,pos); geom.append(v); pos+=c
        skels.append({'cc': cc[0] if cc else 1,
                      'start': geom[0] if geom else 0,
                      'len':   geom[1] if len(geom)>1 else 0})

    num_chunk_dr = struct.unpack_from('>I', azw3, rec_offsets[chunk_idx]+24)[0]
    chunks_raw = []
    for dr in range(num_chunk_dr):
        chunks_raw.extend(entries(rec_offsets[chunk_idx+1+dr]))
    chunks = []
    for e in chunks_raw:
        ctrl = azw3[e['ds']]; pos = e['ds']+1; r = {'ins': int(e['key'])}
        if ctrl & 1: v,c=vwi(azw3,pos); r['cncx']=v; pos+=c
        if ctrl & 2: v,c=vwi(azw3,pos); r['fn']=v;   pos+=c
        if ctrl & 4: v,c=vwi(azw3,pos); r['sn']=v;   pos+=c
        if ctrl & 8:
            s,c=vwi(azw3,pos); pos+=c; l,c=vwi(azw3,pos); pos+=c
            r['start']=s; r['len']=l
        chunks.append(r)

    result = []; cp = 0
    for sk in skels:
        skel_html = text[sk['start']:sk['start']+sk['len']]
        html = skel_html
        for _ in range(sk['cc']):
            if cp >= len(chunks): break
            ch = chunks[cp]; cp += 1
            li = ch['ins'] - sk['start']
            content = text[ch.get('start', sk['start']+sk['len']):
                           ch.get('start', sk['start']+sk['len']) + ch.get('len', 0)]
            html = html[:li] + content + html[li:]
        body_text = re.sub(r'<[^>]+>', '', html).strip()
        if len(body_text) > 30:
            result.append({'html': html, 'body_text': body_text})
    return result

# ── Main ─────────────────────────────────────────────────────────────────────

docs_dir = str(Path(__file__).parent.parent / 'docs')
httpd, port = start_server(docs_dir)
base_url = f'http://localhost:{port}'
print(f'Server: {base_url}  (docs: {docs_dir})')

ALICE = Path('/tmp/alice_images.epub')

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # ── T1: Page loads ─────────────────────────────────────────────────────
    print('\n── T1: Page loads ─────────────────────────────────────────────')
    js_errors = []
    page = browser.new_page()
    page.on('pageerror', lambda e: js_errors.append(str(e)))
    page.goto(base_url)
    page.wait_for_load_state('domcontentloaded')

    test('Page title = "EPUB → AZW3 Converter"',
         lambda: page.title() == 'EPUB → AZW3 Converter')
    test('#fileInput accepts .epub',
         lambda: page.get_attribute('#fileInput', 'accept') == '.epub')
    test('#dlBtn is initially hidden',
         lambda: page.evaluate('() => document.getElementById("dlBtn").style.display') == 'none')
    test('Version shown in footer',
         lambda: bool(re.search(r'v\d+\.\d+\.\d+', page.inner_text('footer'))))
    test('No JS errors on load',
         lambda: len(js_errors) == 0)
    page.close()

    # ── T2: Basic conversion (Alice EPUB 2) ────────────────────────────────
    print('\n── T2: Basic conversion (Alice EPUB 2) ────────────────────────')
    if not ALICE.exists():
        print('  ⚠ skip (alice_images.epub not found at /tmp/)')
    else:
        page = browser.new_page()
        page.goto(base_url)
        upload_and_wait(page, ALICE.read_bytes(), 'alice_images.epub')

        test('Status class is "ok" after conversion',
             lambda: 'ok' in (page.get_attribute('#status', 'class') or ''))
        test('Status text mentions chapter count',
             lambda: 'chapter' in page.inner_text('#status').lower())
        test('#dlBtn download attr ends with .azw3',
             lambda: (page.get_attribute('#dlBtn', 'download') or '').endswith('.azw3'))

        azw3 = fetch_azw3(page)
        test('AZW3 blob is >1 KB',    lambda: len(azw3) > 1000)
        test('PDB magic = BOOKMOBI',  lambda: azw3[60:68] == b'BOOKMOBI')
        test('MOBI ident present',    lambda: b'MOBI' in azw3[76:76+8192])

        tmp = '/tmp/browser_alice.azw3'
        Path(tmp).write_bytes(azw3)
        test('Calibre reads title',
             lambda: 'alice' in calibre_meta(tmp).lower())
        test('Calibre TXT conversion succeeds',
             lambda: subprocess.run(['ebook-convert', tmp, '/tmp/browser_alice.txt'],
                                    capture_output=True, timeout=60).returncode == 0)
        page.close()

    # ── T3: Full user journey ──────────────────────────────────────────────
    print('\n── T3: Full user journey ──────────────────────────────────────')
    epub = make_epub('Journey Test', [
        ('Chapter 1', '<p aid="1">Hello world, this is the first chapter of the journey test.</p>'),
        ('Chapter 2', '<p aid="2">Second chapter content. The converter should handle this.</p>'),
    ])
    page = browser.new_page()
    page.goto(base_url)

    test('Before upload: #status is hidden',
         lambda: page.evaluate(
             '() => document.getElementById("status").style.display') == 'none' or
             page.evaluate('() => getComputedStyle(document.getElementById("status")).display') == 'none')

    page.set_input_files('#fileInput', {
        'name': 'journey.epub', 'mimeType': 'application/epub+zip', 'buffer': epub,
    })
    page.wait_for_selector('#dlBtn', state='visible', timeout=20000)

    test('#dlBtn is visible after conversion',
         lambda: page.is_visible('#dlBtn'))
    test('#dlBtn href is a blob: URL',
         lambda: (page.get_attribute('#dlBtn', 'href') or '').startswith('blob:'))
    test('Status class is "ok"',
         lambda: 'ok' in (page.get_attribute('#status', 'class') or ''))
    test('Status text contains book title',
         lambda: 'Journey Test' in page.inner_text('#status'))
    test('Status text shows 2 chapters',
         lambda: '2 chapter' in page.inner_text('#status').lower())
    page.close()

    # ── T4: Image rendering ────────────────────────────────────────────────
    print('\n── T4: Image rendering ────────────────────────────────────────')
    epub_img = make_epub('Image Test', [
        ('Chapter with Image', '<p aid="1">This chapter has a test image above.</p>'),
    ], images=[('test.png', MINIMAL_PNG)])

    page = browser.new_page()
    page.goto(base_url)
    upload_and_wait(page, epub_img, 'image_test.epub')
    azw3_img = fetch_azw3(page)
    page.close()

    test('AZW3 binary contains data:image/png',
         lambda: b'data:image/png;base64,' in azw3_img)

    chapters = extract_azw3_chapters(azw3_img)
    img_chapters = [c for c in chapters if '<img' in c['html']]
    if not img_chapters:
        print('  ⚠ could not extract chapter with <img> for rendering test')
    else:
        img_page = browser.new_page()
        img_page.set_content(img_chapters[0]['html'], wait_until='domcontentloaded')
        img_page.wait_for_function(
            '() => { const img = document.querySelector("img"); '
            'return !img || img.complete; }',
            timeout=5000
        )
        test('Rendered img naturalWidth > 0 (not broken)',
             lambda: img_page.evaluate(
                 '() => document.querySelector("img")?.naturalWidth ?? 0') > 0)
        test('Rendered img src is a data: URI',
             lambda: (img_page.evaluate(
                 '() => document.querySelector("img")?.src ?? ""')).startswith('data:'))
        img_page.screenshot(path='/tmp/browser_img_chapter.png')
        img_page.close()

    # ── T5: EPUB 3 ────────────────────────────────────────────────────────
    print('\n── T5: EPUB 3 ─────────────────────────────────────────────────')
    epub3 = make_epub('EPUB3 Test Book', [
        ('Chapter One',   '<p aid="1">First chapter of an EPUB 3.0 book.</p>'),
        ('Chapter Two',   '<p aid="2">Second chapter with more content here.</p>'),
        ('Chapter Three', '<p aid="3">Third and final test chapter.</p>'),
    ], version='3.0')

    page = browser.new_page()
    page.goto(base_url)
    page.set_input_files('#fileInput', {
        'name': 'epub3test.epub', 'mimeType': 'application/epub+zip', 'buffer': epub3,
    })
    page.wait_for_function(
        '() => { const s = document.getElementById("status"); '
        'return s && s.style.display !== "none" && '
        '(s.className.includes("ok") || s.className.includes("error")); }',
        timeout=20000
    )

    test('EPUB 3 conversion succeeds (no error)',
         lambda: 'error' not in (page.get_attribute('#status', 'class') or ''))
    test('EPUB 3 status shows 3 chapters',
         lambda: '3 chapter' in page.inner_text('#status').lower())

    azw3_3 = fetch_azw3(page)
    test('EPUB 3 AZW3 output > 1 KB', lambda: len(azw3_3) > 1000)

    tmp3 = '/tmp/browser_epub3.azw3'
    Path(tmp3).write_bytes(azw3_3)
    test('EPUB 3 title in Calibre metadata',
         lambda: 'epub3' in calibre_meta(tmp3).lower())
    page.close()

    # ── T6: Error cases ────────────────────────────────────────────────────
    print('\n── T6: Error cases ────────────────────────────────────────────')

    def wait_for_error(page, timeout=10000):
        page.wait_for_function(
            '() => document.getElementById("status").className.includes("error")',
            timeout=timeout
        )

    # T6a: Wrong file extension
    page = browser.new_page()
    page.goto(base_url)
    page.set_input_files('#fileInput', {
        'name': 'document.pdf', 'mimeType': 'application/pdf',
        'buffer': b'%PDF-1.4 fake content',
    })
    # Status updates synchronously for wrong extension — no need to wait long
    page.wait_for_function(
        '() => document.getElementById("status").style.display !== "none"',
        timeout=3000
    )
    test('Non-EPUB: status class is "error"',
         lambda: 'error' in (page.get_attribute('#status', 'class') or ''))
    test('Non-EPUB: error text mentions .epub',
         lambda: 'epub' in page.inner_text('#status').lower())
    test('Non-EPUB: #dlBtn remains hidden',
         lambda: not page.is_visible('#dlBtn'))
    page.close()

    # T6b: Empty file
    page = browser.new_page()
    page.goto(base_url)
    page.set_input_files('#fileInput', {
        'name': 'empty.epub', 'mimeType': 'application/epub+zip', 'buffer': b'',
    })
    wait_for_error(page)
    test('Empty EPUB: status class is "error"',
         lambda: 'error' in (page.get_attribute('#status', 'class') or ''))
    test('Empty EPUB: #dlBtn remains hidden',
         lambda: not page.is_visible('#dlBtn'))
    page.close()

    # T6c: Valid ZIP but missing container.xml
    bad_epub = io.BytesIO()
    import zipfile as zf
    with zf.ZipFile(bad_epub, 'w') as z:
        z.writestr('not-an-epub.txt', 'this is not an epub')
    page = browser.new_page()
    page.goto(base_url)
    page.set_input_files('#fileInput', {
        'name': 'bad.epub', 'mimeType': 'application/epub+zip',
        'buffer': bad_epub.getvalue(),
    })
    wait_for_error(page)
    test('Malformed EPUB (no container.xml): status is "error"',
         lambda: 'error' in (page.get_attribute('#status', 'class') or ''))
    page.close()

    # T6d: EPUB with empty spine → 0 chapters, but should not crash
    buf = io.BytesIO()
    with zf.ZipFile(buf, 'w') as z:
        mi = zf.ZipInfo('mimetype'); mi.compress_type = zf.ZIP_STORED
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
    <dc:title>Empty Spine Test</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="uid">uid-001</dc:identifier>
  </metadata>
  <manifest/>
  <spine/>
</package>''')
    empty_spine_epub = buf.getvalue()
    page = browser.new_page()
    page.goto(base_url)
    page.set_input_files('#fileInput', {
        'name': 'no_chapters.epub', 'mimeType': 'application/epub+zip',
        'buffer': empty_spine_epub,
    })
    # May succeed with 0 chapters or show an error — either is acceptable,
    # but it must NOT leave the page in a broken/hung state
    page.wait_for_function(
        '() => { const s = document.getElementById("status"); '
        'return s && s.style.display !== "none"; }',
        timeout=15000
    )
    test('Empty spine: page handles gracefully (ok or error, not hung)',
         lambda: bool(page.get_attribute('#status', 'class')))
    page.close()

    # ── T7: CSS visibility ─────────────────────────────────────────────────
    print('\n── T7: CSS visibility ─────────────────────────────────────────')
    epub_css = make_epub('CSS Visibility Test', [
        ('Chapter 1',
         '<div class="publisher-watermark">SECRET WATERMARK TEXT</div>'
         '<p aid="1">Normal readable content here.</p>'),
    ], css_rules=[
        ('.publisher-watermark', 'display: none'),
        ('.normal', 'color: black'),  # should NOT be included in AZW3
    ])

    page = browser.new_page()
    page.goto(base_url)
    upload_and_wait(page, epub_css, 'csstest.epub')
    azw3_css = fetch_azw3(page)
    page.close()

    test('AZW3 contains display:none rule',
         lambda: b'display: none' in azw3_css or b'display:none' in azw3_css)
    test('AZW3 does NOT contain non-visibility CSS (.normal color rule)',
         lambda: b'color: black' not in azw3_css)

    css_chapters = extract_azw3_chapters(azw3_css)
    if css_chapters:
        css_page = browser.new_page()
        css_page.set_content(css_chapters[0]['html'], wait_until='domcontentloaded')

        test('Watermark div is hidden (display:none applied)',
             lambda: css_page.evaluate(
                 '() => getComputedStyle(document.querySelector(".publisher-watermark") '
                 '|| document.body).display') == 'none')
        test('Watermark text not visible in innerText',
             lambda: 'SECRET WATERMARK TEXT' not in css_page.evaluate(
                 '() => document.body.innerText'))
        test('Normal content IS readable',
             lambda: 'Normal readable content' in css_page.evaluate(
                 '() => document.body.innerText'))
        css_page.close()

    # ── T8: Offline / PWA ─────────────────────────────────────────────────
    print('\n── T8: Offline / service worker ───────────────────────────────')
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(base_url)
    page.wait_for_load_state('load')

    # Wait for SW to install and take control (skipWaiting + clients.claim)
    try:
        page.wait_for_function(
            '() => !!navigator.serviceWorker && navigator.serviceWorker.controller !== null',
            timeout=15000
        )
        sw_works = True
    except Exception:
        sw_works = False
        print('  ⚠ Service worker did not activate — skipping offline tests')

    if sw_works:
        test('Service worker is registered and controlling the page',
             lambda: page.evaluate(
                 '() => navigator.serviceWorker.controller !== null'))
        test('SW cache key starts with "epub2azw3-"',
             lambda: page.evaluate(
                 '() => caches.keys().then(keys => '
                 'keys.some(k => k.startsWith("epub2azw3-")))'))

        # Go offline and reload in a new page within the same context
        ctx.set_offline(True)
        page2 = ctx.new_page()
        try:
            page2.goto(base_url, timeout=10000)
            page2.wait_for_load_state('domcontentloaded', timeout=10000)
            test('Page loads from SW cache when offline',
                 lambda: page2.title() == 'EPUB → AZW3 Converter')
            test('JSZip loaded from cache when offline',
                 lambda: page2.evaluate('() => typeof JSZip !== "undefined"'))

            # Try a conversion while offline
            epub_offline = make_epub('Offline Test', [
                ('Only Chapter', '<p aid="1">Testing that conversion works offline.</p>'),
            ])
            page2.set_input_files('#fileInput', {
                'name': 'offline.epub', 'mimeType': 'application/epub+zip',
                'buffer': epub_offline,
            })
            page2.wait_for_selector('#dlBtn', state='visible', timeout=20000)
            test('Full conversion works offline (SW served all assets)',
                 lambda: 'ok' in (page2.get_attribute('#status', 'class') or ''))
        finally:
            ctx.set_offline(False)
            page2.close()

    page.close()
    ctx.close()

    # ── T9: Real-world EPUB (optional, local only) ────────────────────────────
    # Tests any *.epub files found next to the project root.
    # These are .gitignored (copyrighted), so they only run locally.
    # They exercise the full pipeline on real-world complex books and verify:
    # - No JS errors during conversion
    # - Output is valid AZW3 (Calibre reads it)
    # - Text decodes as clean UTF-8 (no garbled compression)
    # - No CSS leakage in the rendered chapters

    import glob
    local_epubs = sorted(glob.glob(str(Path(docs_dir).parent / '*.epub')))
    if local_epubs:
        print('\n── T9: Real-world EPUBs (local only) ──────────────────────────')
        for epub_path in local_epubs:
            epub_name = Path(epub_path).name
            label = epub_name.replace('.epub', '')[:50]
            print(f'\n  Testing: {label}')

            page = browser.new_page()
            js_errs = []
            page.on('pageerror', lambda e: js_errs.append(str(e)))
            page.goto(base_url)

            page.set_input_files('#fileInput', {
                'name': epub_name,
                'mimeType': 'application/epub+zip',
                'buffer': Path(epub_path).read_bytes(),
            })

            try:
                page.wait_for_function(
                    '() => { const s=document.getElementById("status"); '
                    'return s && s.style.display!=="none" && '
                    '(s.className.includes("ok")||s.className.includes("error")); }',
                    timeout=120000
                )
            except Exception as e:
                test(f'{label}: conversion completes', lambda: (_ for _ in ()).throw(AssertionError(f'Timeout: {e}')))
                page.close(); continue

            status_cls = page.get_attribute('#status', 'class') or ''
            status_txt = page.inner_text('#status')

            test(f'{label}: no JS errors', lambda je=js_errs: len(je) == 0)
            test(f'{label}: conversion succeeds (no error status)',
                 lambda sc=status_cls: 'error' not in sc)

            if 'error' not in status_cls:
                azw3 = fetch_azw3(page)

                # Save for Calibre validation
                tmp_azw3 = f'/tmp/realworld_{Path(epub_path).stem}.azw3'
                Path(tmp_azw3).write_bytes(azw3)

                test(f'{label}: AZW3 > 1KB', lambda a=azw3: len(a) > 1000)
                test(f'{label}: PDB magic BOOKMOBI', lambda a=azw3: a[60:68] == b'BOOKMOBI')
                test(f'{label}: Calibre reads metadata',
                     lambda p=tmp_azw3: 'Title' in calibre_meta(p))

                # Decompress and verify first chapter text is valid UTF-8 (not garbled)
                def check_utf8_clean(a=azw3):
                    nrec = struct.unpack_from('>H', a, 76)[0]
                    recs = [struct.unpack_from('>I', a, 78+i*8)[0] for i in range(nrec)]
                    r0 = recs[0]
                    compression = struct.unpack_from('>H', a, r0)[0]
                    num_text = struct.unpack_from('>H', a, r0+8)[0]

                    def palmdoc_decompress(data):
                        out = bytearray(); i = 0
                        while i < len(data):
                            b = data[i]; i += 1
                            if b == 0: out.append(0)
                            elif b <= 8:
                                for _ in range(b): out.append(data[i]); i += 1
                            elif b <= 0x7F: out.append(b)
                            elif b <= 0xBF:
                                b2=data[i]; i+=1; dist=((b&0x3F)<<5)|(b2>>3); ln=(b2&7)+3
                                for _ in range(ln): out.append(out[-dist] if dist<=len(out) else 0)
                            else: out.append(0x20); out.append(b&0x7F)
                        return bytes(out)

                    # Decode first 3 text records
                    sample = b''
                    for idx in range(1, min(4, num_text+1)):
                        s=recs[idx]; e=recs[idx+1] if idx+1<nrec else len(a)
                        rec = a[s:e-1]
                        if compression == 2:
                            rec = palmdoc_decompress(rec)
                        sample += rec

                    # Must decode as valid UTF-8 with no replacement chars
                    decoded = sample.decode('utf-8')  # raises if invalid
                    assert '\ufffd' not in decoded, \
                        f'Replacement chars (U+FFFD) in decoded text — compression bug!'
                    # Must look like HTML (starts with <html or similar)
                    assert '<' in decoded[:200], 'No HTML tags in decoded text'

                test(f'{label}: decompressed text is valid UTF-8 (no garbled chars)',
                     check_utf8_clean)

                # Screenshot first prose chapter (reuse the open browser)
                chapters = extract_azw3_chapters(azw3)
                if chapters:
                    def check_no_css_leak(chs=chapters, lbl=label, br=browser, stem=Path(epub_path).stem):
                        issues = []
                        for i, ch in enumerate(chs[:3]):
                            _pg = br.new_page()
                            _pg.set_content(ch['html'], wait_until='domcontentloaded')
                            body_text = _pg.evaluate('() => document.body?.innerText || ""')
                            if re.search(r'\{[^}]{5,}(display|margin|font)[^}]{0,50}\}', body_text):
                                issues.append(f'ch{i}: CSS rules visible as body text')
                            if '<?xml' in body_text or 'encoding="UTF-8"' in body_text:
                                issues.append(f'ch{i}: XML declaration visible')
                            _pg.screenshot(path=f'/tmp/realworld_{stem}_ch{i:02d}.png', full_page=False)
                            _pg.close()
                        if issues:
                            raise AssertionError('; '.join(issues))
                    test(f'{label}: no CSS/XML leakage in rendered chapters', check_no_css_leak)

            page.close()

    browser.close()

        # ── Mobile & cross-browser tests ──────────────────────────────────────────
    #
    # Playwright supports three engines: Chromium, Firefox, WebKit (Safari).
    # WebKit is the closest approximation to iOS Safari without real hardware.
    # Mobile emulation (viewport + touch + UA) catches layout/rendering issues.

    print('\n── T10: WebKit (Safari engine) ────────────────────────────────')

    try:
        webkit = pw.webkit.launch()
        epub_for_webkit = make_epub('WebKit Test', [
            ('Chapter 1', '<p aid="1">Testing the converter on Safari/WebKit engine.</p>'),
            ('Chapter 2', '<p aid="2">Second chapter to verify multi-chapter support.</p>'),
        ])

        wk_page = webkit.new_page()
        wk_js_errors = []
        wk_page.on('pageerror', lambda e: wk_js_errors.append(str(e)))
        wk_page.goto(base_url)
        wk_page.wait_for_load_state('domcontentloaded')

        test('WebKit: page loads without JS errors',
             lambda: len(wk_js_errors) == 0)
        test('WebKit: page title correct',
             lambda: wk_page.title() == 'EPUB → AZW3 Converter')

        wk_page.set_input_files('#fileInput', {
            'name': 'webkit_test.epub', 'mimeType': 'application/epub+zip',
            'buffer': epub_for_webkit,
        })
        wk_page.wait_for_selector('#dlBtn', state='visible', timeout=30000)

        test('WebKit: conversion succeeds',
             lambda: 'ok' in (wk_page.get_attribute('#status', 'class') or ''))
        test('WebKit: status shows 2 chapters',
             lambda: '2 chapter' in wk_page.inner_text('#status').lower())

        wk_azw3 = fetch_azw3(wk_page)
        test('WebKit: AZW3 output is valid (BOOKMOBI magic)',
             lambda: wk_azw3[60:68] == b'BOOKMOBI')

        wk_page.close()
        webkit.close()

    except Exception as e:
        print(f'  ⚠ WebKit tests skipped: {e}')

    print('\n── T11: Mobile viewport (iPhone 15 emulation) ─────────────────')

    IPHONE_15 = {
        'viewport': {'width': 393, 'height': 852},
        'user_agent': (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        ),
        'is_mobile': True,
        'has_touch': True,
        'device_scale_factor': 3,
    }

    mobile_browser = pw.chromium.launch()
    mobile_ctx = mobile_browser.new_context(**IPHONE_15)
    mobile_page = mobile_ctx.new_page()
    mobile_js_errors = []
    mobile_page.on('pageerror', lambda e: mobile_js_errors.append(str(e)))
    mobile_page.goto(base_url)
    mobile_page.wait_for_load_state('domcontentloaded')

    test('iPhone: page loads without JS errors',
         lambda: len(mobile_js_errors) == 0)
    test('iPhone: drop zone is visible and tappable',
         lambda: mobile_page.is_visible('#drop'))
    test('iPhone: page fits within 393px width (no horizontal scroll)',
         lambda: mobile_page.evaluate(
             '() => document.documentElement.scrollWidth <= 393'))

    # Test conversion on mobile viewport
    epub_mobile = make_epub('Mobile Test', [
        ('Chapter', '<p aid="1">Testing conversion on mobile viewport.</p>'),
    ])
    mobile_page.set_input_files('#fileInput', {
        'name': 'mobile.epub', 'mimeType': 'application/epub+zip',
        'buffer': epub_mobile,
    })
    mobile_page.wait_for_selector('#dlBtn', state='visible', timeout=20000)

    test('iPhone: conversion completes successfully',
         lambda: 'ok' in (mobile_page.get_attribute('#status', 'class') or ''))
    test('iPhone: download button is visible and reachable',
         lambda: mobile_page.is_visible('#dlBtn'))

    mobile_page.screenshot(path='/tmp/mobile_iphone_screenshot.png')
    mobile_page.close()
    mobile_ctx.close()
    mobile_browser.close()

    print('\n── T12: iOS-specific error handling ────────────────────────────')

    # Simulate the iCloud "not downloaded" scenario: file with 0 bytes
    # This reproduces the exact error seen on the user's iPhone screenshot.
    err_browser = pw.chromium.launch()
    err_page = err_browser.new_page()
    err_page.goto(base_url)

    err_page.set_input_files('#fileInput', {
        'name': 'not_downloaded.epub',
        'mimeType': 'application/epub+zip',
        'buffer': b'',  # 0 bytes — simulates iCloud placeholder
    })
    err_page.wait_for_function(
        '() => document.getElementById("status").className.includes("error")',
        timeout=5000
    )
    test('iCloud empty file: shows friendly error (not raw JSZip message)',
         lambda: 'central directory' not in err_page.inner_text('#status').lower())
    test('iCloud empty file: error mentions iCloud or download',
         lambda: any(kw in err_page.inner_text('#status').lower()
                     for kw in ['icloud', 'download', 'empty']))
    test('iCloud empty file: download button stays hidden',
         lambda: not err_page.is_visible('#dlBtn'))

    # Simulate truncated/corrupt EPUB (non-ZIP bytes)
    err_page2 = err_browser.new_page()
    err_page2.goto(base_url)
    err_page2.set_input_files('#fileInput', {
        'name': 'corrupt.epub',
        'mimeType': 'application/epub+zip',
        'buffer': b'This is not a ZIP file but has .epub extension ' * 3,
    })
    err_page2.wait_for_function(
        '() => document.getElementById("status").className.includes("error")',
        timeout=10000
    )
    test('Corrupt file: shows friendly error (not raw JSZip message)',
         lambda: 'central directory' not in err_page2.inner_text('#status').lower())
    test('Corrupt file: error mentions download or iCloud or not valid',
         lambda: any(kw in err_page2.inner_text('#status').lower()
                     for kw in ['icloud', 'download', 'valid', 'read', 'error']))

    err_browser.close()

# ── Cleanup ──────────────────────────────────────────────────────────────────

httpd.shutdown()

# ── Results ──────────────────────────────────────────────────────────────────

print(f'\n{"═"*60}')
print(f'  {passed} passed  {failed} failed')
if failures:
    print('\nFailed:')
    for name, err in failures:
        print(f'  ✗ {name}'); print(f'    {err}')
print()
sys.exit(1 if failed > 0 else 0)
