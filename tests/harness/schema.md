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
               "first_diff": {"item": 0, "ours_excerpt": "", "input_excerpt": ""}},
    "images": {"input": 0, "output": 0, "matched_by_hash": 0, "dimension_mismatch": 0},
    "toc":    {"input_entries": 0, "output_entries": 0, "matched": 0, "depth_in": 0, "depth_out": 0},
    "links":  {"internal_total": 0, "resolved": 0},
    "style":  {"score": 0.0, "per_chapter": [0.0]}
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
| text-loss | matching_items < spine_items | transform or repair, decided in report |
| text-garbled | more U+FFFD in our text than in the input's, or CSS rules in our body text but not in the input's | writer bug |
| images-missing | `images.missing` > 0: referenced input images (plus cover) neither present by hash nor present-but-changed | unported Calibre transform (mobi.utils / writer8 resources) |
| images-resized | dimension_mismatch > 0 | informational |
| images-misreferenced | refs_total > 0 and (refs_wrong_image > 0 or refs_missing > 0) | writer bug |
| toc-missing | input_entries > 0 and output_entries == 0 | unported transform (writer8 toc) |
| toc-flat | depth_out < depth_in | unported transform (writer8 index NCX) |
| toc-labels | matched < min(input, output) | writer bug |
| links-unresolved | resolved < internal_total | unported transform (writer8 main: internal links) |
| style-lost | style.score < 0.5, or (AZW3 only) input_css_rules > 0 and output_css_rules == 0 | unported transform (writer8 main: css flows / oeb flatcss) |
| fixed-layout-unsupported | `invariants.fixed_layout`: input OPF has rendition:layout pre-paginated; the book's other categories become out of scope | out of scope |
| calibre-header-diff | header_fields_diff non-empty beyond the ignore list | informational |
| input-repair | app-error, a clean app error, or text-loss on a book Calibre converted fine and whose verdict is error/warning | input repair |
| harness-error | `harness:` error in app/calibre/gate meta, missing app meta, or `invariants.errors.harness` | harness (not counted) |
