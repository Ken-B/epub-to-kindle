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
from kf8_extract import text_bytes as kf8_text_bytes, fdst_flows as kf8_fdst_flows

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

    # Decompressed text with each record's trailing entry stripped. Skeleton/chunk
    # offsets index flow 0 (the HTML), which is the start of the text, so use it as is.
    text = kf8_text_bytes(azw3).decode('utf-8', errors='replace')

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

def extract_azw3_flows(azw3: bytes) -> list[str]:
    """Split the KF8 text into flows using the FDST table (flow 0 = HTML, 1..N = CSS)."""
    return [f.decode('utf-8', errors='replace') for f in kf8_fdst_flows(azw3)]

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

    # Images are now binary resource records, NOT base64 in text.
    # Verify: raw PNG bytes in the binary (not base64), and kindle:embed: in HTML.
    test('AZW3 binary contains raw PNG bytes (binary resource record)',
         lambda: MINIMAL_PNG[:4] in azw3_img)  # PNG magic: 89 50 4E 47
    test('AZW3 binary does NOT contain base64-encoded image in text records',
         lambda: b'data:image/png;base64,' not in azw3_img)

    chapters = extract_azw3_chapters(azw3_img)
    img_chapters = [c for c in chapters if '<img' in c['html']]
    if not img_chapters:
        print('  ⚠ could not extract chapter with <img> for rendering test')
    else:
        test('Extracted chapter contains kindle:embed: image reference',
             lambda: 'kindle:embed:' in img_chapters[0]['html'])
        # kindle:embed: URLs can't render in a browser, but we can verify
        # the reference format is correct (4-char base-32, 1-indexed)
        import re
        embed_refs = re.findall(r'kindle:embed:([0-9A-Z]{4})', img_chapters[0]['html'])
        test('kindle:embed reference is 4-char base-32',
             lambda: len(embed_refs) > 0 and all(len(r) == 4 for r in embed_refs))
        test('kindle:embed starts at 0001 (1-indexed)',
             lambda: '0001' in embed_refs or any(r != '0000' for r in embed_refs))

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

    # T6b: Corrupt file (> 500 bytes → no auto-retry, fails fast)
    page = browser.new_page()
    page.goto(base_url)
    page.set_input_files('#fileInput', {
        # Use >500 bytes so it takes the fast "no retry" code path
        'name': 'corrupt.epub', 'mimeType': 'application/epub+zip',
        'buffer': b'This is not a valid ZIP file at all.' * 20,
    })
    wait_for_error(page)
    test('Corrupt EPUB: status class is "error"',
         lambda: 'error' in (page.get_attribute('#status', 'class') or ''))
    test('Corrupt EPUB: #dlBtn remains hidden',
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

    # ── T7: CSS visibility (author mode) ───────────────────────────────────
    # ?css=author: the author stylesheets verbatim as KF8 flows (the default, the Kindle
    # profile, bakes them into generated classes: T7b)
    print('\n── T7: CSS visibility (author mode, ?css=author) ──────────────')
    epub_css = make_epub('CSS Visibility Test', [
        ('Chapter 1',
         '<div class="publisher-watermark">SECRET WATERMARK TEXT</div>'
         '<p aid="1">Normal readable content here.</p>'),
    ], css_rules=[
        ('.publisher-watermark', 'display: none'),
        ('.normal', 'color: black'),  # kept verbatim in the CSS flow
    ])

    page = browser.new_page()
    page.goto(base_url + '/?css=author')
    upload_and_wait(page, epub_css, 'csstest.epub')
    azw3_css = fetch_azw3(page)
    page.close()

    # CSS is preserved as KF8 flows: flow 0 = HTML, flow 1..N = stylesheets, linked from
    # the skeleton <head> via kindle:flow:NNNN. (Readers resolve the link; the extractor
    # below does not, so for rendering we inline the flow CSS ourselves.)
    flows = extract_azw3_flows(azw3_css)
    test('AZW3 contains display:none rule',
         lambda: b'display: none' in azw3_css or b'display:none' in azw3_css)
    test('FDST has more than one flow (HTML + stylesheet)',
         lambda: len(flows) > 1)
    test('Flow 1 (after the HTML flow) contains the author CSS rules',
         lambda: len(flows) > 1
                 and '.publisher-watermark' in flows[1]
                 and re.search(r'display:\s*none', flows[1]) is not None
                 and re.search(r'color:\s*black', flows[1]) is not None)
    test('HTML flow does not carry the stylesheet text',
         lambda: len(flows) > 1 and 'color: black' not in flows[0])

    css_chapters = extract_azw3_chapters(azw3_css)
    test('Skeleton head links the CSS flow (kindle:flow:0001?mime=text/css)',
         lambda: bool(css_chapters) and re.search(
             r'<link[^>]*href="kindle:flow:0001\?mime=text/css"', css_chapters[0]['html']) is not None)
    if css_chapters and len(flows) > 1:
        # Resolve kindle:flow links the way a Kindle would: inline the flow CSS
        rendered = re.sub(
            r'<link[^>]*href="kindle:flow:0001\?mime=text/css"[^>]*/?>',
            lambda m: '<style type="text/css">' + flows[1] + '</style>',
            css_chapters[0]['html'])
        css_page = browser.new_page()
        css_page.set_content(rendered, wait_until='domcontentloaded')

        test('Watermark div is hidden (display:none applied from flow CSS)',
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

    # ── T7b: Kindle profile (default KF8 CSS mode) ─────────────────────────
    print('\n── T7b: Kindle profile (KF8 CSS normalisation) ────────────────')
    kp_epub = make_epub('Kindle Profile Test', [
        ('One', '<h2 id="t1">Title</h2>\n'
                '<p>First   para\n   after the title.</p>\n'
                '<p class="noind">&#160;&#160;&#160;Indented by nbsp.</p>\n'
                '<p class="scr imp">Screen <i>red</i> <b>bold</b> text<br/></p>\n'
                '<p></p>\n<p class="keep1">&#160;</p>\n<p class="keep2"><br/></p>\n'
                '<p class="small">Small print.</p>\n'
                '<div class="calc">Calc fallback</div>\n'
                '<p class="pos">Positioned and floated.</p>\n'
                '<p><span class="dropcap">D</span>rop cap.</p>\n'
                '<div class="hidden">HIDDEN</div>\n'
                '<pre>  keep   this\n   spacing</pre>\n'
                '<p>Line one<br/>\n   &#160;&#160;verse indent</p>\n'
                '<p><a href="chapter02.xhtml#target">to the target</a> and <a href="#t1">back</a></p>'),
        ('Two', '<p>Some text.</p>\n<p id="target">Target paragraph.</p>\n<p>After.</p>'),
    ], css_rules=[
        ('body', 'margin: 0 5%; padding: 0 1em; line-height: 1'),
        ('p', 'text-indent: 1.5em; margin: 0'),
        ('h2 + p', 'text-indent: 0'),
        ('.noind', 'text-indent: 0'),
        ('@media screen { .scr', 'color: red } }'),
        ('@media amzn-mobi { .scr', 'color: blue } }'),
        ('.imp', 'font-weight: bold !important'),
        ('p.imp', 'font-weight: normal'),
        ('.small', 'font-size: 12px'),
        ('.calc', 'width: 50%; width: calc(100% - 2em)'),
        ('.pos', 'position: relative; top: 2px; float: left'),
        ('span.dropcap', 'float: left; font-size: 24pt'),
        ('.hidden', 'display: none'),
    ])
    import base64, json
    page = browser.new_page()
    kp_console = []
    page.on('console', lambda m: kp_console.append(f'{m.type}: {m.text}'))
    page.goto(base_url)
    kp = page.evaluate('''async (b64) => {
        const buf = Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer;
        const e = await parseEpub(buf, {mobi: false, kf8: true});
        const sheet = e.stylesheets[0];
        const ch = e.chapters[0].content, head = e.chapters[0].skelHead;
        // declarations of the generated class(es) of the first element matching a start-tag regex
        const decls = re => {
            const m = new RegExp(re).exec(ch);
            const cls = m && /\sclass="([^"]*)"/.exec(m[0]);
            if (!cls) return null;
            return cls[1].split(' ').map(c => (new RegExp('\\.' + c + '\\{([^}]*)\\}').exec(sheet) || [])[1] || '').join(';');
        };
        const bodyCls = /<body[^>]*\sclass="([^"]*)"/.exec(head)?.[1];
        const bodyDecls = bodyCls && (new RegExp('\\.' + bodyCls + '\\{([^}]*)\\}').exec(sheet) || [])[1];
        // internal link to chapter02#target: its kindle:pos offset lands on the target's start tag
        const contents = resolveInternalLinks(e.chapters, e.links);
        const pos = /kindle:pos:fid:(\w{4}):off:(\w{10})/.exec(contents[0]);
        const bytes = new TextEncoder().encode(contents[parseInt(pos[1], 32)]);
        const at = new TextDecoder().decode(bytes.slice(parseInt(pos[2], 32), parseInt(pos[2], 32) + 60));
        // MOBI must not depend on the KF8 pass
        const m1 = await parseEpub(buf, {mobi: true, kf8: true}), m2 = await parseEpub(buf, {mobi: true, kf8: false});
        const r = Math.random, d = Date.now;
        Math.random = () => 0.5; Date.now = () => 0;
        const b1 = convertToAzw3(m1, 'mobi'), b2 = convertToAzw3(m2, 'mobi');
        Math.random = r; Date.now = d;
        // a failing pass falls back to the author sheets for that chapter
        const orig = window.kpNormalise;
        window.kpNormalise = () => { throw new Error('test failure'); };
        let fb;
        try { fb = await parseEpub(buf, {mobi: false, kf8: true}); } finally { window.kpNormalise = orig; }
        const enc = u8 => { let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000)); return btoa(s); };
        return {sheet, ch, head, flows: e.stylesheets.length, bodyDecls,
            afterH2: decls('<p[^>]*aid="2"[^>]*>'), noind: decls('<p[^>]*>(?=Indented)'),
            scr: decls('<p[^>]*>(?=Screen)'), small: decls('<p[^>]*>(?=Small)'),
            calc: decls('<div[^>]*>(?=Calc)'), pos: decls('<p[^>]*>(?=Positioned)'),
            dropcap: decls('<span[^>]*>(?=D<)'), hidden: decls('<div[^>]*>(?=HIDDEN)'),
            linkTarget: at, mobiSame: b1.length === b2.length && b1.every((x, i) => x === b2[i]),
            fbFlows: fb.stylesheets, fbHead: fb.chapters[0].skelHead, fbContent: fb.chapters[0].content,
            azw3: enc(convertToAzw3(e))};
    }''', base64.b64encode(kp_epub).decode())
    page.close()
    has = lambda d, pat: d is not None and re.search(pat, d) is not None
    test('Profile: one generated stylesheet flow (no author sheet flow)',
         lambda: kp['flows'] == 1 and '.noind' not in kp['sheet'] and re.search(r'^\.kp1\{', kp['sheet'], re.M) is not None)
    test('Profile: skeleton links the generated sheet (kindle:flow:0001)',
         lambda: re.search(r'<link[^>]*href="kindle:flow:0001\?mime=text/css"', kp['head']) is not None)
    test('Profile: pinned element defaults lead the sheet (p, h2, ul/ol, pre, sectioning)',
         lambda: kp['sheet'].startswith('p{display:block;margin:1em 0;text-indent:0}')
                 and 'blockquote{display:block;margin:1em 40px}' in kp['sheet'] and 'h2{display:block;font-size:1.5em' in kp['sheet']
                 and 'ul,ol{display:block;margin:1em 0;padding-left:40px}' in kp['sheet']
                 and 'white-space:pre-wrap' in kp['sheet'] and 'section,article,aside,nav' in kp['sheet'])
    test('Profile: sibling selector h2 + p {text-indent:0} baked onto the p',
         lambda: has(kp['afterH2'], r'(^|;)text-indent:0(;|$)'))
    test('Profile: @media screen rule baked, @media amzn-mobi not',
         lambda: has(kp['scr'], r'color:red') and not has(kp['scr'], r'color:blue'))
    test('Profile: !important wins over a more specific rule (and is not written)',
         lambda: has(kp['scr'], r'font-weight:bold') and '!important' not in kp['sheet'])
    test('Profile: &nbsp; indent becomes text-indent (3 × 0.25em), the nbsp run removed',
         lambda: has(kp['noind'], r'text-indent:0\.75em') and '>Indented by nbsp.' in kp['ch'])
    test('Profile: empty <p></p> dropped, <p>&nbsp;</p> and <p><br/></p> kept',
         lambda: '<p aid="5"' not in kp['ch'] and re.search(r'<p[^>]*>(?:</p>)', kp['ch']) is None
                 and re.search(r'<p[^>]*>\u00a0</p>', kp['ch']) is not None and re.search(r'<p[^>]*><br ?/></p>', kp['ch']) is not None)
    test('Profile: trailing <br> of a paragraph dropped', lambda: '<b>bold</b> text</p>' in kp['ch'])
    test('Profile: whitespace runs collapsed, kept in <pre>, nbsp after <br> kept',
         lambda: '>First para after the title.</p>' in kp['ch'] and '  keep   this\n   spacing</pre>' in kp['ch']
                 and '<br />\u00a0\u00a0verse indent' in kp['ch'] and '<i>red</i> <b>bold</b>' in kp['ch'])
    test('Profile: body side margins and padding 0 (top/bottom untouched)',
         lambda: has(kp['bodyDecls'], r'margin:0') and has(kp['bodyDecls'], r'padding:0') and not has(kp['bodyDecls'], '5%'))
    test('Profile: line-height 1 raised to 1.2', lambda: has(kp['bodyDecls'], r'line-height:1\.2(;|$)'))
    test('Profile: px font-size becomes em of the parent (12px → 0.75em, 24pt → 2em)',
         lambda: has(kp['small'], r'font-size:0\.75em') and has(kp['dropcap'], r'font-size:2em'))
    test('Profile: calc() ignored, the earlier width wins', lambda: has(kp['calc'], r'width:50%') and 'calc(' not in kp['sheet'])
    test('Profile: position/top/float dropped on a text block, float kept on the drop cap',
         lambda: kp['pos'] is not None and not has(kp['pos'], r'position|top:|float') and has(kp['dropcap'], r'float:left'))
    test('Profile: hidden element has a class with display:none', lambda: has(kp['hidden'], r'display:none'))
    test('Profile: no author class or style attribute left in the HTML',
         lambda: re.search(r'class="(?!kp\d)', kp['ch']) is None and ' style="' not in kp['ch'])
    test('Profile: internal link offset lands on the target element',
         lambda: kp['linkTarget'].startswith('<p') and 'id="target"' in kp['linkTarget'])
    test('Profile: MOBI output identical with and without the KF8 pass (opts.kf8)', lambda: kp['mobiSame'])
    test('Profile: a failing pass falls back to the author sheet for that chapter',
         lambda: len(kp['fbFlows']) == 2 and '.noind' in kp['fbFlows'][1]
                 and 'kindle:flow:0002?mime=text/css' in kp['fbHead'] and 'class="noind"' in kp['fbContent'])
    # Review regressions: hiding idioms, presentational attributes, spacers, stanza gaps, <br clear>
    kp2_epub = make_epub('Kindle Profile Regressions', [
        ('One', '<h1><span class="screen-reader-text">Chapter 1</span>Title</h1>\n'
                '<p><span class="sr-only">Skip</span>Visible</p>\n'
                '<ol type="a"><li>one</li></ol>\n<hr size="5" color="red" align="left"/>\n'
                '<table cellpadding="4"><tr><td>cell</td></tr></table>\n'
                '<p>a</p><div class="sb"></div><p>b</p><p class="pad"></p>\n'
                '<div class="poem"><p>line</p><p> </p><p>line2</p></div>\n'
                '<p><img src="x.png" class="fl" alt=""/>text<br class="cl"/></p>\n'
                '<p>a <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><style>.q{fill:red}</style>'
                '<text class="q">T</text></svg> b</p>\n<p class="rv">revert</p>\n'
                '<div id="hd"><div id="al">Authors</div></div>\n'
                '<div class="poem2"><p>Indented by the ancestor</p></div>\n'
                '<p><a href="#hd"><b>I.</b><br/> EARLY LETTERS</a></p>\n'
                '<p>before</p><div class="inl"></div><p>after</p>\n'
                '<p class="m">m1</p><p class="m"></p><p class="m">m2</p><div class="pb"></div><p>end</p>\n'
                '<div class="st"><div class="mm"></div><div class="mm">first stanza line</div></div>\n<div class="verse"><span class="vl">line one<br class="hb"/></span><span class="vl">line two<br class="hb"/></span></div>\n'
                '<div><svg xmlns="http://www.w3.org/2000/svg" width="9" height="9">\n  <g>\n    <rect width="9" height="9"/>\n  </g>\n  <text> spaced  text </text>\n</svg></div>'),
    ], css_rules=[
        ('p', 'margin: 0; font-weight: bold'),
        ('.screen-reader-text', 'clip: rect(1px, 1px, 1px, 1px); position: absolute !important; height: 1px; width: 1px; overflow: hidden'),
        ('.sr-only', 'position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%)'),
        ('.sb', 'margin-top: 2em'), ('.pad', 'padding-top: 1em'), ('.poem', 'white-space: pre-wrap'),
        ('.fl', 'float: left'), ('.cl', 'clear: both'), ('text', 'fill: blue'), ('.rv', 'font-weight: revert'),
        ('div', 'display: block; margin-left: 2em'), ('#hd #al', 'all: initial; margin-top: 0'),
        ('.poem2', 'text-indent: -2em; margin-left: 0'),
        ('.m', 'margin: 0 0 1em'), ('.pb', 'page-break-before: always'),
        ('.vl', 'display: block'), ('.hb', 'display: none'), ('.inl', 'display: inline'), ('.mm', 'margin: 1em 0'),
    ])
    page = browser.new_page()
    page.goto(base_url)
    kp2 = page.evaluate('''async (b64) => {
        const buf = Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer;
        const e = await parseEpub(buf, {mobi: false, kf8: true});
        const sheet = e.stylesheets[0], ch = e.chapters[0].content;
        const decls = re => {
            const m = new RegExp(re).exec(ch);
            const cls = m && /\sclass="([^"]*)"/.exec(m[0]);
            if (!cls) return '';
            return cls[1].split(' ').map(c => (new RegExp('\\.' + c + '\\{([^}]*)\\}').exec(sheet) || [])[1] || '').join(';');
        };
        return {sheet, ch, sr: decls('<span[^>]*>(?=Chapter 1)'), sr2: decls('<span[^>]*>(?=Skip)'),
            hr: decls('<hr[^>]*>'), td: decls('<td[^>]*>(?=cell)'), sb: decls('<div[^>]*>(?=</div><p[^>]*>b<)'),
            pad: decls('<p[^>]*>(?=</p>)'), rv: decls('<p[^>]*>(?=revert)'), al: decls('<div[^>]*>(?=Authors)'),
            anc: decls('<p[^>]*>(?=Indented by the ancestor)'), plain: decls('<p[^>]*>(?=<a )')};
    }''', base64.b64encode(kp2_epub).decode())
    page.close()
    test('Profile: clip / clip-path screen-reader text stays hidden (display:none), not revealed',
         lambda: 'display:none' in kp2['sr'] and 'display:none' in kp2['sr2'] and 'position' not in kp2['sr'])
    test('Profile: <ol type> not overridden (no pinned list-style-type), attribute kept',
         lambda: 'list-style-type' not in kp2['sheet'] and re.search(r'<ol [^>]*type="a"', kp2['ch']) is not None)
    test('Profile: <hr size color align> and <table cellpadding> carried into the class',
         lambda: all(d in kp2['hr'] for d in ['height:5px', 'color:red', 'background-color:red', 'margin-left:0'])
                 and 'padding:4px' in kp2['td'])
    test('Profile: empty spacer div (margin-top) and p (padding-top) kept',
         lambda: 'margin-top:2em' in kp2['sb'] and 'padding-top:1em' in kp2['pad'])
    test('Profile: whitespace-only <p> in a white-space:pre-wrap block (stanza gap) kept',
         lambda: re.search(r'>line</p><p[^>]*> </p><p[^>]*>line2<', kp2['ch']) is not None)
    test('Profile: trailing <br> with clear kept', lambda: re.search(r'text<br[^>]*class="kp\d+"[^>]*/></p>', kp2['ch']) is not None)
    test('Profile: nothing baked inside an <svg> with its own <style>',
         lambda: '<text class="q">T</text>' in kp2['ch'])
    test('Profile: revert overrides the author rule but writes nothing (the pinned/UA value applies)',
         lambda: 'font-weight' not in kp2['rv'] and 'margin:0' in kp2['rv'])

    test('Profile: an empty div displayed inline (e.g. all:initial) is dropped',
         lambda: re.search(r'>before</p><p[^>]*>after</p>', kp2['ch']) is not None)
    test('Profile: a winning `all: initial` resets weaker rules (no margin-left/display:block), written first',
         lambda: kp2['al'].startswith('all:initial;') and 'display:inline' in kp2['al'] and 'margin-left' not in kp2['al']
                 and 'margin-top:0' in kp2['al'])
    test('Profile: p under an indented ancestor gets text-indent:inherit (pinned p text-indent:0 elsewhere)',
         lambda: 'text-indent:inherit' in kp2['anc'] and 'text-indent' not in kp2['plain'])
    test('Profile: empty p whose margins collapse into its neighbours dropped; page-break div kept',
         lambda: re.search(r'>m1</p><p[^>]*>m2</p><div[^>]*></div><p[^>]*>end</p>', kp2['ch']) is not None)
    test('Profile: empty first child whose margin collapses into the next sibling\'s dropped',
         lambda: re.search(r'<div[^>]*><div[^>]*>first stanza line</div></div>', kp2['ch']) is not None)
    test('Profile: hidden <br> (display:none, Gutenberg verse br.hidebr) dropped',
         lambda: re.search(r'line one</span><span[^>]*>line two</span>', kp2['ch']) is not None)
    test('Profile: whitespace between SVG elements emptied, kept inside <text>',
         lambda: re.search(r'<svg[^>]*><g[^>]*><rect[^>]*/></g><text[^>]*> spaced  text </text></svg>', kp2['ch']) is not None)
    test('Profile: skeleton <body> tag ends skelHead; chunk inserted right after it (no newline before </body>)',
         lambda: kp['head'].endswith('aid="0">') and (lambda chs: bool(chs) and all(
             re.search(r'<body[^>]*aid="0"><', c['html']) and not re.search(r'\s</body>', c['html'])
             for c in chs))(extract_azw3_chapters(base64.b64decode(kp['azw3']))))
    test('Profile: the fallback (author-mode) chapter keeps the author skeleton (newline before </body>)',
         lambda: kp['fbHead'].endswith('aid="0">\n'))
    test('Profile: words around a <br> stay separated in the text (link text "I. EARLY LETTERS")',
         lambda: re.search(r'<b>I\. </b><br ?/>EARLY LETTERS</a>', kp2['ch']) is not None)

    kp_tmp = '/tmp/browser_kindle_profile.azw3'
    Path(kp_tmp).write_bytes(base64.b64decode(kp['azw3']))
    test('Profile: Calibre converts the book (all text present)',
         lambda: subprocess.run(['ebook-convert', kp_tmp, '/tmp/browser_kindle_profile.txt'],
                                capture_output=True, timeout=60).returncode == 0
                 and all(t in Path('/tmp/browser_kindle_profile.txt').read_text() for t in
                         ['Indented by nbsp.', 'Target paragraph.', 'verse indent']))
    test('Profile: no console warnings (besides the forced fallback above)',
         lambda: not [l for l in kp_console if l.startswith(('warning', 'error')) and 'test failure' not in l])

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
                    # Whole text: trailing entries stripped, decompressed if needed.
                    # (Records are 4096-byte cuts that may split a character; once the
                    # trailing entry is stripped, the concatenation must be valid UTF-8.)
                    sample = kf8_text_bytes(a)

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

    err_browser = pw.chromium.launch()

    # ── Case A: Normal-size corrupt file (> 500 bytes) ──
    # Not an iCloud stub → no retries; outside iOS it is reported as not an EPUB
    # (iOS keeps the iCloud advice: an undownloaded file can have its full size there).
    err_page = err_browser.new_page()
    err_page.goto(base_url)
    err_page.set_input_files('#fileInput', {
        'name': 'corrupt.epub',
        'mimeType': 'application/epub+zip',
        'buffer': b'This is not a valid ZIP file ' * 30,  # ~870 bytes > 500
    })
    err_page.wait_for_function(
        '() => document.getElementById("status").className.includes("error")',
        timeout=8000
    )
    test('Corrupt file (>500B): no raw JSZip error in message',
         lambda: 'central directory' not in err_page.inner_text('#status').lower())
    test('Corrupt file (>500B): says it is not a valid EPUB (zip) file',
         lambda: 'not a valid epub (zip) file' in err_page.inner_text('#status').lower())
    test('Corrupt file (>500B): no iCloud advice (not a stub, not iOS)',
         lambda: 'icloud' not in err_page.inner_text('#status').lower())
    test('Corrupt file (>500B): no Retry button',
         lambda: not err_page.is_visible('#retryBtn'))
    test('Corrupt file (>500B): download button stays hidden',
         lambda: not err_page.is_visible('#dlBtn'))

    # ── Case B: Empty file (0 bytes) — auto-retry mechanism ──
    # The app retries up to 10× (2s apart) for small files, giving iCloud time
    # to finish downloading. Full 20s test is too slow for CI; we just verify
    # the first retry attempt shows the "downloading from iCloud" status quickly.
    err_page2 = err_browser.new_page()
    err_page2.goto(base_url)
    err_page2.set_input_files('#fileInput', {
        'name': 'stub.epub', 'mimeType': 'application/epub+zip', 'buffer': b'',
    })
    # First status update should appear within 3s (before first retry delay)
    err_page2.wait_for_function(
        '() => document.getElementById("status").style.display !== "none"',
        timeout=3000
    )
    status_text = err_page2.inner_text('#status').lower()
    test('iCloud stub (0B): status shows quickly (auto-retry started)',
         lambda: len(status_text) > 0)
    # Note: full retry sequence (10× @ 2s = 20s) verified only on real iOS hardware
    # where file.arrayBuffer() returns updated bytes once iCloud download completes.

    # ── Case C: Retry button works ──
    # Show error, then pick a valid file, click Retry → converts successfully.
    # (Simulates user downloading the file from iCloud, then retrying.)
    # iPhone user agent: on iOS a normal-size non-zip file still gets the iCloud
    # advice (an undownloaded iCloud file can report its full size there).
    err_page3 = err_browser.new_page(user_agent=(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
        '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'))
    err_page3.goto(base_url)
    # Trigger the iCloud error with a corrupt file
    err_page3.set_input_files('#fileInput', {
        'name': 'bad.epub', 'mimeType': 'application/epub+zip',
        'buffer': b'Not a zip at all, more than 500 bytes padding ' * 20,
    })
    err_page3.wait_for_selector('#retryBtn', state='visible', timeout=8000)
    test('iOS corrupt file (>500B): iCloud advice + Retry button',
         lambda: 'icloud' in err_page3.inner_text('#status').lower())
    # Swap in a valid EPUB and click Retry
    valid_epub = make_epub('Retry Test', [('Ch1', '<p aid="1">Retry works!</p>')])
    err_page3.set_input_files('#fileInput', {
        'name': 'good.epub', 'mimeType': 'application/epub+zip', 'buffer': valid_epub,
    })
    # The change event will hide retryBtn and start conversion automatically.
    # Wait for result.
    err_page3.wait_for_function(
        '() => { const s=document.getElementById("status"); '
        'return s && (s.className.includes("ok") || s.className.includes("error")); }',
        timeout=20000
    )
    test('After picking valid file: conversion succeeds',
         lambda: 'ok' in (err_page3.get_attribute('#status', 'class') or ''))

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
