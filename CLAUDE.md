# EPUB → AZW3 Converter — Developer Notes

## Architecture

Pure JavaScript, no build step. Everything is in `docs/index.html` (single file).

### File structure
```
docs/
  index.html    # App: KF8 writer + EPUB parser + UI + PWA registration
  sw.js         # Service worker (must be separate file)
  manifest.json # PWA manifest
  jszip.min.js  # JSZip 3.10.1 (cached by service worker)
  icon-*.png    # PWA icons
```

## KF8/AZW3 Format Notes

KF8 (Kindle Format 8) is a PalmDoc container with MOBI/EXTH headers.

### Critical implementation details

**VLQ encoding (encint):** Calibre uses a non-standard convention where the HIGH BIT marks the LAST byte (terminator), not continuation bytes. `encint(0)→[0x80]`, `encint(15)→[0x8f]`, `encint(128)→[0x01,0x80]`. Wrong encoding breaks ALL index reading.

**FDST flow structure:** ALL HTML content must be in flow 0 as a single continuous blob. Calibre's reader does `text = flows[0]` and all skeleton/chunk byte offsets index into that single array. Do NOT create one flow per chapter. Flows 1..N are the stylesheets (below) and SVG images; the text records simply cover the concatenation `html + flows`, and FDST lists `[0, htmlLen]` then one contiguous `[start, end]` per flow.

**CSS as flows (KF8 only):** every distinct stylesheet a chapter uses (linked `.css`, head or body `<style>`) becomes one flow, de-duplicated by content, linked from the skeleton `<head>` as `<link rel="stylesheet" type="text/css" href="kindle:flow:NNNN?mime=text/css"/>` (NNNN = flow number, base 32, 4 digits). CSS is kept verbatim (Kindle's engine does the cascade); only `url(img)` → `url(kindle:embed:XXXX?mime=…)`, `@import` → `@import url(kindle:flow:NNNN?mime=text/css)` (UNquoted: KindleUnpack/Calibre replace everything inside `url(…)` and add their own quotes), and `@font-face` with a `url()` src is dropped (fonts are not embedded). A flow containing `[CDATA[` is inlined as `<style>` by readers, so CDATA/`<!--` wrappers are stripped from inline styles. body/html `class`, `id`, `lang`, `epub:type`… are copied to the skeleton (CSS selects on them). MOBI v6 has no CSS: see "MOBI v6 markup" below.

**Internal links:** `<a href>` to a spine document (with/without `#frag`) or a bare `#frag` becomes `kindle:pos:fid:FFFF:off:OOOOOOOOOO` (base 32): FFFF = chunk table row = chunk sequence number (one chunk per chapter, so the chapter index), OOOOOOOOOO = byte offset of the target element's start tag `<` within that chunk's text (= `chapter.content`; readers add it to the chunk's insert position and take the nearest id at or before it). extractContent writes a placeholder of the same length (`kindle:pos:fid:0000:off:` + 10 decimal digits) and gives every element with an id (or `<a name>`) an aid; convertToAzw3 (resolveInternalLinks) measures the aid offsets and substitutes, so no offset moves. Missing fragment → offset 0 (chapter start). MOBI v6: `<a filepos="NNNNNNNNNN">` (Calibre writer2/serializer.py), 10 decimal digits = byte offset in the flat text of the target's start tag `<` (chapter start, just after its `<mbp:pagebreak/>`, without a fragment); href dropped. The placeholder href first becomes `filepos="<link number, 10 digits>"` so each body has its final length, markAids/takeAidMarks measure the target aids (TOC ∪ link targets) on the final strings, then the numbers are replaced by the offsets. KindleUnpack inserts `<a id="fileposN"/>` exactly at N. Links to a skipped chapter keep their original href.

**Chunk index keys:** Must be GLOBAL byte positions (`flowStart + skelHeadLen - 1`), not local positions. All chapters with the same skeleton structure would have the same local position, causing dict collisions in Calibre's OrderedDict.

**FDST header fields:** record 0 offset 0xC0 = FDST record index, 0xC4 = number of FDST sections (`fdstEntries.length` = 1 + number of stylesheets), NOT the record index again — libmobi requires it to equal the FDST record's own count ("Corrupted data") and Calibre's inspector rejects it. MOBI v6 has no FDST: 0xC0 holds u16 first content record (1) + u16 last content record, 0xC4 = 1 (Calibre writer2).

**Text records + trailing entry:** every text record holds EXACTLY 4096 text bytes (last one shorter) before compression; never grow a record to finish a UTF-8 char (libmobi "Buffer error"). Since extra_data_flags = 1, each record ends with a multibyte trailing entry: the bytes completing a char split at the boundary ("overlap", also repeated at the start of the next record) followed by one byte = len(overlap); `0x00` when nothing is split (Calibre `create_text_record`).

**Image order:** parseEpub decides the resource order once (cover first) and numbers `kindle:embed:XXXX` from it; convertToAzw3 must write image records in exactly that order. MOBI v6 rewrites every attribute holding a `kindle:embed` URL (`src`, `poster`, `data`, `xlink:href`) to `recindex="NNNNN"` (1-based, 5 digits), turns a `<video>` into `<img recindex>` of its poster (or its fallback content), replaces an `<img>` of an SVG file (`kindle:flow:`) by its alt text, drops `aid`, and joins chapters with `<mbp:pagebreak/>` in one HTML document. Every regex that replaces a whole construct (`SVG_IMAGE_ONLY_RE`, `<video>`) must accept and re-emit the `\0aid\0` marks markAids put in front of start tags, or a link/TOC target inside it breaks the rewrite or loses its offset.

**MOBI v6 markup ("MobiML lite", `mobiMarkup`):** old Kindles ignore CSS, so for MOBI v6 the author CSS is flattened into HTML 3.2 markup like Calibre's mobiml.py, in place on the chapter DOM. extractContent matches the chapter's sheets (link/style, @import, @media all/screen/amzn-mobi, @supports via `CSS.supports`, @layer; `ns|attr` → `*|attr`) with `querySelectorAll` BEFORE it changes the DOM (DOMParser documents are not rendered: no getComputedStyle), ordered by !important, specificity, source order, then `style=""`; after the KF8 `content` is serialised it rewrites the DOM into `chapter.mobiContent` (so KF8 bytes never depend on it; parseEpub `opts.mobi`, default true, the UI passes `fmt === 'mobi'`, and `kf8: false` for MOBI so no CSS/SVG flows are built). The MOBI preparation is optional per chapter: any exception in the rules, cascade or markup is caught (console.warn) and the chapter falls back to its KF8 content — never "Skip chapter". text/html-parsed chapters have attributes like `epub:type` with a null namespace: copy those with `setAttribute`, never `setAttributeNS(null, "epub:type")` (NamespaceError). mobiCascade skips a (valid) selector whose rightmost compound names a tag/class/id the chapter lacks (`mobiSelectorNeeds`, lower-cased over-approximation); `@media not …` negates a query it understands. Nesting caps: TOC 64 levels, CSS blocks/@import 64, mobiMarkup 512 elements deep (deeper content is left as is). Mapping: bold → `<b>`, italic → `<i>`, underline/line-through → `<u>`/`<s>`, font-size → `<font size=1..7>` (px 10/13/16/18/24/32/48, 3 = normal), color → `<font color>`, vertical-align super/sub → `<sup>`/`<sub>` (wrappers around runs of inline content only); `<b>`/`<i>`/`<u>`… the CSS cancels → `<span>`; text-align (and margin-left+right auto) → `align` on p/div/h*/li/td/th/dd/dt; on paragraphs that hold text: text-indent → `width` (0..10em, negative folded into the left margin), collapsed vertical margins → `height` (≤ 2em; pt below 1em, as Calibre); margin+padding-left → `<blockquote>` per ~2em (≤ 3); page-break-before/after → `<mbp:pagebreak/>` (not at a chapter start); display:none / visibility:hidden → element removed, an empty `<a aid>` (with an empty text node: never `<a/>`) keeps link/TOC targets; `style` attributes are dropped once flattened (Calibre's MOBI reader applies them on top of the markup: a `style="margin-left"` inside the `<blockquote>` it became indents twice). Headings keep their tags (so a CSS-normal-weight heading stays bold). The MOBI `<style>` holds only hiding rules whose selector `querySelectorAll` rejects. Not expressible in MOBI 6 and dropped: small-caps/font-variant, line-height, white-space, display changes, hanging indents.

**Image references:** `<img src>`, `<video poster>` and SVG `<image xlink:href|href>` resolve through `imageByPath` (normalised zip path, see below) first, then the legacy href/file-name keys. SVG `<image>` gets `kindle:embed:XXXX?mime=…` (attribute node edited in place, namespace kept); MOBI v6 turns an `<svg>` whose only child is one `<image>` into `<img recindex width height/>` and leaves other SVG alone. An `.svg` FILE referenced by `<img>` (or an SVG spine item) is not a resource record but a flow, `kindle:flow:NNNN?mime=image/svg+xml` (Calibre extract_svg_into_flows; KindleUnpack classifies a flow containing `<svg` as an image). `<object data>` of an image without an image fallback inside becomes `<img src>` (both formats). `srcset`/`sizes` are dropped (src is the fallback; neither Calibre nor KindleUnpack resolve a list of kindle:embed URLs), `<source>` inside a `<picture>` that has an `<img>` is removed. A foreign image type resolves through its manifest `fallback` chain to the first JPEG/PNG/GIF/BMP/SVG item.

**Reading the EPUB:** text files (OPF, chapters, CSS) are read as bytes and decoded by BOM → XML declaration → `@charset` → `<meta charset>`/http-equiv (first 1024 bytes) → UTF-8; UTF-8 that yields U+FFFD on bytes that are valid windows-1252 falls back to windows-1252 (`decodeText`) only when the bytes hold no valid multibyte UTF-8 sequence or the invalid ones outnumber the valid ones more than twice (a UTF-8 file with a stray byte stays UTF-8, one U+FFFD). Zip names without the UTF-8 flag are UTF-8 if valid, else CP437 (`decodeZipName`). Every href is resolved with `resolve`/`joinPath` (%-decoded, `./`/`../` folded, leading `/` = container root) and looked up via `zipFile` (also NFC/NFD-tolerant). OPF: container rootfile, else the zip's only `*.opf`. Spine: a non-XHTML item follows its manifest `fallback` chain to an XHTML item (links and TOC entries naming the original item resolve to that chapter; a document in the spine twice resolves to its first copy); otherwise a raster image becomes a page with one `<img>`, an SVG becomes an `<img>` page in KF8 and an empty page in MOBI v6 (`svgPage`), anything else is skipped (`console.warn('Skip chapter:', …)`); zero chapters throws "No readable chapters found in the EPUB spine (…)". Stylesheets: every `*.css` in the zip is available to `<link>` (wrong or missing manifest media-type).

**NCX index (TOC):** parseEpub reads the whole TOC tree (EPUB3 nav, or the NCX when it has more entries) and resolveToc flattens it in document order to `{label, chapter, aid, depth, parent, children}`: the `#frag` becomes the aid extractContent gave the target (chapter start without one); an entry with no spine target (no href, `<span>` heading, non-spine file) keeps its label and place but takes the position of the nearest following resolved entry. No usable TOC → one entry per chapter (heading / `<title>` / "Chapter N"). Tags (Calibre writer8 NCXIndex, values written in this order): offset(1,mask 1), length(2,2), label(3,4: CNCX offset), depth(4,8), parent(21,16), first_child(22,32), last_child(23,64), pos_fid(6,2 values,128). Write 21/22/23 ONLY when they exist (0xffffffff → Calibre KeyError). Entries are sorted by (depth, play order) — all top-level entries first — so a parent's children are contiguous; parent/child values are indices in that order. KF8 offset = chunk insert position + offset in chunk (flow 0 as rebuilt), pos_fid = [chapter, offset in chunk] (same fid:off as kindle:pos links); length = up to the next entry at the same or shallower depth, else `len(flow 0)`. MOBI v6 uses the same table without pos_fid, offsets in the flat document (markAids/takeAidMarks find the targets after toMobi6 drops the aids). Labels: CNCX strings (one record per ≤ 0x10000 - 1024 bytes, offset = record × 0x10000 + offset; ≤ 500 chars, de-duplicated). Calibre's MOBI 6 reader ignores the NCX index (builds its TOC from the HTML); KindleUnpack and Kindles use it.

**CNCX strings:** Must be non-empty. Format: `"P-//*[@aid='N']"` where N is the aid of the first block element in the chapter. Empty strings cause TypeError in Calibre's mobi8 reader (`idtext[12:-2]` on None).

### Reference implementations
- Calibre (GPL v3): `src/calibre/ebooks/mobi/writer8/` — Python, battle-tested
- kf8-rs (https://github.com/codetheweb/kf8-rs, no licence declared): `src/serialization/` — Rust, useful for format reference
- Attribution of the ported calibre modules is in the comment at the top of the `<script>` in `docs/index.html`; keep it current when porting more.

## Versioning

The app version lives in `docs/index.html` (`APP_VERSION`) and `docs/sw.js` (`CACHE`).
Both must match — the SW cache name must change to bust the cache for returning users.

A pre-commit hook in `.githooks/pre-commit` **auto-bumps the patch version**
whenever any `docs/` file changes. Hooks path is local git config, so it is NOT set
in a fresh clone: run `git config core.hooksPath .githooks` once after cloning.

- To release a minor/major bump: manually edit both files before committing.
- The hook detects that the version already changed and leaves it alone.

## Testing

```bash
# Start local server
cd docs && python3 -m http.server 8765

# Unit tests of the converter in Node (no browser needed)
node tests/test_converter.mjs

# Browser, Calibre-comparison and end-to-end tests
uv run --python 3.13 tests/test_browser.py
uv run --python 3.13 tests/test_calibre_compare.py
uv run --python 3.13 tests/test_e2e.py

# Validate AZW3 output with Calibre
ebook-meta output.azw3
ebook-convert output.azw3 output.txt
```

### Quality harness

Differential harness: converts a ~900-book corpus with the app (headless Chromium) and with Calibre, then
checks gate (mobitool, KindleUnpack, Calibre reader), invariants (text/images/TOC/links/style) and a Calibre diff.
Prerequisites (`uv` for all Python):
- libmobi (`mobitool`): macOS `brew install libmobi`; Debian/Ubuntu `apt install libmobi-tools`.
- Calibre on PATH: macOS `brew install --cask calibre`; Linux the official installer script (https://calibre-ebook.com/download_linux).
- KindleUnpack: `git clone --depth 1 https://github.com/kevinhendricks/KindleUnpack tests/corpus/tools/KindleUnpack`.
- Playwright Chromium: `uv run --with playwright playwright install chromium` (Linux: `uv run --with playwright playwright install --with-deps chromium`).

```bash
uv run tests/harness/cli.py prepare            # manifest (add --fetch to download the corpus, see below)
uv run tests/harness/cli.py all                # convert + check + report (--subset, --ids, --fmt, --limit, --no-style, --force)
uv run tests/harness/cli.py report             # only rewrite the report from cached results
uv run tests/harness/cli.py compare --before tests/corpus/<name>-results   # before/after diff
```
Per-book results: `tests/corpus/out/<sha256>/result.<fmt>.json`; reports: `tests/reports/<date>-<subset>.md/.json`; contracts: `tests/harness/schema.md`.

Corpus: `tests/corpus/` is git-ignored. When no corpus is present, `prepare --fetch` rebuilds it from the GitHub sources: the spec corpora from github.com/IDPF/epub3-samples, github.com/w3c/epub-tests and the github.com/w3c/epubcheck test resources, plus the real-world books (100 Standard Ebooks and 100 Project Gutenberg, fetched at 1 request/s).

`compare --before DIR` needs an archived results directory (`tests/corpus/<name>-results/`, a copy of an earlier `tests/corpus/out/`). A fresh clone has none until a first run is archived (e.g. `cp -r tests/corpus/out tests/corpus/<name>-results` before changing the writer).

## PWA / Offline

Service worker caches all assets on first load. Works offline after that.
iOS: Safari → Share → Add to Home Screen
Android: Chrome → Install app
