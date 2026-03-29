"""
Shared synthetic EPUB builder for tests.
Generates minimal valid EPUB 2 and EPUB 3 files entirely in memory.
"""
import io
import struct
import zlib
import zipfile

# ── Minimal 1×1 red PNG (67 bytes) ─────────────────────────────────────────

def _make_png_1x1():
    def chunk(name, data):
        c = name + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes([0, 255, 0, 0]))  # filter=0, R=255, G=0, B=0
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')

MINIMAL_PNG = _make_png_1x1()

# ── Template strings ─────────────────────────────────────────────────────────

CONTAINER_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
  xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''


def _opf2(title, manifest_items, spine_items):
    items = '\n    '.join(manifest_items)
    refs  = '\n    '.join(spine_items)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="uid">test-uid-001</dc:identifier>
    <dc:date>2024-01-01</dc:date>
  </metadata>
  <manifest>
    {items}
  </manifest>
  <spine>
    {refs}
  </spine>
</package>'''


def _opf3(title, manifest_items, spine_items):
    items = '\n    '.join(manifest_items)
    refs  = '\n    '.join(spine_items)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf"
         unique-identifier="uid" xml:lang="en">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="uid">test-uid-epub3</dc:identifier>
    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>
  </metadata>
  <manifest>
    {items}
    <item id="nav" href="nav.xhtml"
          media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine>
    {refs}
  </spine>
</package>'''


def _nav(chapters):
    items = '\n        '.join(
        f'<li><a href="chapter{i+1:02d}.xhtml">{title}</a></li>'
        for i, (title, _) in enumerate(chapters)
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Navigation</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
        {items}
    </ol>
  </nav>
</body>
</html>'''


# ── Public API ───────────────────────────────────────────────────────────────

def make_epub(
    title: str,
    chapters: list[tuple[str, str]],
    version: str = '2.0',
    css_rules: list[tuple[str, str]] | None = None,
    images: list[tuple[str, bytes]] | None = None,
) -> bytes:
    """
    Build a minimal valid EPUB ZIP in memory.

    Args:
        title:      Book title
        chapters:   List of (chapter_title, body_html) — body_html is the
                    inner HTML of <body>, NOT a full document
        version:    '2.0' (default) or '3.0'
        css_rules:  List of (selector, declaration) CSS rules to embed.
                    e.g. [('.watermark', 'display: none')]
        images:     List of (filename, bytes) image files to embed.
                    Chapters[0] body gets <img src="filename"/> prepended.

    Returns:
        bytes — the EPUB ZIP content
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        # mimetype must be first entry, uncompressed, no extra fields
        mi = zipfile.ZipInfo('mimetype')
        mi.compress_type = zipfile.ZIP_STORED
        z.writestr(mi, 'application/epub+zip')

        z.writestr('META-INF/container.xml', CONTAINER_XML)

        manifest_items = []
        spine_items = []

        # CSS
        if css_rules:
            css_text = '\n'.join(f'{sel} {{ {decl} }}' for sel, decl in css_rules)
            z.writestr('OEBPS/style.css', css_text)
            manifest_items.append(
                '<item id="css" href="style.css" media-type="text/css"/>'
            )

        # Images
        if images:
            for fname, data in images:
                mt = 'image/png' if fname.lower().endswith('.png') else 'image/jpeg'
                z.writestr(f'OEBPS/{fname}', data)
                item_id = 'img_' + fname.replace('.', '_')
                manifest_items.append(
                    f'<item id="{item_id}" href="{fname}" media-type="{mt}"/>'
                )

        # Chapters
        for i, (ch_title, body_html) in enumerate(chapters):
            fname = f'chapter{i+1:02d}.xhtml'
            css_link = '<link rel="stylesheet" href="style.css" type="text/css"/>' if css_rules else ''

            # Prepend image to first chapter if images provided
            if i == 0 and images:
                body_html = f'<img src="{images[0][0]}" alt="test image"/>\n' + body_html

            xhtml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{ch_title}</title>{css_link}</head>
<body>{body_html}</body>
</html>'''
            z.writestr(f'OEBPS/{fname}', xhtml)
            item_id = f'ch{i+1:02d}'
            manifest_items.append(
                f'<item id="{item_id}" href="{fname}" media-type="application/xhtml+xml"/>'
            )
            spine_items.append(f'<itemref idref="{item_id}"/>')

        # OPF
        opf_fn = _opf3 if version == '3.0' else _opf2
        z.writestr('OEBPS/content.opf', opf_fn(title, manifest_items, spine_items))

        # Nav doc (EPUB 3 only)
        if version == '3.0':
            z.writestr('OEBPS/nav.xhtml', _nav(chapters))

    return buf.getvalue()
