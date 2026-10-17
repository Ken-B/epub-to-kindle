"""Run Calibre's ebook-convert over corpus EPUBs in parallel processes.

Writes <out_root>/<sha256>/calibre.<fmt> and calibre.<fmt>.meta.json {calibre_version, ms, error}.

Cache: a stored result is reused when it was produced by the same `ebook-convert --version` and is
either a file or a definitive Calibre failure; timeouts and harness errors ("harness: ...") are
always retried.
"""
# Broad `except Exception` (and silent cleanup) is deliberate: the harness contract is that one bad
# book or one flaky tool never aborts a corpus run; failures are recorded in the result instead.
# ruff: noqa: BLE001
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from common import ROOT, default_timeout, entry_path, select_entries, write_json_atomic


def calibre_version() -> str | None:
    try:
        r = subprocess.run(["ebook-convert", "--version"], check=False, capture_output=True, text=True,
                           timeout=60)
        return (r.stdout.strip().splitlines() or [None])[0]
    except Exception:
        return None


def _job(epub: str, out_file: str, timeout_s: int, version: str | None, tmp_root: str, cfg_dir: str) -> dict:
    """Runs in a worker process. Never raises."""
    out = Path(out_file)
    fmt = out.name.split(".", 1)[1]
    meta_file = out.with_name(out.name + ".meta.json")
    log_file = out.with_name(out.name + ".log")
    # Calibre picks the output format from the extension, so the in-progress file is
    # calibre.partial.<fmt> (not calibre.<fmt>.partial); it is renamed on success.
    part = out.with_name(f"calibre.partial.{fmt}")
    meta = {"calibre_version": version, "ms": None, "error": None}
    job_tmp = tempfile.mkdtemp(prefix="job-", dir=tmp_root)
    env = dict(os.environ, TMPDIR=job_tmp, TEMP=job_tmp, TMP=job_tmp,
               CALIBRE_TEMP_DIR=tmp_root, CALIBRE_CONFIG_DIRECTORY=cfg_dir,
               CALIBRE_OVERRIDE_LANG="en")
    t0 = time.perf_counter()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        for stale in (out, meta_file, part, log_file):
            if stale.exists():
                stale.unlink()
        with open(log_file, "wb") as log:
            p = subprocess.Popen(["ebook-convert", epub, str(part)], env=env,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                rc = p.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    p.kill()
                p.wait()
                rc = None
                meta["error"] = "timeout"
        meta["ms"] = int((time.perf_counter() - t0) * 1000)
        if meta["error"] is None and (rc != 0 or not part.exists()):
            tail = log_file.read_bytes()[-2000:].decode("utf-8", "replace")
            meta["error"] = tail or f"exit {rc}"
        if meta["error"] is None:
            os.replace(part, out)
    except Exception as e:
        meta["error"] = f"harness: {type(e).__name__}: {e}"[-2000:]
    finally:
        if part.exists():
            part.unlink()
        shutil.rmtree(job_tmp, ignore_errors=True)
    write_json_atomic(meta_file, meta)
    return meta


def _cached(out: Path, version: str | None) -> dict | None:
    meta_file = out.with_name(out.name + ".meta.json")
    if not meta_file.exists():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    if version is None or meta.get("calibre_version") != version:
        return None  # other (or unknown) Calibre build: convert again
    err = meta.get("error")
    if out.exists() and not err:
        return meta
    # Calibre is deterministic: a recorded Calibre failure is cached too, but not a timeout
    # (machine load) and not an error of the harness itself
    if not out.exists() and err and err != "timeout" and not str(err).startswith("harness:"):
        return meta
    return None


def convert_many(entries: list[dict], fmts: list[str], out_root: Path, *, workers: int = 8,
                 timeout_s: int | None = 300, force: bool = False, progress=None) -> dict[str, dict]:
    """sha256 -> {fmt: meta}.  timeout_s=None uses default_timeout(entry): 120 s (<2 MB) / 300 s.

    progress(entry, fmt, meta, cached: bool) is called once per (entry, fmt) when given."""
    out_root = Path(out_root)
    version = calibre_version()
    results: dict[str, dict] = {}
    todo = []
    for e in entries:
        d = out_root / e["sha256"]
        for fmt in fmts:
            out = d / f"calibre.{fmt}"
            hit = None if force else _cached(out, version)
            if hit is not None:
                results.setdefault(e["sha256"], {})[fmt] = hit
                if progress:
                    progress(e, fmt, hit, True)
            else:
                todo.append((e, fmt, out))
    if todo:
        tmp_root = out_root / "_calibre_tmp"
        cfg_dir = out_root / "_calibre_cfg"
        tmp_root.mkdir(parents=True, exist_ok=True)
        cfg_dir.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {}
            for e, fmt, out in todo:
                t = timeout_s if timeout_s is not None else default_timeout(e)
                futs[ex.submit(_job, str(entry_path(e)), str(out), t, version,
                                 str(tmp_root.resolve()), str(cfg_dir.resolve()))] = (e, fmt)
            for f in as_completed(futs):
                e, fmt = futs[f]
                try:
                    meta = f.result()
                except Exception as exc:  # worker process died
                    meta = {"calibre_version": version, "ms": None,
                            "error": f"harness: {type(exc).__name__}: {exc}"[-2000:]}
                results.setdefault(e["sha256"], {})[fmt] = meta
                if progress:
                    progress(e, fmt, meta, False)
        # sweep leftovers (killed helpers can leave calibre-* / job-* dirs behind)
        for d in tmp_root.iterdir():
            if d.is_dir() and d.name.startswith(("calibre-", "job-")):
                shutil.rmtree(d, ignore_errors=True)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert corpus EPUBs with Calibre ebook-convert")
    ap.add_argument("--manifest", default=str(ROOT / "tests/corpus/manifest.json"))
    ap.add_argument("--ids", help="comma-separated ids or fnmatch globs (default: all)")
    ap.add_argument("--fmt", default="azw3,mobi")
    ap.add_argument("--out", default=str(ROOT / "tests/corpus/out"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=None, help="override per-conversion timeout (s)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    entries = select_entries(json.loads(Path(a.manifest).read_text(encoding="utf-8")), a.ids)
    fmts = [f.strip() for f in a.fmt.split(",") if f.strip()]
    print(f"{len(entries)} entries x {fmts}; {calibre_version()}; workers={a.workers}")

    def progress(e, fmt, m, cached):
        out = Path(a.out) / e["sha256"] / f"calibre.{fmt}"
        size = out.stat().st_size if out.exists() else 0
        state = "ok" if not m["error"] else f"ERR {m['error'][-80:]!r}"
        print(f"{e['id'][-60:]:60} {fmt:5} {m['ms'] if m['ms'] is not None else '-':>7} ms "
              f"{size:>9} B  {state}{' (cached)' if cached else ''}", flush=True)

    convert_many(entries, fmts, Path(a.out), workers=a.workers, timeout_s=a.timeout,
                 force=a.force, progress=progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
