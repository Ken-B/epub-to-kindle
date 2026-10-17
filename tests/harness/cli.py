# /// script
# requires-python = ">=3.13"
# dependencies = ["playwright", "pillow", "lxml"]
# ///
"""Differential quality harness driver.

    uv run tests/harness/cli.py prepare [--fetch]
    uv run tests/harness/cli.py convert [flags]     # app (Chromium) + Calibre ebook-convert
    uv run tests/harness/cli.py check   [flags]     # gate + invariants + calibre_diff -> result.<fmt>.json
    uv run tests/harness/cli.py report  [flags]     # tests/reports/<date>-<subset>.md/.json
    uv run tests/harness/cli.py all     [flags]     # convert, check, report
    uv run tests/harness/cli.py compare --before DIR --name N  # report + 'Before vs after' section

Flags (all stages): --subset core,heavy,real,generated,local  --ids GLOBS  --fmt azw3,mobi
                    --workers N  --force  --no-style  --limit N
Every stage caches; --force recomputes. See tests/harness/schema.md for the file layout.
"""
from __future__ import annotations

import argparse
import atexit
import datetime
import fnmatch
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
ROOT = HARNESS_DIR.parents[1]
CORPUS = ROOT / "tests/corpus"
OUT_ROOT = CORPUS / "out"
REPORTS = ROOT / "tests/reports"
DEFAULT_BEFORE = CORPUS / "baseline-results"
DEFAULT_SUBSETS = "core,real,generated,local"

if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))


# ── selection ────────────────────────────────────────────────────────────────

def _csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def select(args) -> list[dict]:
    manifest = CORPUS / "manifest.json"
    if not manifest.exists():
        sys.exit("tests/corpus/manifest.json missing: run `uv run tests/harness/cli.py prepare` first")
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    subsets = set(_csv(args.subset))
    entries = [e for e in entries if e.get("subset") in subsets]
    pats = _csv(args.ids) if args.ids else []
    if pats:
        entries = [e for e in entries if any(fnmatch.fnmatchcase(e["id"], p) for p in pats)]
    if args.limit:
        entries = entries[: args.limit]
    return entries


def subset_label(args) -> str:
    return "-".join(_csv(args.subset))


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write_json_atomic(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


# ── prepare ──────────────────────────────────────────────────────────────────

def cmd_prepare(args) -> None:
    import corpus
    t0 = time.time()
    entries = corpus.prepare(ROOT, se=100, pg=100, fetch=args.fetch)
    from collections import Counter
    log(f"manifest: {len(entries)} entries "
        f"{dict(sorted(Counter(e['subset'] for e in entries).items()))} ({time.time() - t0:.0f}s)")


# ── convert ──────────────────────────────────────────────────────────────────

def cmd_convert(args) -> None:
    import run_app
    import run_calibre
    entries = select(args)
    fmts = _csv(args.fmt)
    log(f"convert: {len(entries)} entries x {fmts}; app {run_app.app_version(ROOT)}")
    cal_err: list[BaseException] = []
    t_cal = [0.0]

    def calibre_stage():
        t0 = time.time()
        done = [0]
        total = len(entries) * len(fmts)

        def progress(e, fmt, meta, cached):
            done[0] += 1
            if done[0] % 50 == 0 or done[0] == total:
                log(f"calibre: {done[0]}/{total}")
        try:
            run_calibre.convert_many(entries, fmts, OUT_ROOT, workers=args.workers, timeout_s=None,
                                     force=args.force, progress=progress)
        except BaseException as e:  # noqa
            cal_err.append(e)
            traceback.print_exc()
        t_cal[0] = time.time() - t0

    th = threading.Thread(target=calibre_stage, name="calibre", daemon=True)
    th.start()
    t0 = time.time()
    errs = 0
    n = 0
    with run_app.AppRunner(ROOT) as runner:
        for e in entries:
            for fmt in fmts:
                n += 1
                try:
                    m = runner.convert(e, fmt, OUT_ROOT / e["sha256"],
                                       timeout_s=run_app.default_timeout(e), force=args.force)
                except Exception as exc:  # noqa: BLE001
                    m = {"error": f"harness: {type(exc).__name__}: {exc}"[:600]}
                    d = OUT_ROOT / e["sha256"]
                    d.mkdir(parents=True, exist_ok=True)
                    _write_json_atomic(d / f"ours.{fmt}.meta.json", {
                        "app_version": run_app.app_version(ROOT), "app_sha": run_app.app_sha(ROOT),
                        "ms": None, "status_text": "",
                        "console_errors": [], "error": m["error"]})
                errs += bool(m.get("error"))
                if n % 100 == 0:
                    log(f"app: {n}/{len(entries) * len(fmts)} ({errs} with error)")
    t_app = time.time() - t0
    log(f"app done: {n} conversions, {errs} with error, {t_app:.0f}s; waiting for calibre")
    th.join()
    log(f"calibre done in {t_cal[0]:.0f}s" + (f" (CRASHED: {cal_err[0]!r})" if cal_err else ""))
    if cal_err:
        raise cal_err[0]


# ── check ────────────────────────────────────────────────────────────────────

_W: dict = {}   # per-process lazy state: playwright, browser, context, page, base_url


def _worker_page(no_style: bool):
    """Lazily create this process's Chromium (JS disabled, 600x800) + page + out server."""
    import oracles
    if "base_url" not in _W:
        _W["base_url"] = oracles.start_out_server(OUT_ROOT)
    if no_style:
        return None, _W["base_url"]
    br = _W.get("browser")
    if br is not None and not br.is_connected():
        _worker_close()
        br = None
    if br is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _W["pw"] = pw
        _W["browser"] = br = pw.chromium.launch(headless=True)
        _W["ctx"] = br.new_context(java_script_enabled=False, viewport=dict(oracles.STYLE_VIEWPORT),
                                   service_workers="block")
        _W["page"] = _W["ctx"].new_page()
        atexit.register(_worker_close)
    return _W["page"], _W["base_url"]


def _worker_close() -> None:
    for k, fn in (("ctx", lambda o: o.close()), ("browser", lambda o: o.close()),
                  ("pw", lambda o: o.stop())):
        o = _W.pop(k, None)
        if o is not None:
            try:
                fn(o)
            except Exception:  # noqa: BLE001, S110
                pass
    _W.pop("page", None)


def _meta_app(out_dir: Path, fmt: str) -> dict:
    f = out_dir / f"ours.{fmt}"
    m = _read_json(out_dir / f"ours.{fmt}.meta.json")
    if m is None:
        return {"ok": f.exists(), "ms": None, "error": None if f.exists() else "no app output / meta",
                "status_text": "", "console_errors": []}
    return {"ok": f.exists() and not m.get("error"), "ms": m.get("ms"), "error": m.get("error"),
            "status_text": m.get("status_text", ""), "console_errors": m.get("console_errors", [])}


def _meta_calibre(out_dir: Path, fmt: str) -> dict:
    f = out_dir / f"calibre.{fmt}"
    m = _read_json(out_dir / f"calibre.{fmt}.meta.json")
    if m is None:
        return {"ok": f.exists(), "ms": None, "error": None if f.exists() else "no calibre output / meta"}
    return {"ok": f.exists() and not m.get("error"), "ms": m.get("ms"), "error": m.get("error")}


def _calibre_tree(out_dir: Path, fmt: str, force: bool) -> None:
    """KindleUnpack tree of calibre.<fmt>, needed by calibre_diff. Only the unpack step of the gate
    is run (the full gate would also run mobitool and ebook-convert on Calibre's own output)."""
    import oracles
    src = out_dir / f"calibre.{fmt}"
    d = out_dir / "unpack" / fmt / "calibre" / "kindleunpack"
    if src.exists() and (force or not d.exists()):
        oracles._gate_kindleunpack(src, d, fmt)


def _skipped_gate(why: str) -> dict:
    return {k: {"ok": None, "err": why} for k in ("mobitool", "kindleunpack", "calibre_reader")}


def check_one(entry: dict, fmt: str, force: bool, no_style: bool) -> dict:
    """Compute and write result.<fmt>.json for one (entry, fmt). Never raises."""
    import calibre_diff
    import oracles
    import report
    out_dir = OUT_ROOT / entry["sha256"]
    res = {k: entry.get(k) for k in ("id", "path", "sha256", "category", "expected_verdict",
                                     "size_bytes", "subset")}
    res["format"] = fmt
    res.update(app=None, calibre=None, gate=None, invariants=None, calibre_diff=None, categories=[])
    errors = []
    try:
        res["app"] = _meta_app(out_dir, fmt)
        res["calibre"] = _meta_calibre(out_dir, fmt)
        ours = out_dir / f"ours.{fmt}"
        if ours.exists():
            try:
                res["gate"] = oracles.gate(out_dir, fmt, "ours", force=force)
            except Exception as e:  # noqa: BLE001
                res["gate"] = _skipped_gate(f"harness: {type(e).__name__}: {e}")
                errors.append(f"gate: {e}")
            if (res["gate"].get("kindleunpack") or {}).get("ok"):
                try:
                    # MOBI v6 needs Chromium even without the style score: the input elements its
                    # author CSS hides are pruned before text/links (see oracles.hidden_pass)
                    page, base_url = _worker_page(no_style and fmt != "mobi")
                    res["invariants"] = oracles.invariants(entry, out_dir, fmt, page, base_url=base_url,
                                                           who="ours", skip_style=no_style)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"invariants: {type(e).__name__}: {e}")
                    res["invariants"] = {"errors": {"harness": f"{type(e).__name__}: {e}"}}
        else:
            res["gate"] = _skipped_gate("no ours output")
        if ours.exists() and (out_dir / f"calibre.{fmt}").exists():
            try:
                _calibre_tree(out_dir, fmt, force)
                res["calibre_diff"] = calibre_diff.diff(entry, out_dir, fmt)
            except Exception as e:  # noqa: BLE001
                errors.append(f"calibre_diff: {type(e).__name__}: {e}")
                res["calibre_diff"] = {"error": f"{type(e).__name__}: {e}"}
    except Exception as e:  # noqa: BLE001
        errors.append(f"check: {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
    inv = res.get("invariants")
    if isinstance(inv, dict) and inv.get("fixed_layout") is not None:
        res["fixed_layout"] = inv["fixed_layout"]    # report.categorize reads it at top level
    if errors:
        res["check_errors"] = errors
    try:
        res["categories"] = report.categorize(res)
    except Exception as e:  # noqa: BLE001
        res["categories"] = []
        res.setdefault("check_errors", []).append(f"categorize: {e}")
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(out_dir / f"result.{fmt}.json", res)
    return res


def _check_batch(batch: list[tuple[dict, str]], force: bool, no_style: bool) -> list[tuple[str, str, bool]]:
    out = []
    for entry, fmt in batch:
        try:
            r = check_one(entry, fmt, force, no_style)
            out.append((entry["id"], fmt, True, r.get("categories") or []))
        except BaseException as e:  # noqa: BLE001
            out.append((entry["id"], fmt, False, [f"{type(e).__name__}: {e}"]))
    return out


def _is_fresh(entry: dict, fmt: str) -> bool:
    """Result exists and is newer than every input it derives from."""
    d = OUT_ROOT / entry["sha256"]
    rf = d / f"result.{fmt}.json"
    if not rf.exists():
        return False
    t = rf.stat().st_mtime
    for n in (f"ours.{fmt}", f"ours.{fmt}.meta.json", f"calibre.{fmt}", f"calibre.{fmt}.meta.json"):
        p = d / n
        if p.exists() and p.stat().st_mtime > t:
            return False
    return True


def cmd_check(args) -> None:
    entries = select(args)
    fmts = _csv(args.fmt)
    items = [(e, f) for e in entries for f in fmts]
    if not args.force:
        todo = [(e, f) for e, f in items if not _is_fresh(e, f)]
    else:
        todo = items
    log(f"check: {len(items)} items, {len(items) - len(todo)} cached, {len(todo)} to do, "
        f"workers={args.workers}, style={'off' if args.no_style else 'on'}")
    if not todo:
        return
    todo.sort(key=lambda it: -(it[0].get("size_bytes") or 0))   # big first for load balance
    bsize = 4
    batches = [todo[i:i + bsize] for i in range(0, len(todo), bsize)]
    t0 = time.time()
    done = 0
    failed = 0
    attempts = 0
    pending = batches
    while pending and attempts < 3:
        attempts += 1
        nxt = []
        with ProcessPoolExecutor(max_workers=min(args.workers, len(pending))) as ex:
            futs = {ex.submit(_check_batch, b, args.force, args.no_style): b for b in pending}
            try:
                for f in as_completed(futs):
                    b = futs[f]
                    try:
                        out = f.result()
                    except BrokenProcessPool:
                        raise
                    except Exception as e:  # noqa: BLE001
                        log(f"batch failed: {e!r}")
                        out = [(e_["id"], fm, False, [repr(e)]) for e_, fm in b]
                    for id_, fm, ok, cats in out:
                        done += 1
                        failed += (not ok)
                    if done % 25 < bsize or done == len(todo):
                        el = time.time() - t0
                        eta = el / done * (len(todo) - done)
                        log(f"check: {done}/{len(todo)} ({failed} failed) elapsed {el / 60:.1f}m "
                            f"eta {eta / 60:.1f}m")
            except BrokenProcessPool:
                log("worker pool broke (a worker died); retrying unfinished batches")
                nxt = [b for f, b in futs.items() if not f.done() or f.exception() is not None]
        pending = nxt
    if pending:
        # give up on batches that keep killing workers: write error results for them
        for b in pending:
            for e, fm in b:
                if not _is_fresh(e, fm):
                    r = {k: e.get(k) for k in ("id", "path", "sha256", "category", "expected_verdict",
                                               "size_bytes", "subset")}
                    r.update(format=fm, app=_meta_app(OUT_ROOT / e["sha256"], fm),
                             calibre=_meta_calibre(OUT_ROOT / e["sha256"], fm), gate=None,
                             invariants=None, calibre_diff=None, categories=[],
                             check_errors=["worker process died repeatedly on this item"])
                    _write_json_atomic(OUT_ROOT / e["sha256"] / f"result.{fm}.json", r)
        log(f"check: {sum(len(b) for b in pending)} items recorded as worker deaths")
    log(f"check done: {done} items in {(time.time() - t0) / 60:.1f} min")


# ── report ───────────────────────────────────────────────────────────────────

def _add_comparison(results: list[dict], before_dir: Path, md: Path, js: Path) -> None:
    """Prepend a "Before vs after" section (compare.py) to the markdown, add `before_after` to the JSON."""
    import compare
    before = []
    for sha in {r["sha256"] for r in results}:
        for f in sorted((before_dir / sha).glob("result.*.json")):
            r = _read_json(f)
            if r is not None:
                before.append(r)
    cmp = compare.compare(before, results)
    text = md.read_text(encoding="utf-8")
    i = text.find("\n## Format:")
    section = compare.render(cmp, str(before_dir.relative_to(ROOT)) if before_dir.is_relative_to(ROOT)
                             else str(before_dir))
    md.write_text(text[:i + 1] + section + "\n" + text[i + 1:] if i >= 0 else text + "\n" + section + "\n",
                  encoding="utf-8")
    data = _read_json(js) or {}
    data["before_after"] = cmp
    _write_json_atomic(js, data)
    nreg = {f: len(v["regressions"]) for f, v in cmp["formats"].items()}
    log(f"compare: {len(before)} baseline results; regressions {nreg}")


def cmd_report(args) -> None:
    import report
    entries = select(args)
    fmts = _csv(args.fmt)
    results = []
    missing = 0
    for e in entries:
        for f in fmts:
            r = _read_json(OUT_ROOT / e["sha256"] / f"result.{f}.json")
            if r is None:
                missing += 1
            else:
                results.append(r)
    label = subset_label(args)
    today = datetime.date.today().isoformat()
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = getattr(args, "name", None) or f"{today}-{label}"
    md, js = REPORTS / f"{stem}.md", REPORTS / f"{stem}.json"
    report.write_report(results, md, js, subset=label)
    before = getattr(args, "before", None)
    if before:
        _add_comparison(results, Path(before), md, js)
    log(f"report: {len(results)} results ({missing} missing) -> {md.relative_to(ROOT)}")


# ── main ─────────────────────────────────────────────────────────────────────

def cmd_all(args) -> None:
    t = {}
    for name, fn in (("convert", cmd_convert), ("check", cmd_check), ("report", cmd_report)):
        t0 = time.time()
        fn(args)
        t[name] = time.time() - t0
    log("stage wall times: " + ", ".join(f"{k} {v / 60:.1f}m" for k, v in t.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--subset", default=DEFAULT_SUBSETS,
                       help="comma list of core,heavy,real,generated,local (default: %(default)s)")
        p.add_argument("--ids", help="comma-separated fnmatch globs on entry ids")
        p.add_argument("--fmt", default="azw3,mobi")
        p.add_argument("--workers", type=int, default=8)
        p.add_argument("--force", action="store_true",
                       help="recompute: for `check` only gate/invariants/diff (never convert outputs); "
                            "for `convert`/`all` also the conversions")
        p.add_argument("--no-style", action="store_true", help="skip the (slow) style score")
        p.add_argument("--limit", type=int, help="only the first N entries (smoke tests)")

    p = sub.add_parser("prepare", help="regenerate tests/corpus/manifest.json")
    p.add_argument("--fetch", action="store_true", help="also (re)fetch real-world books")
    p.set_defaults(fn=cmd_prepare)
    for name, fn in (("convert", cmd_convert), ("check", cmd_check), ("report", cmd_report),
                     ("all", cmd_all), ("compare", cmd_report)):
        p = sub.add_parser(name)
        common(p)
        if name in ("report", "all", "compare"):
            p.add_argument("--name", help="report file stem (default <date>-<subset>)")
            p.add_argument("--before", default=str(DEFAULT_BEFORE) if name == "compare" else None,
                           help="baseline results dir (<sha>/result.<fmt>.json): adds a 'Before vs after' "
                                "section to the report")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
