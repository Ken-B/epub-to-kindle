# EPUB to AZW3 Converter

A client-side web app that converts EPUB ebooks to AZW3 (Kindle KF8) format — entirely in the browser, no server, no data uploaded.

**[Try it →](https://ken-b.github.io/epub-to-kindle/)**

## Features

- 🔒 **Fully private** — files never leave your device
- 📱 **Works on iPhone & Android** — install as a home screen app
- ✈️ **Works offline** — after first load, no internet required
- 🆓 **Free & open source** — GPL v3

## How to use

1. Open the web app (or install it to your home screen)
2. Drag & drop an EPUB file, or tap to pick one
3. Download the converted `.azw3` file
4. Send it to your Kindle via USB, email, or the Kindle app

## Formats

- **AZW3 / KF8** — for current Kindles and Kindle apps (default)
- **MOBI v6** — for old Kindles that predate KF8; author CSS is flattened into plain markup

## Install as a mobile app (offline use)

**iPhone/iPad:** Safari → Share button → "Add to Home Screen"
**Android:** Chrome → Menu → "Add to Home Screen" or "Install app"

Once installed, the app works in airplane mode — no internet needed.

## Technical notes

- Pure JavaScript, no build step: a few static files in `docs/`
- KF8/AZW3 writer ported from [Calibre](https://github.com/kovidgoyal/calibre) and [kf8-rs](https://github.com/codetheweb/kf8-rs)
- Uses [JSZip](https://stuk.github.io/jszip/) for EPUB (ZIP) reading
- PWA with service worker for offline caching

## Quality

Converted with this app and checked against a corpus of 886 books (IDPF samples, W3C conformance tests, epubcheck resources, 100 Standard Ebooks, 100 Project Gutenberg). For AZW3, all three independent parsers (libmobi, KindleUnpack, Calibre) accept every book the app converts (876 of 886; the rest are rejected with a clear error), 100% of internal links resolve, 99.97% of TOC entries match, and author CSS is preserved. Details: [tests/reports/2026-10-17-round3.md](tests/reports/2026-10-17-round3.md). Rendering on actual Kindle devices was not part of the automated checks.

## Development and testing

Prerequisites: [uv](https://docs.astral.sh/uv/), Calibre on PATH, libmobi (`mobitool`), Playwright Chromium, and a [KindleUnpack](https://github.com/kevinhendricks/KindleUnpack) clone in `tests/corpus/tools/KindleUnpack`.

```bash
git config core.hooksPath .githooks            # once: auto-bumps the version on commit
uv run tests/harness/cli.py prepare --fetch    # build the corpus
uv run tests/harness/cli.py all                # convert + check + report
uv run tests/harness/cli.py report             # rewrite the report from cached results
```

Install hints, the other test suites and format internals are in [CLAUDE.md](CLAUDE.md); report and result contracts in [tests/harness/schema.md](tests/harness/schema.md).

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE)

This project's KF8/AZW3 writing logic is derived from [Calibre](https://calibre-ebook.com/), which is also GPL v3. © Kovid Goyal and contributors.
