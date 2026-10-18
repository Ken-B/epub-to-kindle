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
  `epubcheck-other`, `se`, `pg`, `generated`, `local`, `private`.
- `expected_verdict`: `valid` | `warning` | `error` | `unknown`. For `03-epubcheck-*` derive from the
  filename suffix (`-valid`, `-warning`, `-error`, `-usage` → warning); else `valid` for idpf/w3c/se/pg,
  `error` for generated cases that are meant to be broken, `unknown` otherwise.
- `subset`: `core` | `heavy` | `real` | `generated` | `local` | `private`. `cli.py --subset` filters on this.
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
    "style":  {"score": 0.0, "score_page_dependent": 0.0, "page_neutral": true, "per_chapter": [0.0], "input_css_rules": 0,
               "input_css_rules_unreferenced": 0, "output_css_rules": 0,
               "device_score": 0.0, "device_per_chapter": [0.0], "device_checked_props": 0,
               "device_equal_props": 0, "device_prop_disagreements": {"text-indent": 0},
               "device_prop_examples": {"text-indent": [{"text": "", "tag": "p", "out_tag": "p", "in": "0px", "out": "24px"}]},
               "device_model": "kindle-v1", "device_css_removed": {"at:media": 0, "selectors": 0, "rules": 0},
               "visibility": {"hidden_in_input_shown_out_chars": 0, "hidden_in_input_shown_out_elements": 0,
                              "shown_in_input_hidden_out_chars": 0, "shown_in_input_hidden_out_elements": 0,
                              "examples": {"hidden_in_input_shown_out": [{"chapter": 2, "text": "Here, Perfect to a Wish", "chars": 19}],
                                           "shown_in_input_hidden_out": []}},
               "device_visibility": {"…": "same shape as visibility, AZW3 only (null for MOBI)"}},
    "layout_hygiene":       {"empty_blocks": 0, "trailing_breaks": 0, "whitespace_runs": 0, "nbsp_indents": 0,
                             "empty_blocks_styled": 0, "trailing_breaks_double": 0,
                             "nbsp_indents_ambiguous": 0, "documents": 0, "examples": {"empty_blocks": ["part0003.xhtml: <p> ''"]}},
    "layout_hygiene_input": {"empty_blocks": 0, "trailing_breaks": 0, "whitespace_runs": 0, "nbsp_indents": 0,
                             "documents": 0, "examples": {}}
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
elements its author CSS hides (`display: none`, `visibility: hidden|collapse`), the elements with the `hidden`
attribute (unless the author sets a display), and the `position: absolute|fixed` elements moved off the page or
clipped away (a declared left/top/right/bottom of -500px or less, `clip: rect()` with every side at most 1px,
`clip-path: inset(>= 50%)` / `circle(0)`, a declared width or height of at most 1px with `overflow: hidden|clip`;
read from `computedStyleMap`, since `getComputedStyle` resolves `bottom: auto` to a px value), as Calibre's MobiML does.
The oracle does the same to the input before `text`, `links` and `images` run: every XHTML spine document
is loaded in the style pass's JS-disabled Chromium context (the style pass itself, which loads them
anyway, runs first; with `--no-style` a hidden-only pass loads them), an element counts as hidden when its
computed display/visibility hides it with the author style sheets and style attributes applied but not
without them (so the UA's `<head>` & co., `<rp>` do not count; the `hidden` attribute does), or the
position patterns above hold, and the topmost hidden elements are
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
- Page-neutral preservation score (AZW3): the writer zeroes the `<html>`/`<body>` side margins and paddings
  on purpose (the Kindle owns the page margins), so comparing them, or percentage widths/margins that
  resolve against a wider content box, would penalise every book. `score` therefore aligns the output
  (loaded as it is, without the device model) against the page-neutral input reference of the device pass
  (the second input load served with `device.INPUT_PAGE_CSS`, loaded once and shared by both scores) and
  does not compare margin-top/bottom/left/right and padding-left/right of `<html>`/`<body>` (`_StyleAcc`
  `page_box_free`). `page_neutral` is true when every chapter used that reference, false when the device
  pass failed for some chapter and the plain input was used instead. `score_page_dependent` is the old
  number (plain input, page margins counted), for reference and for comparing with results written before
  this field existed (their `score` is the old definition; `compare.py` pairs it with the new result's
  `score_page_dependent`). `prop_disagreements`, `prop_examples`, `per_chapter`, `checked_props`,
  `equal_props` and `score_all_props` belong to the page-neutral score.
- Alignment key and unrendered elements (both scores): anchors are aligned on their full textContent with ALL
  whitespace removed (NFC, soft hyphen/ZWSP/BOM dropped), so the writer's whitespace hygiene (newline after
  `<br/>`, trimmed runs) does not unmatch a heading (`XVII<br/>\n<span>` equals `XVII<br/><span>`); the
  difflib order alignment, `(key, tag)` first then key alone, and the fallback window are unchanged, so
  repeated texts still pair in document order. An element pair is skipped (no property checked, nothing
  counted) when `display:none` holds on the element or an ancestor on BOTH sides (`hid` in the element
  record): its computed style is noise (line-height of two hidden headings). An unmatched input anchor that
  is itself hidden scores nothing instead of 0. One side hidden and the other shown is still compared (a
  `display` disagreement, e.g. Standard Ebooks' `@supports` un-hide dropped by the Kindle profile);
  the visibility oracle covers the text itself. MOBI v6 is unchanged:
  `score_page_dependent == score`, `page_neutral` false.
- Device score (AZW3 only; `device_score: null` for MOBI, and with `device_error` when the pass
  failed): what a Kindle would show, not what a browser shows. Every output part is loaded a second
  time in its own JS-disabled context whose requests are answered through `device.py` (Playwright
  route fulfil): the document gets `KINDLE_UA_CSS` as its FIRST style sheet (a `<style>` right after
  `<head>`), and every style sheet it loads (linked `Styles/*.css`, `@import`, inline `<style>`) is
  rewritten by `device_css`: `@media`, `@supports`, `@namespace`, `@layer` (also `@container`,
  `@scope`, `@document`, `@starting-style`) are removed with their blocks (not inlined), `@charset`
  removed, `@import` kept only for a relative URL without condition; in every rule's selector list a
  selector with a sibling combinator (`+`, `~`), an attribute selector, a namespace prefix (`|`),
  `:not(`/`:is(`/`:where(`/`:has(` or a structural pseudo-class other than `:first-child`
  (`:nth-*`, `:last-child`, `:only-child`, `:*-of-type`, `:root`, `:empty`) is dropped, and the
  rule when none is left; pseudo-elements and declarations are kept. The rewriter is a tokeniser
  (strings, comments, escapes, unquoted `url()`, nested blocks); `device_css_removed` counts what it
  removed per book (unique sheets). `KINDLE_UA_CSS` is a tunable model assumption (`device_model`
  names its version): `p {margin: 0; text-indent: 1.5em}`, `blockquote {margin: 0 0 0 2em}`,
  `h1..h6 {margin: 0}`, `ul, ol {margin: 0; padding-left: 2em}`, and section/article/aside/nav/
  header/footer/main/figure/figcaption/hgroup/details/summary `{display: inline}` (unknown
  elements), so a default the writer leaves unpinned is penalised. The device rendering is aligned
  and scored, with the same `_align_score` / `_StyleAcc` rules as `score`, against a SECOND load of
  each input chapter (full author CSS in Chromium) served with `device.INPUT_PAGE_CSS` inserted
  before `</body>` (after the author sheets): `html, body {margin-left/right, padding-left/right: 0
  !important}`, i.e. the author's intended look on a page whose side margins the device owns, so the
  percentage widths/margins of descendants resolve against the same content box as on the output
  (whose writer zeroes them on purpose). UTF-16/32 inputs or ones without `</body>`/`</html>` are
  loaded unchanged (`device_css_removed.input_page_not_injected`). margin-*/padding-* of
  `<html>`/`<body>` are not compared (page margins belong to the device). The preservation `score`
  reuses this same input load (see "Page-neutral preservation score"); only `score_page_dependent`
  uses the first, unmodified input load. `device_score` = equal / checked over the
  book, `device_per_chapter` per spine item, `device_prop_disagreements` / `device_prop_examples`
  as for `prop_disagreements`. It runs whenever the style pass runs (`--no-style` skips both).
- Visibility (`visibility`, and for AZW3 `device_visibility`): the style pass records, per element with
  text of its own, whether that text is rendered visibly; the input is compared with the output render
  (`visibility`) and with the device-model render (`device_visibility`), so a text that the input hides
  and the output shows (a writer pinning `h2 {display: block}` over the UA rule `[hidden] {display: none}`:
  Standard Ebooks' `<h2 hidden="hidden">` titles) or the reverse is reported, which neither the text
  invariant (visibility-blind) nor the style scores (they align on visible input elements) notice.
  - Rendered visibly = computed `visibility: visible`, a layout box for the text (so no `display:none` on
    the element or an ancestor; `display: contents` is measured on the text itself), not clipped away by
    the screen-reader patterns on the element or an ancestor (`clip: rect(..)` of at most 1 px under
    `position: absolute|fixed`, `clip-path: inset(..)` with the insets adding up to 100 % in a direction,
    `circle(0)`, a box of 1 px or less with `overflow` other than visible), and not positioned 500 px or
    more off the page (right/bottom edge above -500; left edge below viewport width + 500, which applies only
    to text that something positions: `position` other than static on the element or an ancestor, since text
    in normal flow far to the right is a wide table or an unwrapped `<pre>` line that overflows the page,
    not a hiding idiom). The input
    is measured with its author CSS (MOBI v6: also the elements the writer removes, which count as hidden);
    the MOBI output with MOBI_CSS applied like the style score.
  - Matching is by text, per spine item (aligned mode) or for the whole book (concat mode): text T of a
    hidden element (non-space characters, at least `VIS_MIN_CHARS` = 4) counts as changed when the other
    side's visible text (whitespace-free concatenation of the visible elements' own text) holds it more
    often than this side's visible text does: `min(hidden elements with T, count_B(T) - count_A(T))`.
    Text that is absent from the other side is text loss, not a visibility change; one visible as often on
    both sides cancels out. At most `VIS_MAX_TEXTS` = 2000 distinct hidden texts per unit are looked up
    (`texts_capped: true` when more).
  - `hidden_in_input_shown_out_chars|elements`: hidden in the input, visible in the output;
    `shown_in_input_hidden_out_*` the reverse (chars = non-space characters). `examples`: up to 5 per
    direction, `{chapter (spine index; null when unknown), text (<= 80 chars), chars}`. `visibility` is
    null with `visibility_error` when the pure-Python accounting failed, `device_visibility` null for MOBI
    and when the device pass failed.
  - Category `visibility-changed` (`report.VISIBILITY_MIN_CHARS` = 20): either direction above that many
    chars in `visibility` or `device_visibility`. compare.py: a regression when the summed chars of either
    render rise against a baseline that has the field.
- `input_css_rules`: rule blocks of the style sheets reachable from an XHTML spine document (`<link
  rel=stylesheet>` to CSS, i.e. not `.xpgt` and not another declared type; `<style>`; `@import` chains),
  `@font-face` blocks excluded (fonts are dropped by design). The same exclusion applies to
  `output_css_rules`. `input_css_rules_unreferenced`: the rest of the manifest's `text/css` items.

`layout_hygiene` (both formats; static, lxml, no browser, also with `--no-style`): counts over the
`<body>` of the output documents (KindleUnpack `mobi8/OEBPS/Text/part*.xhtml`, or the single mobi7
`book.html`); `layout_hygiene_input` the same over the input XHTML spine documents (before MOBI hidden
content is pruned). `device.layout_hygiene_doc`:
- `empty_blocks`: `<p>`/`<div>` with no element child, no text (ASCII whitespace only; U+00A0 is
  text) and no `id`; `<p><br/></p>` is not empty. One whose tag/class rule in the document's sheets
  (`device.marker_selectors`: last compound of the selector) or `style` attribute sets
  page-break-*/break-*, border*, background*, height/min-height, width, clear or padding (incl.
  -top/-bottom) is an intentional marker/spacer and counts as `empty_blocks_styled` instead.
- `trailing_breaks`: a `<br>` that is the last non-whitespace node of a p/div/li/h1-h6/blockquote/dd/dt
  (directly or through inline elements ending there too) whose nearest preceding non-whitespace
  content (looking back through inline wrappers; empty ones such as `<a id>` are passed over) is text
  or a non-`<br>` inline element (img, ...). `<p><br/></p>` (a blank line) and a `<br>` right after a
  block do not count; `text<br/><br/>` (the last `<br>` preceded by `<br>`s after content) counts as
  `trailing_breaks_double`.
- `whitespace_runs`: text nodes (text and tails, whitespace-only ones between blocks included) with a
  newline, tab, CR or two ASCII spaces in a row, outside pre/textarea/listing/plaintext/xmp and
  outside elements whose `style` attribute, or a rule of the document's sheets whose selector's last
  compound names their tag or class, sets `white-space: pre*`/`break-spaces` (an approximation: the
  rest of the selector is ignored). Text inside style/script/template/noscript and inline svg/math
  subtrees is not counted (not HTML text flow).
- `nbsp_indents`: p/div/li/dd/dt/h1-h6 whose text (leading ASCII whitespace ignored) starts with two
  or more U+00A0, counted on the innermost such block, and only in the unambiguous case the writer
  converts: no nested block element, no other line of the block (after a `<br>`) starting with U+00A0
  (verse), and the nbsp run not followed by a short non-letter mark (ditto, dash, ...) and more U+00A0
  (table-like columns). The excluded ones count as `nbsp_indents_ambiguous`.
- The `layout-hygiene` category and the report/compare "layout hygiene" rows use the four main
  counts only; `empty_blocks_styled`, `trailing_breaks_double`, `nbsp_indents_ambiguous` are shown
  in the report summary.
`documents` = documents counted, `examples` = up to 3 per count. A failure leaves both `null` and sets
`invariants.errors.layout_hygiene`.

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

# device.py (self-test: uv run tests/harness/test_device.py)
KINDLE_UA_CSS: str; DEVICE_MODEL: str
def device_css(css: str, stats: Counter | None = None) -> str        # device-model rewrite of one sheet
def device_document(data: bytes, stats: Counter | None = None) -> bytes  # UA sheet first, <style> rewritten
def layout_hygiene_doc(body, pre=(set(), set()), counts=None, examples=None, doc="") -> Counter

# calibre_diff.py
def diff(entry: dict, out_dir: Path, fmt: str) -> dict

# compare.py: a rise of the chars that changed visibility (style.visibility / device_visibility) is a regression
# (the metric rows "visibility changed, pooled chars", "n/a" on a baseline without the field);
# a device_score drop > STYLE_TOL is a regression like the style score; a baseline result
# without device_score / layout_hygiene shows "n/a" and gets no "new category" for device-style-lost /
# layout-hygiene (CAT_FIELD); layout-hygiene is informational.

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
| device-style-lost | (AZW3 only) style.device_score < 0.8 (`report.DEVICE_STYLE_MIN`) | unported transform (oeb flatcss: cascade baked into classes, UA defaults pinned) |
| visibility-changed | `style.visibility` or `style.device_visibility`: more than 20 chars (`report.VISIBILITY_MIN_CHARS`) of text hidden in the input and shown in the output, or the reverse | unported transform (oeb flatcss / UA rules: hidden elements stay hidden) |
| layout-hygiene | any output layout_hygiene count > 0 | informational |
| fixed-layout-unsupported | `invariants.fixed_layout`: input OPF has rendition:layout pre-paginated; the book's other categories become out of scope | out of scope |
| calibre-header-diff | header_fields_diff non-empty beyond the ignore list | informational |
| input-repair | app-error, a clean app error, or text-loss on a book Calibre converted fine and whose verdict is error/warning | input repair |
| harness-error | `harness:` error in app/calibre/gate meta, missing app meta, or `invariants.errors.harness` | harness (not counted) |
