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

**FDST flow structure:** ALL HTML content must be in flow 0 as a single continuous blob. Calibre's reader does `text = flows[0]` and all skeleton/chunk byte offsets index into that single array. Do NOT create one flow per chapter.

**Chunk index keys:** Must be GLOBAL byte positions (`flowStart + skelHeadLen - 1`), not local positions. All chapters with the same skeleton structure would have the same local position, causing dict collisions in Calibre's OrderedDict.

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

## PWA / Offline

Service worker caches all assets on first load. Works offline after that.
iOS: Safari → Share → Add to Home Screen
Android: Chrome → Install app
