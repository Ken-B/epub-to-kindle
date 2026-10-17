"""compare: before/after comparison of two sets of result.<fmt>.json files.

    from compare import compare, render
    cmp = compare(before_results, after_results)      # lists of result dicts (schema.md)
    md = render(cmp, before_label)                    # markdown "Before vs after" section

Books are paired by (sha256, format). Categories are recomputed with report.categorize for both sides so
that a changed taxonomy cannot show up as a change in the converter. A book REGRESSED when, compared
with its baseline result, any of these holds: the app fails now but not before; a parser gate passed
before and fails now; a text/image/TOC/link invariant count got worse; the style score dropped by more
than STYLE_TOL; or a new gap category (other than informational ones) appeared.
"""
from __future__ import annotations

from collections import defaultdict

import report as R

STYLE_TOL = 0.05
MAX_ROWS = 60
INFORMATIONAL = {"calibre-header-diff", "images-resized"}


def _inv(r: dict, key: str) -> dict:
    return R._d(R._d(r.get("invariants")).get(key))


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _cats(r: dict) -> list[str]:
    try:
        return R.categorize(r)
    except Exception:  # noqa: BLE001  (a malformed old result must not sink the comparison)
        return list(r.get("categories") or [])


def _pool(rs: list[dict], key: str, num: str, den: str):
    """Pooled fraction sum(num)/sum(den) over results where both are numbers."""
    n = d = 0
    for r in rs:
        a, b = _num(_inv(r, key).get(num)), _num(_inv(r, key).get(den))
        if a is not None and b is not None:
            n += a
            d += b
    return (n, d)


def _mean_style(rs: list[dict]):
    v = [s for r in rs if r.get("category") in ("se", "pg") and (s := _num(_inv(r, "style").get("score"))) is not None]
    return (sum(v) / len(v), len(v)) if v else (None, 0)


def _metrics(rs: list[dict]) -> dict:
    conv = [r for r in rs if R._d(r.get("app")).get("ok")]
    gate_known = [r for r in conv if R._gate_pass(r) is not None]
    ms, ns = _mean_style(rs)
    return {
        "books": len(rs), "converted": len(conv),
        "gate_pass": sum(1 for r in gate_known if R._gate_pass(r)), "gate_evaluated": len(gate_known),
        "style_se_pg": ms, "style_se_pg_n": ns,
        "links": _pool(rs, "links", "resolved", "internal_total"),
        "image_refs": _pool(rs, "images", "refs_correct", "refs_total"),
        "images_hash": _pool(rs, "images", "matched_by_hash", "input"),
        "text": _pool(rs, "text", "matching_items", "spine_items"),
        "toc": _pool(rs, "toc", "matched", "input_entries"),
    }


def _regression_reasons(b: dict, a: dict, cb: list[str], ca: list[str]) -> list[tuple[str, str]]:
    why = []
    if R._d(b.get("app")).get("ok") and not R._d(a.get("app")).get("ok"):
        why.append(("app error now", "app error now: " + R._trunc(R._d(a.get("app")).get("error") or R._d(a.get("app")).get("status_text"), 80)))
    for k, _ in R.GATE_CATS:
        if R._d(R._d(b.get("gate")).get(k)).get("ok") is True and R._d(R._d(a.get("gate")).get(k)).get("ok") is False:
            why.append(("gate regression", f"gate {k} passed before, fails now: " + R._gate_why(R._d(R._d(a.get("gate")).get(k)), 60)))
    # invariant counts: (label, section, key, higher_is_better)
    for label, sec, key in (("text items matching", "text", "matching_items"),
                            ("images matched by hash", "images", "matched_by_hash"),
                            ("image refs correct", "images", "refs_correct"),
                            ("TOC entries matched", "toc", "matched"),
                            ("internal links resolved", "links", "resolved")):
        vb, va = _num(_inv(b, sec).get(key)), _num(_inv(a, sec).get(key))
        if vb is not None and va is not None and va < vb:
            why.append((label, f"{label} {vb} -> {va}"))
    sb, sa = _num(_inv(b, "style").get("score")), _num(_inv(a, "style").get("score"))
    if sb is not None and sa is not None and sa < sb - STYLE_TOL:
        why.append(("style score", f"style score {sb:.2f} -> {sa:.2f}"))
    new = [c for c in ca if c not in cb and c not in INFORMATIONAL]
    if new:
        why.append(("new category", "new categories: " + ", ".join(new)))
    return why


def compare(before: list[dict], after: list[dict]) -> dict:
    bmap = {(r.get("sha256"), r.get("format")): r for r in before}
    amap = {(r.get("sha256"), r.get("format")): r for r in after}
    fmts = sorted({k[1] for k in amap} | {k[1] for k in bmap}, key=lambda f: (f != "azw3", f))
    out: dict = {"formats": {}, "unpaired_before": len(set(bmap) - set(amap)),
                 "unpaired_after": len(set(amap) - set(bmap))}
    for fmt in fmts:
        keys = sorted(k for k in amap if k[1] == fmt and k in bmap)
        rb = [bmap[k] for k in keys]
        ra = [amap[k] for k in keys]
        cb_all = [_cats(r) for r in rb]
        ca_all = [_cats(r) for r in ra]
        cat_b: dict[str, int] = defaultdict(int)
        cat_a: dict[str, int] = defaultdict(int)
        for c in cb_all:
            for x in c:
                cat_b[x] += 1
        for c in ca_all:
            for x in c:
                cat_a[x] += 1
        cats = [c for c in R.TAXONOMY if cat_b.get(c) or cat_a.get(c)]
        regs = []
        for b, a, cb, ca in zip(rb, ra, cb_all, ca_all, strict=True):
            why = _regression_reasons(b, a, cb, ca)
            if why:
                regs.append({"id": a.get("id"), "category": a.get("category"), "reasons": why})
        out["formats"][fmt] = {
            "pairs": len(keys),
            "categories": {c: {"before": cat_b.get(c, 0), "after": cat_a.get(c, 0)} for c in cats},
            "before": _metrics(rb), "after": _metrics(ra), "regressions": regs,
        }
    return out


# ── rendering ───────────────────────────────────────────────────────────────

def _frac(p) -> str:
    n, d = p
    return "n/a" if not d else f"{n}/{d} ({100 * n / d:.1f}%)"


def _pct_pair(p):
    n, d = p
    return None if not d else n / d


def _signed(x: int) -> str:
    return f"{x:+d}" if x else "0"


def render(cmp: dict, before_label: str) -> str:
    L = ["## Before vs after", "",
         (f"Baseline: `{before_label}` (result files of the original writer). Books are paired by sha256 "
          "and format; categories are recomputed with the current taxonomy on both sides. A lower count "
          "is better in every category row."), ""]
    if cmp.get("unpaired_before") or cmp.get("unpaired_after"):
        L += [f"Unpaired results: {cmp['unpaired_before']} only in the baseline, {cmp['unpaired_after']} only now.", ""]
    for fmt, f in cmp["formats"].items():
        b, a = f["before"], f["after"]
        def style(m):
            return "n/a" if m["style_se_pg"] is None else f"{m['style_se_pg']:.3f} (n={m['style_se_pg_n']})"

        rows = [
            ("books with an output file", f"{b['converted']}/{b['books']}", f"{a['converted']}/{a['books']}"),
            ("gate pass (all three parsers)", _frac((b["gate_pass"], b["gate_evaluated"])),
             _frac((a["gate_pass"], a["gate_evaluated"]))),
            ("mean style score, se+pg books", style(b), style(a)),
            ("internal links resolved (pooled)", _frac(b["links"]), _frac(a["links"])),
            ("image refs correct (pooled)", _frac(b["image_refs"]), _frac(a["image_refs"])),
            ("images present by hash (pooled)", _frac(b["images_hash"]), _frac(a["images_hash"])),
            ("spine items with matching text (pooled)", _frac(b["text"]), _frac(a["text"])),
            ("TOC entries matched (pooled)", _frac(b["toc"]), _frac(a["toc"])),
        ]
        L += [f"### {fmt.upper()}: {f['pairs']} paired books, {len(f['regressions'])} regressed", "",
              "| metric | before | after |", "|---|---|---|"]
        L += [f"| {m} | {x} | {y} |" for m, x, y in rows]
        L += ["", "| category | books before | books after | delta |", "|---|---|---|---|"]
        for c, v in f["categories"].items():
            L.append(f"| `{c}` | {v['before']} | {v['after']} | {_signed(v['after'] - v['before'])} |")
        L.append("")
        regs = f["regressions"]
        L.append(f"#### {fmt.upper()} regressions ({len(regs)})")
        L.append("")
        if not regs:
            L += ["None.", ""]
            continue
        kinds: dict[str, int] = defaultdict(int)
        for r in regs:
            for kind, _ in r["reasons"]:
                kinds[kind] += 1
        L += ["Reason counts (a book can have several): " + "; ".join(
            f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])), "",
            "| book | corpus category | why |", "|---|---|---|"]
        for r in regs[:MAX_ROWS]:
            L.append(f"| `{R._short_id(r['id'])}` | {r['category']} | {R._md('; '.join(t for _, t in r['reasons']))} |")
        if len(regs) > MAX_ROWS:
            L.append(f"| ... | | {len(regs) - MAX_ROWS} more in the JSON report (`before_after`) |")
        L.append("")
    return "\n".join(L)
