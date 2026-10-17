"""Corpus preparation for the differential quality harness (standard library only).

    uv run --python 3.13 tests/harness/corpus.py

Builds tests/corpus/manifest.json (list of BookEntry dicts, see schema.md) from:
  tests/corpus/core/<folder>/*.epub      unpacked from epubs/epub-corpus-core.zip, or rebuilt from the
  tests/corpus/heavy/<folder>/*.epub     upstream GitHub repos by fetch_spec() (heavy = files > 2 MB)
  tests/corpus/realworld/{standard-ebooks,gutenberg}/*.epub
  tests/corpus/generated/*.epub          synthetic mutated books (generate_cases)
  <repo root>/Oorlog en terpentijn - Stefan Hertmans.epub

The files under tests/corpus/ are untrusted downloads: nothing in them is ever executed here;
they are only hashed, and zip archives are extracted with zipfile (which sanitises member paths).

Spec corpora without the private zips: `prepare(fetch=True)` or `prepare(spec=True)` (CLI:
`cli.py prepare --fetch-spec`, spec corpora only; `--fetch` also downloads the real-world books) call
fetch_spec() when core/ or heavy/ has no .epub and the matching epubs/epub-corpus-<name>.zip is absent.

Byte-identical books (same sha256) share one working directory tests/corpus/out/<sha256>/, so the
manifest keeps one entry per sha256: the first by id, with the ids of the others in `aliases`.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import ROOT, sha256_file

HARNESS_DIR = Path(__file__).resolve().parent

CATEGORIES = {"idpf", "w3c", "epubcheck-valid", "epubcheck-warnings", "epubcheck-invalid",
              "epubcheck-other", "se", "pg", "generated", "local"}

LOCAL_BOOK = "Oorlog en terpentijn - Stefan Hertmans.epub"

# folder name -> (category, source_url, license_note)
_FOLDER_INFO = {
    "01-idpf-samples": ("idpf", "https://github.com/IDPF/epub3-samples", "CC-BY-SA (IDPF epub3-samples)"),
    "02-w3c-conformance": ("w3c", "https://github.com/w3c/epub-tests", "W3C Test Suite License (epub-tests)"),
    "03-epubcheck-valid": ("epubcheck-valid", "https://github.com/w3c/epubcheck", "BSD-3 (epubcheck test resources)"),
    "03-epubcheck-warnings": ("epubcheck-warnings", "https://github.com/w3c/epubcheck", "BSD-3 (epubcheck test resources)"),
    "03-epubcheck-invalid": ("epubcheck-invalid", "https://github.com/w3c/epubcheck", "BSD-3 (epubcheck test resources)"),
    "03-epubcheck-other": ("epubcheck-other", "https://github.com/w3c/epubcheck", "BSD-3 (epubcheck test resources)"),
}

# epubcheck filename suffix -> verdict
_SUFFIX_VERDICT = {"valid": "valid", "warning": "warning", "usage": "warning",
                   "error": "error", "fatal": "error"}
# fallback when the suffix is not one of the above, by folder category
_FOLDER_VERDICT = {"epubcheck-valid": "valid", "epubcheck-warnings": "warning",
                   "epubcheck-invalid": "error", "epubcheck-other": "unknown"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _epubs_in(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() == ".epub") if d.is_dir() else []


def _unpack(zip_path: Path, dest: Path) -> None:
    if not zip_path.exists():
        print(f"corpus: {zip_path} missing, cannot unpack", file=sys.stderr)
        return
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)  # zipfile strips absolute paths and '..' components


def _epubcheck_verdict(basename: str, category: str) -> str:
    m = re.search(r"-([a-z]+)$", basename)
    if m and m.group(1) in _SUFFIX_VERDICT:
        return _SUFFIX_VERDICT[m.group(1)]
    return _FOLDER_VERDICT.get(category, "unknown")


def _read_sources(root: Path) -> dict[str, tuple[str, str]]:
    """sources.tsv: '<folder>/<file>\\t<url>\\t<licence>' -> {relpath: (url, licence)}"""
    out: dict[str, tuple[str, str]] = {}
    f = root / "tests/corpus/realworld/sources.tsv"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                out[parts[0]] = (parts[1], parts[2])
    return out


# ── manifest ─────────────────────────────────────────────────────────────────

def _entry(root: Path, path: Path, id_: str, category: str, verdict: str, url: str, lic: str,
           subset: str) -> dict:
    return {
        "id": id_,
        "path": path.relative_to(root).as_posix(),
        "sha256": "",  # filled in after (parallel) hashing
        "size_bytes": path.stat().st_size,
        "category": category,
        "expected_verdict": verdict,
        "source_url": url,
        "license_note": lic,
        "subset": subset,
    }


def prepare(root: Path = ROOT, *, se: int = 100, pg: int = 100, fetch: bool = False,
            spec: bool = False) -> list[dict]:
    """Regenerate tests/corpus/manifest.json.

    core/ and heavy/ are filled, if they hold no .epub yet, from epubs/epub-corpus-<name>.zip when that
    exists. When it does not, and `fetch` or `spec` is set, fetch_spec() rebuilds them from the upstream
    GitHub repos (three archive downloads, cached under tests/corpus/tools/src/, resumable). `fetch` also
    downloads the real-world books (Standard Ebooks + Gutenberg, 1 request/s); `spec` does only the spec
    corpora. Without either flag nothing is downloaded and a hint is printed.
    """
    root = Path(root)
    corpus = root / "tests/corpus"
    corpus.mkdir(parents=True, exist_ok=True)

    missing = []
    for name in ("core", "heavy"):
        if not _epubs_in(corpus / name):
            zip_path = root / f"epubs/epub-corpus-{name}.zip"
            if zip_path.exists():
                _unpack(zip_path, corpus / name)
            else:
                missing.append(name)
    if missing:
        if fetch or spec:
            fetch_spec(root)
        else:
            print(f"corpus: no .epub in {' and '.join(f'tests/corpus/{m}/' for m in missing)} and no private "
                  "zip; run `prepare --fetch-spec` to rebuild them from the upstream repos", file=sys.stderr)

    if fetch:
        fetch_realworld(root, se=se, pg=pg)
    generate_cases(root)

    entries: list[dict] = []

    # core / heavy
    for subset in ("core", "heavy"):
        base = corpus / subset
        for p in _epubs_in(base):
            rel = p.relative_to(base)
            folder = rel.parts[0] if len(rel.parts) > 1 else ""
            info = _FOLDER_INFO.get(folder)
            if info is None:
                category, url, lic = "epubcheck-other", "", "unknown"
            else:
                category, url, lic = info
            basename = p.stem
            if category in ("idpf", "w3c"):
                verdict = "valid"
            else:
                verdict = _epubcheck_verdict(basename, category)
            id_ = "/".join([subset, *rel.parts[:-1], basename])
            entries.append(_entry(root, p, id_, category, verdict, url, lic, subset))

    # real-world
    sources = _read_sources(root)
    rw = corpus / "realworld"
    for sub, category in (("standard-ebooks", "se"), ("gutenberg", "pg")):
        for p in _epubs_in(rw / sub):
            if not zipfile.is_zipfile(p):  # partial download still in flight
                print(f"corpus: skipping incomplete download {p.name}", file=sys.stderr)
                continue
            url, lic = sources.get(f"{sub}/{p.name}", ("unknown", "unknown"))
            entries.append(_entry(root, p, f"real/{sub}/{p.stem}", category, "valid", url, lic, "real"))

    # generated
    for p in _epubs_in(corpus / "generated"):
        verdict = _GENERATED_VERDICT.get(p.stem, "unknown")
        entries.append(_entry(root, p, f"generated/{p.stem}", "generated", verdict,
                              "tests/epub_fixtures.py", "generated by tests/harness/corpus.py (this repo)",
                              "generated"))

    # local reference book
    local = root / LOCAL_BOOK
    if local.exists():
        entries.append(_entry(root, local, "local/hertmans", "local", "valid", "",
                              "user-owned reference book, not redistributed", "local"))

    with ThreadPoolExecutor(max_workers=8) as ex:  # hashlib releases the GIL on big buffers
        for e, digest in zip(entries, ex.map(lambda e: sha256_file(root / e["path"]), entries)):
            e["sha256"] = digest

    entries.sort(key=lambda e: e["id"])
    ids = [e["id"] for e in entries]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        raise RuntimeError(f"duplicate manifest ids: {dupes[:5]}")
    entries = _dedupe_by_sha(entries)
    (corpus / "manifest.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    return entries


def _dedupe_by_sha(entries: list[dict]) -> list[dict]:
    """One entry per sha256: the first by id, unless a later one has a known expected_verdict
    (valid/warning/error) and the first does not; the other ids go into its `aliases` list."""
    def known(e: dict) -> bool:
        return e.get("expected_verdict") in ("valid", "warning", "error")

    groups: dict[str, list[dict]] = {}
    for e in entries:  # sorted by id
        groups.setdefault(e["sha256"], []).append(e)
    out = []
    for g in groups.values():
        keep = next((e for e in g if known(e)), g[0])
        keep["aliases"] = [e["id"] for e in g if e is not keep] + keep.get("aliases", [])
        if not keep["aliases"]:
            del keep["aliases"]
        out.append(keep)
    out.sort(key=lambda e: e["id"])
    n_alias = sum(len(e.get("aliases", [])) for e in out)
    if n_alias:
        print(f"corpus: {n_alias} byte-identical duplicate(s) folded into `aliases` of "
              f"{sum(1 for e in out if e.get('aliases'))} entr(y/ies)", file=sys.stderr)
    return out


def load_manifest(root: Path = ROOT) -> list[dict]:
    return json.loads((Path(root) / "tests/corpus/manifest.json").read_text(encoding="utf-8"))


# ── real-world fetching (port of fetch_realworld.sh) ─────────────────────────

_UA = "epub2azw3-corpus-fetch/1.0 (+https://github.com/Ken-B/epub-to-kindle; polite, 1 req/s)"
_PG_CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"


def _get(url: str) -> bytes | None:
    """GET with the polite UA; None on any failure (like `curl -sfL`). Caller sleeps 1 s."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _is_epub_file(f: Path) -> bool:
    """Non-empty, valid zip (an earlier fetch stored HTML interstitial pages under .epub names)."""
    return f.is_file() and f.stat().st_size > 0 and zipfile.is_zipfile(f)


def _count_epubs(d: Path) -> int:
    return sum(1 for p in d.glob("*.epub") if _is_epub_file(p)) if d.is_dir() else 0


def _save(f: Path, data: bytes) -> None:
    tmp = f.with_name(f.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(f)


def fetch_realworld(root: Path = ROOT, *, se: int = 100, pg: int = 100) -> None:
    out = Path(root) / "tests/corpus/realworld"
    (out / "standard-ebooks").mkdir(parents=True, exist_ok=True)
    (out / "gutenberg").mkdir(parents=True, exist_ok=True)
    manifest = out / "sources.tsv"
    manifest.touch()

    def record(rel: str, url: str, lic: str) -> None:
        lines = manifest.read_text(encoding="utf-8").splitlines()
        lines = [ln for ln in lines if ln.split("\t")[0] != rel]  # replace any stale row
        lines.append(f"{rel}\t{url}\t{lic}")
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Standard Ebooks: OPDS is patron-only, so walk the public catalog pages.
    have_se = _count_epubs(out / "standard-ebooks")
    page = 1
    while have_se < se and page <= 40:
        raw = _get(f"https://standardebooks.org/ebooks?page={page}&sort=newest"); time.sleep(1)
        if not raw:
            print(f"SE: listing page {page} failed"); break
        listing = raw.decode("utf-8", "replace")
        slugs = sorted(set(re.findall(r'href="(/ebooks/[^"/]*/[^"/]*)"', listing)))
        if not slugs:
            print(f"SE: no slugs on page {page}"); break
        for s in slugs:
            if have_se >= se:
                break
            name = s.removeprefix("/ebooks/").replace("/", "_") + ".epub"
            f = out / "standard-ebooks" / name
            if _is_epub_file(f):
                continue
            raw = _get("https://standardebooks.org" + s); time.sleep(1)
            hrefs = [h for h in re.findall(r'href="([^"]*/downloads/[^"]*\.epub[^"]*)"', (raw or b"").decode("utf-8", "replace"))
                     if "_advanced" not in h and "kepub" not in h]
            if not hrefs:
                print(f"SE: no epub link for {s}"); continue
            href = hrefs[0]
            if href.startswith("/"):
                href = "https://standardebooks.org" + href
            if "?" not in href:
                href += "?source=download"  # without it the server answers with an HTML interstitial page
            data = _get(href)
            if data and data[:2] == b"PK":
                _save(f, data)
                record(f"standard-ebooks/{name}", href, "CC0 (Standard Ebooks)")
                have_se += 1
                print(f"SE {have_se}/{se} {name}")
            else:
                print(f"SE: download failed {href}")
            time.sleep(1)
        page += 1

    # Project Gutenberg: random IDs from the offline catalog CSV (Type=Text), 80% en / 20% other.
    have_pg = _count_epubs(out / "gutenberg")
    catalog = out / "pg_catalog.csv"
    if not catalog.exists():
        data = _get(_PG_CATALOG_URL); time.sleep(1)
        if data:
            _save(catalog, data)
    if catalog.exists() and have_pg < pg:
        random.seed(42)
        with open(catalog, encoding="utf-8", errors="replace", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("Type") == "Text"]
        en = [r["Text#"] for r in rows if r.get("Language") == "en"]
        other = [r["Text#"] for r in rows if r.get("Language") != "en"]
        k = int(pg * 0.8)
        ids = random.sample(en, k * 3) + random.sample(other, (pg - k) * 3)  # 3x oversample
        for id_ in ids:
            if have_pg >= pg:
                break
            f = out / "gutenberg" / f"pg{id_}.epub"
            if _is_epub_file(f):
                continue
            url = f"https://www.gutenberg.org/cache/epub/{id_}/pg{id_}-images-3.epub"
            data = _get(url); time.sleep(1)
            if not data or data[:2] != b"PK":
                url = f"https://www.gutenberg.org/cache/epub/{id_}/pg{id_}-images.epub"
                data = _get(url)
                if not data or data[:2] != b"PK":
                    time.sleep(1); continue
            _save(f, data)
            record(f"gutenberg/pg{id_}.epub", url, "Public domain (Project Gutenberg License)")
            have_pg += 1
            print(f"PG {have_pg}/{pg} pg{id_}")
            time.sleep(1)
    print(f"DONE standard-ebooks={_count_epubs(out / 'standard-ebooks')} gutenberg={_count_epubs(out / 'gutenberg')}")


# ── spec corpora (core/ + heavy/) rebuilt from the upstream repos ─────────────

# repo -> (owner/name, branch, pinned commit). The pinned sha makes the rebuilt set (and, with the fixed
# timestamps below, the packed bytes) reproducible; set it to None to follow the branch head instead.
_SPEC_REPOS = {
    "epub3-samples": ("IDPF/epub3-samples", "main", "7651e2002b631e6577fadf7e9e0692fa6efb8746"),
    "epub-tests": ("w3c/epub-tests", "main", "54092b4233253e9aac80e93ec4782b380b4b3403"),
    "epubcheck": ("w3c/epubcheck", "main", "0cc28fb25fdb3cc7455f029e53afe9e00d7ae607"),
}
_HEAVY_BYTES = 2 * 1024 * 1024  # packed books above this go to heavy/ (same limit as default_timeout)
_EPUBCHECK_RES = "src/test/resources/"


def _download(url: str, dest: Path) -> None:
    """Stream url to dest (via dest.part). One archive download, so no politeness delay is needed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as fh:
                while chunk := r.read(1 << 20):
                    fh.write(chunk)
            if not zipfile.is_zipfile(part):
                raise OSError("download is not a zip archive")
            part.replace(dest)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    part.unlink(missing_ok=True)
    raise RuntimeError(f"download failed: {url}: {last}")


def _spec_archive(root: Path, repo: str, force: bool = False) -> Path:
    """Path of the (cached) codeload zip of a repo, each in its own directory under tools/src/."""
    slug, branch, sha = _SPEC_REPOS[repo]
    ref = sha or branch
    ref_path = ref if sha else f"refs/heads/{branch}"
    dest = root / "tests/corpus/tools/src" / repo / f"{repo}-{ref}.zip"
    if force or not (dest.exists() and zipfile.is_zipfile(dest)):
        url = f"https://codeload.github.com/{slug}/zip/{ref_path}"
        t0 = time.time()
        print(f"corpus: downloading {url}")
        _download(url, dest)
        print(f"corpus:   {dest.stat().st_size / 1e6:.1f} MB in {time.time() - t0:.0f}s")
    return dest


def _is_hidden(name: str) -> bool:
    return any(part.startswith(".") for part in name.split("/") if part)


class _SpecArchive:
    """Read-only view of a GitHub source archive; paths are relative to its single top-level directory.
    Members are only ever read with zipfile (never extracted), so a hostile path cannot escape."""

    def __init__(self, path: Path):
        self.zf = zipfile.ZipFile(path)
        top = {n.split("/", 1)[0] for n in self.zf.namelist()}
        if len(top) != 1:
            raise RuntimeError(f"{path.name}: expected a single top-level directory, got {sorted(top)[:3]}")
        self.top = top.pop() + "/"
        self.files = {i.filename[len(self.top):]: i for i in self.zf.infolist()
                      if not i.is_dir() and i.filename.startswith(self.top)}

    def roots(self, under: str = "") -> list[str]:
        """Directories below `under` that are an unpacked EPUB, outermost only: they hold
        META-INF/container.xml (a missing `mimetype` file is a legitimate test case and still packs; a
        directory with a mimetype but no container.xml is not an openable book and is skipped)."""
        tail = "/META-INF/container.xml"
        found = {n[:-len(tail)] for n in self.files if n.startswith(under) and n.endswith(tail)
                 and not _is_hidden(n)}
        return sorted(r for r in found if not any(r.startswith(o + "/") for o in found if o != r))

    def prebuilt(self, under: str = "") -> list[str]:
        """Prebuilt *.epub files (exact lower-case extension: epubcheck also keeps `x.ePub` fixtures to
        test extension handling; those are not part of this corpus)."""
        return sorted(n for n in self.files if n.startswith(under) and n.endswith(".epub")
                      and not _is_hidden(n))

    def read_dir(self, root: str) -> dict[str, bytes]:
        prefix = root + "/"
        return {n[len(prefix):]: self.zf.read(i) for n, i in self.files.items()
                if n.startswith(prefix) and not _is_hidden(n[len(prefix):])}

    def pack(self, root: str, dest: Path) -> None:
        """Pack directory `root` into an EPUB at dest: mimetype first and STORED, the rest DEFLATED, sorted,
        fixed timestamps, hidden files skipped."""
        prefix = root + "/"
        rel = sorted(((n[len(prefix):], n) for n in self.files
                      if n.startswith(prefix) and not _is_hidden(n[len(prefix):])),
                     key=lambda t: (t[0] != "mimetype", t[0]))
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
            for name, full in rel:
                zi = zipfile.ZipInfo(name, _FIXED_DATE)
                zi.create_system = 3
                zi.external_attr = 0o644 << 16
                zi.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                out.writestr(zi, self.zf.read(self.files[full]))

    def copy(self, name: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.zf.read(self.files[name]))


def _epubcheck_section_test(rel: str) -> tuple[str, str]:
    """Directory below src/test/resources/ -> (section, test name), e.g.
    'epub3/07-content-documents/files/foo' -> ('epub3_07-content-documents', 'foo'),
    'epub-edupub/files/epub/foo' -> ('epub-edupub', 'foo'). Directories outside a files/ tree use their whole
    path as the section: 'stress' -> ('stress', 'stress'), 'epub3/test-files-unused/foo' ->
    ('epub3_test-files-unused_foo', 'foo') (names of the original private corpus)."""
    parts = rel.split("/")
    if "files" in parts[:-1]:
        i = parts.index("files")
        tree, rest = parts[:i], parts[i + 1:]
        if len(rest) > 1 and rest[0] == "epub":  # <feature>/files/epub/<test>: 'epub' is just a container
            rest = rest[1:]
        return "_".join(tree), "_".join(rest)
    return "_".join(parts), parts[-1]


def _epubcheck_folder(test: str) -> str:
    """Folder by verdict word: the name's suffix (`...-valid`), else any `-valid-`/`-warning-` style token
    in the name (cli__30-valid-test, cli__20-warning-tester). `invalid` is a different token from `valid`."""
    tokens = re.split(r"[-_]", test)
    for word in (tokens[-1], *tokens):
        if word == "valid":
            return "03-epubcheck-valid"
        if word in ("warning", "usage"):
            return "03-epubcheck-warnings"
        if word in ("error", "fatal"):
            return "03-epubcheck-invalid"
    return "03-epubcheck-other"


def _signature(files: dict[str, bytes]) -> frozenset:
    return frozenset((n, hashlib.sha256(b).hexdigest()) for n, b in files.items())


def fetch_spec(root: Path, *, force: bool = False) -> None:
    """Rebuild tests/corpus/core/<folder>/ and tests/corpus/heavy/<folder>/ without the private zips.

    Downloads the three GitHub source archives (pinned commits, see _SPEC_REPOS) to
    tests/corpus/tools/src/<repo>/, reads them with zipfile only, and writes EPUBs:
      01-idpf-samples      IDPF/epub3-samples: prebuilt .epub files if the repo ships any (it does not),
                           else every directory <sample>/ holding META-INF + mimetype under 30/
      02-w3c-conformance   w3c/epub-tests: every tests/<feature>/ directory, one feature per book
      03-epubcheck-*       w3c/epubcheck src/test/resources: every unpacked EPUB directory becomes
                           <section>__<test>.epub (section = feature/tree path with '/' -> '_', as in
                           epub3_07-content-documents__foo); folder by test-name suffix: -valid -> valid,
                           -warning/-usage -> warnings, -error/-fatal -> invalid, else other (a `-valid-`
                           or `-warning-` token elsewhere in the name counts too). Directories without
                           META-INF/container.xml, and ones identical to a prebuilt fixture, are skipped.
                           Prebuilt .epub fixtures are copied under their own name into 03-epubcheck-other.
    Packing is deterministic (mimetype first and stored, rest deflated, sorted, fixed timestamps, hidden
    files skipped). Books above 2 MB go to heavy/<folder>/, the rest to core/<folder>/.
    Resumable: a book that already exists in core/ or heavy/ is skipped unless force=True, and cached
    archives are reused (force=True downloads them again).
    """
    root = Path(root)
    corpus = root / "tests/corpus"
    jobs: list[tuple[str, str, bool, _SpecArchive, str]] = []  # (folder, name, pack?, archive, source path)
    seen: dict[tuple[str, str], str] = {}

    def add(folder: str, name: str, pack: bool, arc: _SpecArchive, src: str) -> None:
        if (folder, name) in seen:  # e.g. several minimal.epub fixtures: keep the first, say so
            print(f"corpus: {folder}/{name}.epub from {src} dropped (already provided by "
                  f"{seen[folder, name]})", file=sys.stderr)
            return
        seen[folder, name] = src
        jobs.append((folder, name, pack, arc, src))

    t0 = time.time()
    samples = _SpecArchive(_spec_archive(root, "epub3-samples", force))
    pre = [n for n in samples.prebuilt() if not n.startswith("lib/")]
    for n in pre:
        add("01-idpf-samples", Path(n).stem, False, samples, n)
    if not pre:
        for r in samples.roots("30/"):
            add("01-idpf-samples", r.rsplit("/", 1)[-1], True, samples, r)

    tests = _SpecArchive(_spec_archive(root, "epub-tests", force))
    for r in tests.roots("tests/"):
        add("02-w3c-conformance", r.rsplit("/", 1)[-1], True, tests, r)

    check = _SpecArchive(_spec_archive(root, "epubcheck", force))
    prebuilt = check.prebuilt(_EPUBCHECK_RES)
    twins: dict[str, frozenset] = {}  # prebuilt fixtures by name -> content, to spot unpacked duplicates
    for n in prebuilt:
        try:
            with zipfile.ZipFile(io.BytesIO(check.zf.read(check.files[n]))) as z:
                twins[Path(n).stem] = _signature({i.filename: z.read(i) for i in z.infolist() if not i.is_dir()})
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError):
            pass  # deliberately corrupt fixture
    for r in check.roots(_EPUBCHECK_RES):
        section, test = _epubcheck_section_test(r[len(_EPUBCHECK_RES):])
        if test in twins and twins[test] == _signature(check.read_dir(r)):
            print(f"corpus: {r} skipped (same content as the prebuilt {test}.epub)", file=sys.stderr)
            continue
        add(_epubcheck_folder(test), f"{section}__{test}", True, check, r)
    for n in prebuilt:
        add("03-epubcheck-other", Path(n).stem, False, check, n)

    done = skipped = 0
    for folder, name, pack, arc, src in jobs:
        core_f = corpus / "core" / folder / f"{name}.epub"
        heavy_f = corpus / "heavy" / folder / f"{name}.epub"
        if not force and (core_f.exists() or heavy_f.exists()):
            skipped += 1
            continue
        part = core_f.with_name(core_f.name + ".part")  # never a *.epub until complete
        (arc.pack if pack else arc.copy)(src, part)
        final = heavy_f if part.stat().st_size > _HEAVY_BYTES else core_f
        for stale in (core_f, heavy_f):  # force: the book may land in the other tier than before
            stale.unlink(missing_ok=True)
        final.parent.mkdir(parents=True, exist_ok=True)
        part.replace(final)
        done += 1
    print(f"corpus: spec corpora: {done} written, {skipped} already present, {len(jobs)} total "
          f"({time.time() - t0:.0f}s)")


# ── generated cases ──────────────────────────────────────────────────────────

_GENERATED_VERDICT = {
    "gen-missing-ncx": "error",
    "gen-wrong-media-types": "error",
    "gen-item-not-in-manifest": "error",
    "gen-unterminated-tag": "error",
    "gen-latin1-declared": "valid",
    "gen-latin1-undeclared": "error",
    "gen-duplicate-ids": "error",
    "gen-footnotes-ok": "valid",
}

_FIXED_DATE = (2024, 1, 1, 0, 0, 0)

_NCX = '''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="test-uid-001"/></head>
  <docTitle><text>Generated Test Book</text></docTitle>
  <navMap>
    <navPoint id="np1" playOrder="1"><navLabel><text>Chapter 1</text></navLabel><content src="chapter01.xhtml"/></navPoint>
    <navPoint id="np2" playOrder="2"><navLabel><text>Chapter 2</text></navLabel><content src="chapter02.xhtml"/></navPoint>
    <navPoint id="np3" playOrder="3"><navLabel><text>Chapter 3</text></navLabel><content src="chapter03.xhtml"/></navPoint>
  </navMap>
</ncx>'''

_NCX_ITEM = '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'


def _xhtml(title: str, body: str, decl: str = '<?xml version="1.0" encoding="UTF-8"?>\n') -> str:
    return (f'{decl}<html xmlns="http://www.w3.org/1999/xhtml">\n'
            f'<head><title>{title}</title><meta charset="utf-8"/>'
            f'<link rel="stylesheet" href="style.css" type="text/css"/></head>\n'
            f'<body>{body}</body>\n</html>')


def _base_chapters() -> list[tuple[str, str]]:
    return [(f"Chapter {i}", (f"<h1>Chapter {i}</h1>\n<p>Paragraph one of chapter {i}, with <em>emphasis</em>.</p>\n"
                              f"<p class=\"note\">Paragraph two of chapter {i}.</p>")) for i in (1, 2, 3)]


def _base_files(chapters: list[tuple[str, str]] | None = None, with_ncx: bool = True) -> dict[str, bytes]:
    """Return {zip member name: bytes} of a 3-chapter EPUB 2 with css, a PNG and (optionally) toc.ncx."""
    if str(HARNESS_DIR.parent) not in sys.path:
        sys.path.insert(0, str(HARNESS_DIR.parent))
    from epub_fixtures import MINIMAL_PNG, make_epub  # type: ignore

    data = make_epub("Generated Test Book", chapters or _base_chapters(), version="2.0",
                     css_rules=[("p.note", "font-style: italic"), ("h1", "font-weight: bold")],
                     images=[("pixel.png", MINIMAL_PNG)])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = {n: z.read(n) for n in z.namelist()}
    if with_ncx:
        files["OEBPS/toc.ncx"] = _NCX.encode()
        opf = files["OEBPS/content.opf"].decode()
        opf = opf.replace("<manifest>\n    ", "<manifest>\n    " + _NCX_ITEM + "\n    ", 1)
        opf = opf.replace("<spine>", '<spine toc="ncx">', 1)
        files["OEBPS/content.opf"] = opf.encode()
    return files


def _write_epub(path: Path, files: dict[str, bytes]) -> None:
    """Write files as a zip with 'mimetype' first and stored; fixed timestamps for stable hashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        mi = zipfile.ZipInfo("mimetype", _FIXED_DATE)
        mi.compress_type = zipfile.ZIP_STORED
        z.writestr(mi, files["mimetype"])
        for name, data in files.items():
            if name == "mimetype":
                continue
            zi = zipfile.ZipInfo(name, _FIXED_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)


def _edit(files: dict[str, bytes], name: str, fn) -> None:
    files[name] = fn(files[name].decode("utf-8")).encode("utf-8")


def generate_cases(root: Path = ROOT) -> list[Path]:
    out = Path(root) / "tests/corpus/generated"
    out.mkdir(parents=True, exist_ok=True)
    OPF = "OEBPS/content.opf"
    cases: dict[str, dict[str, bytes]] = {}

    # missing NCX: toc.ncx, its manifest item and spine@toc removed
    f = _base_files()
    del f["OEBPS/toc.ncx"]
    _edit(f, OPF, lambda s: s.replace(_NCX_ITEM + "\n    ", "").replace(' toc="ncx"', ""))
    cases["gen-missing-ncx"] = f

    # wrong media types: chapters as text/plain, css as text/html
    f = _base_files()
    _edit(f, OPF, lambda s: s.replace('media-type="application/xhtml+xml"', 'media-type="text/plain"')
                             .replace('media-type="text/css"', 'media-type="text/html"'))
    cases["gen-wrong-media-types"] = f

    # extra chapter in zip and spine but not in the manifest
    f = _base_files()
    f["OEBPS/chapter04.xhtml"] = _xhtml("Chapter 4", "<h1>Chapter 4</h1>\n<p>Orphan chapter not in the manifest.</p>").encode()
    _edit(f, OPF, lambda s: s.replace("</spine>", '  <itemref idref="ch04"/>\n  </spine>'))
    cases["gen-item-not-in-manifest"] = f

    # chapter 2 never closes its tags
    ch = _base_chapters()
    ch[1] = ("Chapter 2", "<p><em>unterminated text with no closing tags")
    cases["gen-unterminated-tag"] = _base_files(ch)

    # Latin-1 bytes, declared and undeclared
    latin_body = "<h1>Chapter 2</h1>\n<p>Café crème, über été: é è ü.</p>"
    f = _base_files()
    f["OEBPS/chapter02.xhtml"] = _xhtml("Chapter 2", latin_body, '<?xml version="1.0" encoding="ISO-8859-1"?>\n') \
        .replace('<meta charset="utf-8"/>', '<meta charset="ISO-8859-1"/>').encode("latin-1")
    cases["gen-latin1-declared"] = f
    f = _base_files()
    f["OEBPS/chapter02.xhtml"] = _xhtml("Chapter 2", latin_body, "").encode("latin-1")  # no declaration, claims utf-8
    cases["gen-latin1-undeclared"] = f

    # duplicate ids with a link to the duplicated fragment
    ch = _base_chapters()
    ch[1] = ("Chapter 2", ('<h1>Chapter 2</h1>\n<p id="note1">First note.</p>\n<p id="note1">Second note, same id.</p>\n'
                           '<p>See <a href="#note1">the note</a>.</p>'))
    cases["gen-duplicate-ids"] = _base_files(ch)

    # valid cross-chapter footnote links (measures link rewriting)
    ch = _base_chapters()
    ch[0] = ("Chapter 1", '<h1>Chapter 1</h1>\n<p>Text with a footnote<a id="ref1" href="chapter03.xhtml#fn1">[1]</a>.</p>')
    ch[2] = ("Chapter 3", ('<h1>Chapter 3</h1>\n<p>Closing text.</p>\n'
                           '<p id="fn1">Footnote one. <a href="chapter01.xhtml#ref1">back</a></p>'))
    cases["gen-footnotes-ok"] = _base_files(ch)

    paths = []
    for name, files in cases.items():
        p = out / f"{name}.epub"
        _write_epub(p, files)
        paths.append(p)
    return paths


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    entries = prepare(ROOT, fetch=False)
    print(f"manifest: {len(entries)} entries -> tests/corpus/manifest.json")
    print("by category:")
    for k, v in sorted(Counter(e["category"] for e in entries).items()):
        print(f"  {k:20s} {v}")
    print("by subset:")
    for k, v in sorted(Counter(e["subset"] for e in entries).items()):
        print(f"  {k:20s} {v}")
    print("by expected_verdict:")
    for k, v in sorted(Counter(e["expected_verdict"] for e in entries).items()):
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()
