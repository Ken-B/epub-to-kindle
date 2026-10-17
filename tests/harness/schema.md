# Harness contracts

All harness modules live in `tests/harness/` and are plain Python 3.13 modules (no package install;
`cli.py` adds its own directory to `sys.path`). Each module exposes functions, not scripts, except
`cli.py`. Scripts are run with `uv run tests/harness/cli.py ...`; third-party dependencies are declared
once in `cli.py`'s inline script metadata (`playwright`, `pillow`, `lxml`).

Paths (all relative to the repo root, resolved via `ROOT = Path(__file__).resolve().parents[2]`):

```
tests/corpus/                 gitignored
  manifest.json               list[BookEntry]
  core/<folder>/<name>.epub   unpacked epub-corpus-core.zip
  heavy/<folder>/<name>.epub  unpacked epub-corpus-heavy.zip
  realworld/standard-ebooks/*.epub
  realworld/gutenberg/*.epub
  generated/*.epub            built from tests/epub_fixtures.py then mutated
  tools/KindleUnpack/         git clone
  out/<sha256>/               per-book working dir (see below)
tests/reports/<YYYY-MM-DD>-<subset>.md and .json
```

## BookEntry (manifest.json)

```json
{
  "id": "core/03-epubcheck-invalid/epub3_05-package-document__package-manifest-missing-item-error",
  "path": "tests/corpus/core/03-epubcheck-invalid/epub3_05-...-error.epub",
  "sha256": "…",
  "size_bytes": 12345,
  "category": "epubcheck-invalid",
  "expected_verdict": "error",
  "source_url": "https://github.com/w3c/epubcheck",
  "license_note": "BSD-3 (epubcheck test resources)",
  "subset": "core"
}
```

- `id`: `<subset>/<folder>/<basename without .epub>`; must be unique and filesystem-safe.
- `category`: one of `idpf`, `w3c`, `epubcheck-valid`, `epubcheck-warnings`, `epubcheck-invalid`,
  `epubcheck-other`, `se`, `pg`, `generated`, `local`.
- `expected_verdict`: `valid` | `warning` | `error` | `unknown`. For `03-epubcheck-*` derive from the
  filename suffix (`-valid`, `-warning`, `-error`, `-usage` → warning); else `valid` for idpf/w3c/se/pg,
  `error` for generated cases that are meant to be broken, `unknown` otherwise.
- `subset`: `core` | `heavy` | `real` | `generated` | `local`. `cli.py --subset` filters on this.
- `sha256` is unique: byte-identical books are folded into the first entry by id, whose optional
  `aliases` lists the other ids (they would share `out/<sha256>/`).
- The local reference book (`Oorlog en terpentijn - Stefan Hertmans.epub` in the repo root) is entry
  `local/hertmans`, category `local`, subset `local`.

## Per-book working directory `tests/corpus/out/<sha256>/`

```
ours.azw3            app output (KF8)               written by run_app.py
ours.mobi            app output (MOBI v6)           written by run_app.py
ours.<fmt>.meta.json {app_version, app_sha, ms, status_text, console_errors[], error, chapters_reported, skipped_chapters[]}
calibre.azw3         ebook-convert output           written by run_calibre.py
calibre.mobi
calibre.<fmt>.meta.json {calibre_version, ms, error}
input/               unzipped input EPUB            written by oracles.py (once)
unpack/<fmt>/ours/kindleunpack/   KindleUnpack tree of ours.<fmt>
unpack/<fmt>/ours/mobitool/       mobitool -e output of ours.<fmt>
unpack/<fmt>/ours/calibre.txt     ebook-convert ours.<fmt> → txt
unpack/<fmt>/calibre/kindleunpack/  KindleUnpack tree of calibre.<fmt>
inspect/<fmt>/ours.txt, calibre.txt   calibre-debug --inspect-mobi dumps (text)
result.<fmt>.json    Result (below)                 assembled by cli.py from the stage outputs
```

Caching rule: a stage skips its work when its output file exists (or a definitive error was recorded)
and, for `ours.*`, the stored `app_sha` (sha256 over `docs/index.html` + `docs/jszip.min.js`) equals
the current one; for `calibre.*`, the stored `calibre_version` equals `ebook-convert --version`.
Timeouts and harness errors (`error` starting with `harness:`) are never cached. The gate cache
(`unpack/<fmt>/<who>/gate.json`) is keyed by the file's sha256 and never stores timeouts.
`cli.py --force` ignores caches.

## Result (`result.<fmt>.json`)

```json
{
  "id": "…", "path": "…", "sha256": "…", "category": "…", "expected_verdict": "…",
  "size_bytes": 0, "subset": "…", "format": "azw3",
  "app":     {"ok": true, "ms": 0, "error": null, "status_text": "", "console_errors": []},
  "calibre": {"ok": true, "ms": 0, "error": null},
  "gate": {
    "mobitool":       {"ok": true, "err": null},
    "kindleunpack":   {"ok": true, "err": null},
    "calibre_reader": {"ok": true, "err": null}
  },
  "invariants": {
    "text":   {"spine_items": 0, "matching_items": 0,
               "first_diff": {"item": 0, "ours_excerpt": "", "input_excerpt": ""},
               "non_xhtml_spine_items": 0,
               "non_xhtml_handling": [{"item": 0, "type": "image/svg+xml", "output_has_img": false}]},
    "images": {"input": 0, "output": 0, "matched_by_hash": 0, "dimension_mismatch": 0,
               "missing": 0, "unextractable": 0, "refs_total": 0, "refs_correct": 0, "refs_missing": 0},
    "toc":    {"input_entries": 0, "output_entries": 0, "matched": 0, "depth_in": 0, "depth_out": 0},
    "links":  {"internal_total": 0, "resolved": 0},
    "style":  {"score": 0.0, "per_chapter": [0.0], "input_css_rules": 0,
               "input_css_rules_unreferenced": 0, "output_css_rules": 0}
  },
  "calibre_diff": {
    "header_fields_diff": [{"field": "…", "ours": "…", "calibre": "…"}],
    "chapters_ours": 0, "chapters_cal": 0,
    "ncx_depth_ours": 0, "ncx_depth_cal": 0,
    "css_rules_ours": 0, "css_rules_cal": 0,
    "text_similarity": 0.0
  },
  "categories": ["style-lost", "links-unresolved"]
}
```

Rules:
- Every stage writes `null` for fields it could not compute and never raises for a single book;
  exceptions are caught per book and recorded in the nearest `error`/`err` field.
- `app.ok` is true when the app produced a file. For `expected_verdict == "error"` books a clean,
  specific error message in `status_text` (no file) is also acceptable and gets category `app-clean-error`
  instead of `app-error`.
- `gate.*.ok` is false when the tool exited non-zero or produced no output tree, and null with
  `err: "timeout"` when it ran out of time (120 s + 60 s per 10 MB of input).
- `invariants` are computed only when `gate.kindleunpack.ok`; otherwise `null`.

### Invariant details (oracles.py)

Input lookup. A spine/manifest href is looked up in the input zip exactly, URI-decoded, NFC- and
NFD-normalised, and by the cp437 -> UTF-8 re-decoded member name (Python decodes names without the
UTF-8 flag as cp437; JSZip, the app, always decodes UTF-8). A book the app converted fine is therefore
not reported with `text.spine_missing_in_zip`. `text.app_skipped` still follows the app's own (JSZip)
view of the names.

`text`
- Only spine items whose manifest media-type is `application/xhtml+xml` or `text/html` are compared:
  `spine_items`/`matching_items`/`first_diff`/`chars_*` cover those only. A `text/*` (or missing)
  media-type on a `.xhtml/.html/.htm/.xht` file is a mislabelled document and counts as XHTML (the app reads
  it as such); every other type (`image/*` incl. svg, `application/json`, `application/xml`, mathml,
  dtbook, octet-stream, ...) is a foreign spine item, whatever its manifest `fallback`: the app is
  expected to follow the fallback, which is a writer matter, not a text-loss.
- `non_xhtml_spine_items`: number of foreign spine items; `non_xhtml_handling`: one record each,
  `{item (spine index), path, type (manifest media-type), fallback_type (media-type of the first XHTML/HTML
  item of its manifest fallback chain, else null), app_found, output_has_img (the output chapter holds an
  <img>), output_has_content (an <img> or any visible text)}`; the two `output_*` flags are null in
  `concat` mode (chapters cannot be told apart) and false when the app emitted no chapter. Foreign items
  are not parsed as markup when binary (raster images, media, fonts); other non-XHTML items are read as
  UTF-8 (a JSON spine item is not decoded as latin-1). They are left out of the images, links and style
  checks and of the CSS rule counts too. Category `spine-non-xhtml` (informational) keeps them visible.

MOBI v6 hidden content (`fmt == "mobi"` only). MOBI 6 readers ignore CSS, so the writer removes the
elements its author CSS hides (`display: none`, `visibility: hidden|collapse`), as Calibre's MobiML does.
The oracle does the same to the input before `text`, `links` and `images` run: every XHTML spine document
is loaded in the style pass's JS-disabled Chromium context (the style pass itself, which loads them
anyway, runs first; with `--no-style` a hidden-only pass loads them), an element counts as hidden when its
computed display/visibility hides it with the author style sheets and style attributes applied but not
without them (so the UA's `[hidden]`, `<head>` & co. do not count), and the topmost hidden elements are
removed from the parsed (lxml) document with their subtrees, keeping their tail text and an empty
`<a id|name>` for every id/name inside (the writer keeps link targets the same way). Chromium's element
sequence is mapped onto lxml's by aligning the local names (identical for XHTML). Links inside hidden
elements are thereby out of `links.internal_total`, images inside them out of the reference counts.
`text.hidden_excluded` = `{method: "chromium" | null (no browser), items (documents with hidden
elements), elements, chars (visible chars removed), anchors (<a href> removed), unmapped}`,
`links.hidden_anchors_excluded` = `anchors`. The style pass leaves the hidden input elements out as well.

`images`
- References: `img@src`, svg `image@href`, `video@poster`, `object@data`, `img@srcset`, `source@srcset`
  and CSS `url()` (outside `@font-face` and `@import`) in the style sheets reachable from the spine
  (AZW3 only: MOBI v6 has no style sheets). All feed the same `refs_total` / `refs_correct` /
  `refs_wrong_image` / `refs_missing` accounting; `refs_by_kind` counts them per kind (`src`, `srcset`,
  `poster`, `object`, `css`), `refs_missing_by_kind` the missing ones, `first_missing_ref` is the first
  missing one (`{item, kind, input}`).
- Pairing input and output references: only elements with a primary reference (`img@src`, svg `image@href`,
  `video@poster`, `object@data`) are paired with each other (by their text context, difflib over the
  document-order sequences). Every `<img>`/`<image>` takes part on both sides even without a usable
  reference: an input one whose src is a `data:` URI, remote or not in the manifest is a placeholder
  (paired, never counted), mirroring the output side, which lists every `<img>`/`<image>` without a
  usable src (a lost image). Otherwise the output's src-less counterpart of a `data:` image would take
  the pairing of a real image with the same text context (e.g. an empty one: the images of a document
  without text, or two images between the same two paragraphs); with the same elements on both sides,
  references with equal contexts pair in document order. `srcset` references are
  evaluated apart, in their own pairing keyed by context and tag, so a `<source>` is never paired with the
  `<img>` next to it (they share the same text context).
- `srcset` is one reference per element carrying candidates (`<img srcset>`, `<source srcset>`). When the
  output keeps the attribute it is correct when every candidate resolves to a file; a candidate that is still
  a dangling relative path (`../images/x.png`) makes it a missing reference. When the writer dropped it, it is
  correct if the `<img>` (for a `<source>`: the `<img>` of its `<picture>`) still has a `src` that resolves
  (a dropped `<source>` is fine), else missing. srcset candidates are not "referenced" images: they never
  feed `missing`.
- `kindle:embed:XXXX[?mime=...]` left in the output (KindleUnpack only rewrites `<img>`/`<image>` tags,
  style attributes and CSS `url()`; not `video@poster`, `object@data`, `source@srcset`, ...) is resolved by
  the harness: XXXX is base 32 (0-9, A-V), a 1-based index into the resource records from the MOBI header's
  first-resource record on (the same `rscnames[XXXX-1]` KindleUnpack uses), and KindleUnpack names the
  extracted file after that record (`image|cover|thumb<record:05d>.<ext>`) in `mobi8/OEBPS/Images` or
  `mobi7/Images`. The file is hashed like any other reference. KF8 only: a MOBI v6 file has no such
  references, so a `kindle:embed` there stays unresolved (missing). An embed that names an existing record
  KindleUnpack did not extract (svg, ...) still counts as a resolving `src` for the srcset rule above and as
  `unextractable` for the reference itself. The MOBI v6 analogue: KindleUnpack turns `<img recindex="NNNNN">`
  into a `src` only for the images it extracted; an `<img>` left with a `recindex` that names an existing
  resource record (1-based from the first-resource record) counts as a resolving `src` for the srcset rule
  the same way.
- Fallback: when the referenced manifest item has a `fallback` chain of images, the end of the chain is the
  expected image and any image of the chain is accepted. The foreign image itself is then not "referenced".
- `unextractable`: referenced images that are in the AZW3/MOBI file as an unchanged raw PalmDB record but
  that KindleUnpack did not extract (svg, avif, jxl, psd ...). They are not in `missing`. A reference to
  such an image counts in `refs_unextractable` (not correct, not missing; `refs_total` includes it).
  Category `images-unextractable` (informational).
- `missing` = referenced images (plus cover) neither present by hash, nor present-but-changed, nor
  unextractable.

`toc`
- Source: the EPUB 3 nav document when it has entries, else the NCX. When both exist and the nav is empty the
  NCX wins (the one with more entries). `source` says which.
- Labels: an anchor/label with no visible text uses the `<img alt>`, then a `title` (anchor or image),
  then (nav anchors only) the target file's basename, as a reader would show it.

`links`
- A fragment link whose target is the target document's `<body id>` resolves when the output link lands on
  the target chapter (no fragment needed).

`style`
- MOBI v6 (`fmt == "mobi"`): the score measures what MOBI 6 markup can carry.
  - Output semantics: before collecting, `MOBI_CSS` is added to the KindleUnpack `book.html` and its
    attributes are applied, after Calibre's MobiReader (base CSS and `upshift_markup`):
    `p {margin: 0; text-indent: 1.5em}`, `blockquote {margin: 0 0 0 2em}`; `align=left|right|center|justify`
    on p/div/h1-h6/li/dd/dt/td/th -> `text-align`; `width` -> `text-indent` and `height` -> `margin-top`
    (inline style; the writer writes them with a unit, `Npt` below 1em else `Nem`; a bare number would be
    px, Calibre `ensure_unit`), not on img/table/tr/td/th/hr/media; `<font size=1..7>` -> x-small, small,
    medium, large, x-large, xx-large, xxx-large (the HTML legacy sizes 10/13/16/18/24/32/48 px, which are
    the writer's own, 3 = normal). `body {text-align: justify}` is left out (a reader setting).
    `page.evaluate` runs with JavaScript disabled for the page. The output's baseline (see "carries
    author CSS") keeps the reader defaults (`MOBI_BASE_CSS`: the p and blockquote rules), and
    `margin-top`/`text-indent` left at the browser default on the input and at the MOBI default on the
    output are not checked: an unstyled paragraph gets the target reader's look (indented, no gap),
    which is not a conversion difference.
  - Both sides: computed `text-align` `-webkit-center|left|right` reads as `center|left|right`;
    `margin-left` is compared as the left inset level: margin-left + padding-left, plus those of the
    single-child `<blockquote>`s directly around the element (which then count 0), in the writer's 2em
    steps (`0` below 8 px, else round(px / 32), at most 3); `margin-top` of a block is the space above it,
    max(margin-top, margin-bottom of the previous block sibling); `<body>`/`<html>` margin-top/left are
    not compared (page margins: a reader setting in MOBI 6); `vertical-align` is what the text shows (the
    first raised/lowered value among the element and its inline ancestors) and `text-decoration-line`
    the union of the element's and its ancestors' lines, since the `<sup>`/`<sub>`/`<u>`/`<s>` wrappers
    may sit inside or outside the element that carried the CSS.
  - Not scored (`props_excluded_for_format`): display, font-family, font-variant, line-height,
    white-space, margin-right, padding-right (no MOBI 6 markup), padding-left (folded into the inset)
    and margin-bottom (folded into the next block's space above, where the writer puts it).
  - Ancestors of an anchor pair are compared on the non-inherited properties only (MobiML puts font,
    alignment and indent on the text itself, which the anchor pair compares).
  - Hidden input elements are left out (see "MOBI v6 hidden content").
  For AZW3 `props_excluded_for_format` is `[]` and nothing of this applies.
- `input_css_rules`: rule blocks of the style sheets reachable from an XHTML spine document (`<link
  rel=stylesheet>` to CSS, i.e. not `.xpgt` and not another declared type; `<style>`; `@import` chains),
  `@font-face` blocks excluded (fonts are dropped by design). The same exclusion applies to
  `output_css_rules`. `input_css_rules_unreferenced`: the rest of the manifest's `text/css` items.
- `calibre_diff` is computed only when both files exist; otherwise `null`.

## Module interfaces

```python
# corpus.py
def prepare(root: Path, *, se: int, pg: int, fetch: bool) -> list[dict]   # unpack, fetch, generate, write manifest
def load_manifest(root: Path) -> list[dict]

# run_app.py
class AppRunner:                      # context manager: starts HTTPServer on docs/ + one Chromium
    def convert(self, entry: dict, fmt: str, out_dir: Path, *, timeout_s: int) -> dict  # returns app meta

# run_calibre.py
def convert_many(entries: list[dict], fmts: list[str], out_root: Path, *, workers: int = 8,
                 timeout_s: int = 300, force: bool = False) -> dict[str, dict]  # sha -> {fmt: meta}

# oracles.py
def install_tools(root: Path) -> None                      # brew libmobi, clone KindleUnpack, playwright chromium
def gate(out_dir: Path, fmt: str, who: str = "ours") -> dict        # runs the three parsers, fills unpack/
def invariants(entry: dict, out_dir: Path, fmt: str, page) -> dict  # needs a Playwright page for style score

# calibre_diff.py
def diff(entry: dict, out_dir: Path, fmt: str) -> dict

# report.py
TAXONOMY = {...}                                                     # category -> (description, kind)
def categorize(result: dict) -> list[str]
def write_report(results: list[dict], out_md: Path, out_json: Path, *, subset: str) -> None
```

## Gap taxonomy

| category | assigned when | kind |
|---|---|---|
| app-error | app produced no file and no other app rule applies (incl. JS runtime / iCloud-stub messages) | writer bug |
| app-clean-error | no file, verdict `error`, specific app message (not a JS runtime error, not the iCloud advice), Calibre failed too | acceptable |
| app-timeout | app exceeded timeout | writer bug |
| gate-mobitool / gate-kindleunpack / gate-calibre | that parser failed | writer bug |
| text-loss | matching_items < spine_items (XHTML/HTML spine items only) | transform or repair, decided in report |
| spine-non-xhtml | `text.non_xhtml_spine_items` > 0: svg/image/xml/json spine items not compared as text | informational |
| text-garbled | more U+FFFD in our text than in the input's, or CSS rules in our body text but not in the input's | writer bug |
| images-missing | `images.missing` > 0: referenced input images (plus cover) neither present by hash, present-but-changed nor unextractable (raw record in the file) | unported Calibre transform (mobi.utils / writer8 resources) |
| images-resized | dimension_mismatch > 0 | informational |
| images-unextractable | `images.unextractable` > 0: referenced image present as a raw record KindleUnpack does not extract | informational |
| images-misreferenced | refs_total > 0 and (refs_wrong_image > 0 or refs_missing > 0), incl. dangling srcset candidates | writer bug |
| toc-missing | input_entries > 0 and output_entries == 0 | unported transform (writer8 toc) |
| toc-flat | depth_out < depth_in | unported transform (writer8 index NCX) |
| toc-labels | matched < min(input, output) | writer bug |
| links-unresolved | resolved < internal_total | unported transform (writer8 main: internal links) |
| style-lost | style.score < 0.5, or (AZW3 only) input_css_rules (reachable sheets, no @font-face) > 0 and output_css_rules == 0 | unported transform (writer8 main: css flows / oeb flatcss) |
| fixed-layout-unsupported | `invariants.fixed_layout`: input OPF has rendition:layout pre-paginated; the book's other categories become out of scope | out of scope |
| calibre-header-diff | header_fields_diff non-empty beyond the ignore list | informational |
| input-repair | app-error, a clean app error, or text-loss on a book Calibre converted fine and whose verdict is error/warning | input repair |
| harness-error | `harness:` error in app/calibre/gate meta, missing app meta, or `invariants.errors.harness` | harness (not counted) |
