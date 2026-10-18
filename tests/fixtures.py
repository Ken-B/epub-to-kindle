"""
Shared fixture books for the legacy test suites (test_e2e, test_browser, test_calibre_compare).

  fixture(name)              -> Path of the named book; downloads it once into tests/corpus/fixtures/
                                (gitignored via tests/corpus/). Raises FixtureUnavailable when it cannot.
  try_fixture(name, section) -> Path, or None after printing a loud `SKIP: <section> (<reason>)` line
  skip(section, reason)      -> print the SKIP line and count it
  skip_count()               -> number of skips so far (for the final `N passed, M failed, K skipped`)

Downloads come from Project Gutenberg at 1 request/s with a browser-like User-Agent, are resumable
(a `.part` file plus an HTTP Range request) and are validated as a zip before they are used.
"""
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / 'corpus' / 'fixtures'

_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) '
       'Version/17.0 Safari/605.1.15')

def _gutenberg(id_, *, images=False):
    if images:
        return [f'https://www.gutenberg.org/cache/epub/{id_}/pg{id_}-images-3.epub',
                f'https://www.gutenberg.org/cache/epub/{id_}/pg{id_}-images.epub']
    return [f'https://www.gutenberg.org/ebooks/{id_}.epub.noimages',
            f'https://www.gutenberg.org/cache/epub/{id_}/pg{id_}.epub']

# name -> candidate URLs, tried in order. Gutenberg ids: Alice 11, Frankenstein 84, Sherlock 1661,
# Pride and Prejudice 1342, A Tale of Two Cities 98, Moby Dick 2701.
FIXTURES = {
    'alice_images':    _gutenberg(11, images=True),
    'pride_prejudice': _gutenberg(1342),
    'sherlock':        _gutenberg(1661),
    'tale_two_cities': _gutenberg(98),
    'moby_dick':       _gutenberg(2701),
    'frankenstein':    _gutenberg(84),
}

class FixtureUnavailable(Exception):
    pass

_last_request = 0.0
_skips: list[tuple[str, str]] = []


def _throttle():
    global _last_request
    wait = 1.0 - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _is_zip(p: Path) -> bool:
    return p.is_file() and p.stat().st_size > 0 and zipfile.is_zipfile(p)


def _download(url: str, part: Path):
    """Fetch url into `part`, resuming from its current size. Raises on failure."""
    have = part.stat().st_size if part.exists() else 0
    headers = {'User-Agent': _UA, 'Accept': '*/*'}
    if have:
        headers['Range'] = f'bytes={have}-'
    _throttle()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120)
    except urllib.error.HTTPError as e:
        if e.code == 416:      # the .part file already holds the whole body
            return
        raise
    with r:
        mode = 'ab' if have and r.status == 206 else 'wb'    # server ignored Range -> start over
        with open(part, mode) as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)


def fixture(name: str) -> Path:
    if name not in FIXTURES:
        raise KeyError(f'unknown fixture {name!r}; known: {sorted(FIXTURES)}')
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    dest = FIXTURE_DIR / f'{name}.epub'
    if _is_zip(dest):
        return dest
    part = FIXTURE_DIR / f'{name}.epub.part'
    errors = []
    for url in FIXTURES[name]:
        for attempt in range(2):      # the second attempt resumes the first
            try:
                print(f'  Downloading fixture {name} <- {url}', flush=True)
                _download(url, part)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f'{url}: {getattr(e, "reason", e)}')
                continue
            if _is_zip(part):
                part.replace(dest)
                return dest
            errors.append(f'{url}: not a zip file')
            part.unlink(missing_ok=True)
            break
    raise FixtureUnavailable(f'download of {name} failed ({errors[-1] if errors else "no URL"})')


def skip(section: str, reason: str):
    _skips.append((section, reason))
    print(f'SKIP: {section} ({reason})', flush=True)


def skip_count() -> int:
    return len(_skips)


def try_fixture(name: str, section: str):
    try:
        return fixture(name)
    except FixtureUnavailable as e:
        skip(section, str(e))
        return None
