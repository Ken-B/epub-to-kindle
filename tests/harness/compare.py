"""compare: before/after comparison of two sets of result.<fmt>.json files.

    from compare import compare, render
    cmp = compare(before_results, after_results)      # lists of result dicts (schema.md)
    md = render(cmp, before_label)                    # markdown "Before vs after" section

Books are paired by (sha256, format). Categories are recomputed with report.categorize for both sides so
that a changed taxonomy cannot show up as a change in the converter. A book REGRESSED when, compared
with its baseline result, any of these holds: the app fails now but not before; a parser gate passed
before and fails now; a text/image/TOC/link invariant count got worse; the style score or the (AZW3)
device score dropped by more than STYLE_TOL; or a new gap category (other than informational ones)
appeared; or the characters of text that changed visibility (hidden in the input and shown in the output,
or the reverse; preservation or device render) rose. A baseline written before a field existed (no
device_score, no layout_hygiene, no style.visibility) shows "n/a"
and is not compared on it. style.score is page-neutral for AZW3 since score_page_dependent exists; a baseline
without that field is old-style, so its score is compared with the new result's score_page_dependent.
"""
from __future__ import annotations

from collections import defaultdict

import report as R

STYLE_TOL = 0.05
MAX_ROWS = 60
INFORMATIONAL = {"calibre-header-diff", "images-resized", "spine-non-xhtml", "images-unextractable",
                 "layout-hygiene"}


# categories that need a result field older results lack: on a baseline without the field the category
# was not evaluated, so it is neither counted ("n/a") nor a "new category" regression
CAT_FIELD = {
    "device-style-lost": lambda r: R._device_score(r) is not None,
    "layout-hygiene": lambda r: isinstance(R._d(r.get("invariants")).get("layout_hygiene"), dict),
    "visibility-changed": lambda r: isinstance(R._d(_inv(r, "style")).get("visibility"), dict),
}


def _evaluated(r: dict, cat: str) -> bool:
    f = CAT_FIELD.get(cat)
    return f is None or f(r)


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


def _vis_chars(r: dict, key: str):
    """(hidden->shown chars, shown->hidden chars) of style.<key> (visibility / device_visibility), or None."""
    v = R._d(_inv(r, "style").get(key))
    if not v:
        return None
    return tuple(_num(v.get(k)) or 0 for k in R.VIS_KEYS)


def _metrics(rs: list[dict]) -> dict:
    conv = [r for r in rs if R._d(r.get("app")).get("ok")]
    gate_known = [r for r in conv if R._gate_pass(r) is not None]
    ms, ns = R.mean_score(rs, R._score)
    md, nd = R.mean_score(rs, R._device_score)
    mo, no = R.mean_score(rs, R._score_page_dependent)
    return {
        "books": len(rs), "converted": len(conv),
        "gate_pass": sum(1 for r in gate_known if R._gate_pass(r)), "gate_evaluated": len(gate_known),
        "style_se_pg": ms, "style_se_pg_n": ns,
        "style_old_se_pg": mo, "style_old_se_pg_n": no,
        "device_se_pg": md, "device_se_pg_n": nd,
        "hygiene": R.hygiene_pooled(rs),
        "visibility": R.visibility_pooled(rs),
        "device_visibility": R.visibility_pooled(rs, "device_visibility"),
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
    # score is page-neutral since score_page_dependent exists: a baseline without it is old-style, so compare
    # it with the page-dependent number of the new result (like with like)
    sb, sa = _num(R._d(_inv(b, "style")).get("score")), _num(R._d(_inv(a, "style")).get("score"))
    if "score_page_dependent" not in R._d(_inv(b, "style")) and "score_page_dependent" in R._d(_inv(a, "style")):
        sa = _num(_inv(a, "style").get("score_page_dependent"))
    if sb is not None and sa is not None and sa < sb - STYLE_TOL:
        why.append(("style score", f"style score {sb:.2f} -> {sa:.2f}"))
    db, da = R._device_score(b), R._device_score(a)
    if db is not None and da is not None and da < db - STYLE_TOL:
        why.append(("device score", f"device score {db:.2f} -> {da:.2f}"))
    # text changing visibility (either direction, preservation or device render): any rise is a regression;
    # a baseline without the field is not compared
    for label, key in (("visibility changed", "visibility"), ("device visibility changed", "device_visibility")):
        vb, va = _vis_chars(b, key), _vis_chars(a, key)
        if vb is not None and va is not None and sum(va) > sum(vb):
            why.append((label, f"{label} chars {vb[0]}/{vb[1]} -> {va[0]}/{va[1]} (hidden>shown/shown>hidden)"))
    new = [c for c in ca if c not in cb and c not in INFORMATIONAL and _evaluated(b, c)]
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
        # None: no baseline result has the field the category needs (rendered "n/a")
        unev_b = {c for c in CAT_FIELD if not any(_evaluated(r, c) for r in rb)}
        unev_a = {c for c in CAT_FIELD if not any(_evaluated(r, c) for r in ra)}
        regs = []
        for b, a, cb, ca in zip(rb, ra, cb_all, ca_all, strict=True):
            why = _regression_reasons(b, a, cb, ca)
            if why:
                regs.append({"id": a.get("id"), "category": a.get("category"), "reasons": why})
        out["formats"][fmt] = {
            "pairs": len(keys),
            "categories": {c: {"before": None if c in unev_b else cat_b.get(c, 0),
                               "after": None if c in unev_a else cat_a.get(c, 0)} for c in cats},
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
        def style(m, k="style_se_pg"):
            return "n/a" if m.get(k) is None else f"{m[k]:.3f} (n={m[k + '_n']})"

        rows = [
            ("books with an output file", f"{b['converted']}/{b['books']}", f"{a['converted']}/{a['books']}"),
            ("gate pass (all three parsers)", _frac((b["gate_pass"], b["gate_evaluated"])),
             _frac((a["gate_pass"], a["gate_evaluated"]))),
            ("mean style score, se+pg books (AZW3: page-neutral; a baseline written before that is old-style)",
             style(b), style(a)),
            ("mean style score, page-dependent (old definition), se+pg books",
             style(b, "style_old_se_pg"), style(a, "style_old_se_pg")),
            ("mean device score, se+pg books", style(b, "device_se_pg"), style(a, "device_se_pg")),
            ("layout hygiene, pooled (empty blocks / trailing breaks / whitespace runs / nbsp indents)",
             R.hygiene_str(b.get("hygiene")), R.hygiene_str(a.get("hygiene"))),
            ("visibility changed, pooled chars (hidden→shown / shown→hidden)",
             R.visibility_str(b.get("visibility")), R.visibility_str(a.get("visibility"))),
            ("visibility changed on the device model, pooled chars (hidden→shown / shown→hidden)",
             R.visibility_str(b.get("device_visibility")), R.visibility_str(a.get("device_visibility"))),
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
            na = v["before"] is None or v["after"] is None
            L.append(f"| `{c}` | {'n/a' if v['before'] is None else v['before']} | "
                     f"{'n/a' if v['after'] is None else v['after']} | "
                     f"{'n/a' if na else _signed(v['after'] - v['before'])} |")
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
