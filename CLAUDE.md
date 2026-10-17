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

**FDST flow structure:** ALL HTML content must be in flow 0 as a single continuous blob. Calibre's reader does `text = flows[0]` and all skeleton/chunk byte offsets index into that single array. Do NOT create one flow per chapter. Flows 1..N are the stylesheets (below); the text records simply cover the concatenation `html + sheets`, and FDST lists `[0, htmlLen]` then one contiguous `[start, end]` per sheet.

**CSS as flows (KF8 only):** every distinct stylesheet a chapter uses (linked `.css`, head or body `<style>`) becomes one flow, de-duplicated by content, linked from the skeleton `<head>` as `<link rel="stylesheet" type="text/css" href="kindle:flow:NNNN?mime=text/css"/>` (NNNN = flow number, base 32, 4 digits). CSS is kept verbatim (Kindle's engine does the cascade); only `url(img)` → `url(kindle:embed:XXXX?mime=…)`, `@import` → `@import url(kindle:flow:NNNN?mime=text/css)` (UNquoted: KindleUnpack/Calibre replace everything inside `url(…)` and add their own quotes), and `@font-face` with a `url()` src is dropped (fonts are not embedded). A flow containing `[CDATA[` is inlined as `<style>` by readers, so CDATA/`<!--` wrappers are stripped from inline styles. body/html `class`, `id`, `lang`, `epub:type`… are copied to the skeleton (CSS selects on them). MOBI v6 keeps only the display:none/visibility:hidden rules in one `<style>`.

**Internal links:** `<a href>` to a spine document (with/without `#frag`) or a bare `#frag` becomes `kindle:pos:fid:FFFF:off:OOOOOOOOOO` (base 32): FFFF = chunk table row = chunk sequence number (one chunk per chapter, so the chapter index), OOOOOOOOOO = byte offset of the target element's start tag `<` within that chunk's text (= `chapter.content`; readers add it to the chunk's insert position and take the nearest id at or before it). extractContent writes a placeholder of the same length (`kindle:pos:fid:0000:off:` + 10 decimal digits) and gives every element with an id (or `<a name>`) an aid; convertToAzw3 (resolveInternalLinks) measures the aid offsets and substitutes, so no offset moves. Missing fragment → offset 0 (chapter start). MOBI v6 gets the original hrefs back.

**Chunk index keys:** Must be GLOBAL byte positions (`flowStart + skelHeadLen - 1`), not local positions. All chapters with the same skeleton structure would have the same local position, causing dict collisions in Calibre's OrderedDict.

**FDST header fields:** record 0 offset 0xC0 = FDST record index, 0xC4 = number of FDST sections (`fdstEntries.length` = 1 + number of stylesheets), NOT the record index again — libmobi requires it to equal the FDST record's own count ("Corrupted data") and Calibre's inspector rejects it. MOBI v6 has no FDST: 0xC0 holds u16 first content record (1) + u16 last content record, 0xC4 = 1 (Calibre writer2).

**Text records + trailing entry:** every text record holds EXACTLY 4096 text bytes (last one shorter) before compression; never grow a record to finish a UTF-8 char (libmobi "Buffer error"). Since extra_data_flags = 1, each record ends with a multibyte trailing entry: the bytes completing a char split at the boundary ("overlap", also repeated at the start of the next record) followed by one byte = len(overlap); `0x00` when nothing is split (Calibre `create_text_record`).

**Image order:** parseEpub decides the resource order once (cover first) and numbers `kindle:embed:XXXX` from it; convertToAzw3 must write image records in exactly that order. MOBI v6 rewrites them to `recindex="NNNNN"` (1-based, 5 digits), drops `aid`, and joins chapters with `<mbp:pagebreak/>` in one HTML document.

**CNCX strings:** Must be non-empty. Format: `"P-//*[@aid='N']"` where N is the aid of the first block element in the chapter. Empty strings cause TypeError in Calibre's mobi8 reader (`idtext[12:-2]` on None).

### Reference implementations
- Calibre (GPL v3): `src/calibre/ebooks/mobi/writer8/` — Python, battle-tested
- kf8-rs: `src/serialization/` — Rust, useful for format reference

## Versioning

The app version lives in `docs/index.html` (`APP_VERSION`) and `docs/sw.js` (`CACHE`).
Both must match — the SW cache name must change to bust the cache for returning users.

A pre-commit hook in `.githooks/pre-commit` **auto-bumps the patch version**
whenever any `docs/` file changes. It's wired via `git config core.hooksPath .githooks`
(already set in this repo).

- To release a minor/major bump: manually edit both files before committing.
- The hook detects that the version already changed and leaves it alone.

## Testing

```bash
# Start local server
cd docs && python3 -m http.server 8765

# Validate AZW3 output with Calibre
ebook-meta output.azw3
ebook-convert output.azw3 output.txt

# Test EPUB → AZW3 in Node (no browser needed)
node /tmp/test-v6.mjs  # see /tmp/ for test scripts
```

### Quality harness

Differential harness: converts a ~900-book corpus with the app (headless Chromium) and with Calibre, then
checks gate (mobitool, KindleUnpack, Calibre reader), invariants (text/images/TOC/links/style) and a Calibre diff.
Prerequisites: `brew install libmobi`, Calibre, `git clone --depth 1 https://github.com/kevinhendricks/KindleUnpack tests/corpus/tools/KindleUnpack`, `uv run --with playwright playwright install chromium`.
```bash
uv run tests/harness/cli.py prepare            # manifest (add --fetch to download real-world books)
uv run tests/harness/cli.py all                # convert + check + report (--subset, --ids, --fmt, --limit, --no-style, --force)
uv run tests/harness/cli.py report             # only rewrite the report from cached results
```
Per-book results: `tests/corpus/out/<sha256>/result.<fmt>.json`; reports: `tests/reports/<date>-<subset>.md/.json`; contracts: `tests/harness/schema.md`.

## PWA / Offline

Service worker caches all assets on first load. Works offline after that.
iOS: Safari → Share → Add to Home Screen
Android: Chrome → Install app
