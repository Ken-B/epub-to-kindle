# EPUB to AZW3 Converter

A client-side web app that converts EPUB ebooks to AZW3 (Kindle KF8) format — entirely in the browser, no server, no data uploaded.

**[Try it →](https://kenp.github.io/wasm-epub2azw3/)**

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

## Install as a mobile app (offline use)

**iPhone/iPad:** Safari → Share button → "Add to Home Screen"
**Android:** Chrome → Menu → "Add to Home Screen" or "Install app"

Once installed, the app works in airplane mode — no internet needed.

## Technical notes

- Pure JavaScript, no build step, single HTML file
- KF8/AZW3 writer ported from [Calibre](https://github.com/kovidgoyal/calibre) and [kf8-rs](https://github.com/codetheweb/kf8-rs)
- Uses [JSZip](https://stuk.github.io/jszip/) for EPUB (ZIP) reading
- PWA with service worker for offline caching

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE)

This project's KF8/AZW3 writing logic is derived from [Calibre](https://calibre-ebook.com/), which is also GPL v3. © Kovid Goyal and contributors.
