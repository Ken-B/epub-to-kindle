"""report: gap taxonomy, per-book categorisation and the markdown/JSON report.

    from report import TAXONOMY, categorize, write_report

`results` are the `result.<fmt>.json` dicts from schema.md (one per book and format; the `format`
key groups them). Every function tolerates None sub-dicts (stages that were skipped or failed).

Optional result keys that sharpen the categories when an upstream stage provides them (all are
treated as "unknown/false" when absent):
    result["invariants"]["fixed_layout"]        bool, input OPF is rendition:layout pre-paginated
                                                (a top-level result["fixed_layout"] is accepted too)
    result["invariants"]["text"]["replacement_chars"] / ["replacement_chars_input"]
                                                U+FFFD count in our text / in the input text
    result["invariants"]["text"]["css_in_text"] / ["css_in_text_input"]
                                                CSS rules visible in our body text / in the input's
    result["invariants"]["images"]["missing"]   referenced input images absent from the output
    result["invariants"]["images"]["unextractable"]
                                                referenced input images present in the file as raw records
                                                that KindleUnpack does not extract (not counted as missing)
    result["invariants"]["text"]["non_xhtml_spine_items"]
                                                spine items whose manifest type is not XHTML/HTML (not
                                                compared as text; category `spine-non-xhtml`, informational)
    result["invariants"]["style"]["device_score"]
                                                AZW3 style score under the Kindle device model (category
                                                `device-style-lost` below DEVICE_STYLE_MIN)
    result["invariants"]["layout_hygiene"] / ["layout_hygiene_input"]
                                                {empty_blocks, trailing_breaks, whitespace_runs, nbsp_indents}
                                                in our output / in the input (category `layout-hygiene`)
Without them: fixed layout is guessed from "fixed-layout"/"pre-paginated" in id/path, garbling from
U+FFFD in `invariants.text.first_diff.ours_excerpt` (and not in `input_excerpt`), and images-missing
from matched_by_hash < input.

Errors of the harness itself ("harness: ..." in app/calibre/gate errors, a missing app meta file, or
cli.py's invariants["errors"]["harness"]) get the category `harness-error` (kind "harness"): such a
book says nothing about the app and is kept out of every actionable tally.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# category -> (description, kind)
TAXONOMY: dict[str, tuple[str, str]] = {
    "app-error": ("App produced no file and the input is not expected to fail", "writer bug"),
    "app-clean-error": ("No file, input expected to be an error, specific message shown", "acceptable"),
    "app-timeout": ("App exceeded the conversion timeout", "writer bug"),
    "gate-mobitool": ("libmobi mobitool cannot read our output", "writer bug"),
    "gate-kindleunpack": ("KindleUnpack cannot unpack our output", "writer bug"),
    "gate-calibre": ("Calibre's reader cannot read our output", "writer bug"),
    "text-loss": ("Spine items whose text did not survive conversion", "transform or repair"),
    "text-garbled": ("U+FFFD or CSS rules in the body text", "writer bug"),
    "spine-non-xhtml": ("Spine items that are not XHTML/HTML (svg, image, xml, json, ...): not compared as text",
                        "informational"),
    "images-missing": ("Input images not found (by hash) in the output",
                       "unported Calibre transform"),
    "images-resized": ("Images present but with different dimensions", "informational"),
    "images-unextractable": (("Images stored in the file as raw records that KindleUnpack does not extract "
                              "(svg, avif, jxl, ...)"), "informational"),
    "images-misreferenced": ("Image references in the text point at the wrong image or at none",
                             "writer bug"),
    "toc-missing": ("Input has TOC entries, output has none", "unported Calibre transform"),
    "toc-flat": ("TOC nesting depth reduced", "unported Calibre transform"),
    "toc-labels": ("TOC entries whose labels/targets do not match the input", "writer bug"),
    "links-unresolved": ("Internal links that no longer resolve", "unported Calibre transform"),
    "style-lost": ("Style score below 0.5, or the input has CSS rules and the output none",
                   "unported Calibre transform"),
    "device-style-lost": ("AZW3 style score under the Kindle device model (Kindle UA defaults, no @media/"
                          "@supports, no sibling/attribute/structural selectors) below 0.8",
                          "unported Calibre transform"),
    "layout-hygiene": ("Output markup has empty p/div, trailing <br>, raw whitespace runs or &nbsp; indents",
                       "informational"),
    "fixed-layout-unsupported": ("Input is fixed-layout (pre-paginated)", "out of scope"),
    "calibre-header-diff": ("MOBI/EXTH header fields differ from Calibre's beyond the ignore list",
                            "informational"),
    "input-repair": ("App failed or lost text on a malformed input Calibre converted anyway",
                     "input repair"),
    "harness-error": ("The harness itself failed (browser/tool crash, stage not run); no verdict",
                      "harness"),
}

KINDS_ACTIONABLE = ("unported Calibre transform", "input repair", "writer bug")
DEVICE_STYLE_MIN = 0.8
HYGIENE_KEYS = ("empty_blocks", "trailing_breaks", "whitespace_runs", "nbsp_indents")
# stricter facts (intentional markers, double breaks, verse/column nbsp): shown, not categorised
HYGIENE_EXTRA_KEYS = ("empty_blocks_styled", "trailing_breaks_double", "nbsp_indents_ambiguous")
INVARIANTS = ("text", "images", "toc", "links", "style")
KIND_ADVICE = {
    "unported Calibre transform": "port the missing Calibre transforms",
    "input repair": "add input repair/normalisation before conversion",
    "writer bug": "fix the KF8/MOBI writer defects",
}
GATE_CATS = (("mobitool", "gate-mobitool"), ("kindleunpack", "gate-kindleunpack"),
             ("calibre_reader", "gate-calibre"))


# ── categorisation ──────────────────────────────────────────────────────────

def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _int(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _is_timeout(app: dict) -> bool:
    msg = " ".join(str(app.get(k) or "") for k in ("error", "status_text")).lower()
    return "timeout" in msg or "timed out" in msg


def _is_harness_err(err) -> bool:
    return isinstance(err, str) and err.startswith("harness:")


# cli.py's placeholder when ours.<fmt>.meta.json is missing (the convert stage never ran for it)
_NO_APP_META = "no app output / meta"

# status texts that are not a specific, intentional app message: JS runtime errors leaking through
# `Error: ${err.message}`, and the iOS iCloud-stub advice (the app's guess for unreadable zips)
_JS_INTERNAL_RE = re.compile(
    r"TypeError|ReferenceError|RangeError|SyntaxError|InternalError|Cannot read propert"
    r"|is not a function|is not defined|is not iterable|Maximum call stack|\bundefined\b|\bnull\b")
_ICLOUD_RE = re.compile(r"iCloud", re.IGNORECASE)


def _specific_app_message(status_text) -> bool:
    t = (status_text or "").strip()
    return bool(t) and not _JS_INTERNAL_RE.search(t) and not _ICLOUD_RE.search(t)


def _fixed_layout(r: dict) -> bool:
    """invariants.fixed_layout or a top-level fixed_layout (either True wins); guessed from id/path
    only when neither is known."""
    vals = [v for v in (_d(r.get("invariants")).get("fixed_layout"), r.get("fixed_layout"))
            if isinstance(v, bool)]
    if vals:
        return any(vals)
    hay = f"{r.get('id', '')} {r.get('path', '')}".lower()
    return "fixed-layout" in hay or "pre-paginated" in hay


def _style_skipped(inv: dict) -> bool:
    """style is None without an error: the run used --no-style (not a failure)."""
    return inv.get("style") is None and "style" not in _d(inv.get("errors"))


def _not_evaluated(r: dict) -> list[str]:
    """Invariants that were not computed for this result (style only when not deliberately skipped)."""
    inv = r.get("invariants")
    if not isinstance(inv, dict):
        return list(INVARIANTS)
    return [k for k in INVARIANTS if inv.get(k) is None and not (k == "style" and _style_skipped(inv))]


def categorize(result: dict) -> list[str]:
    """Apply the gap taxonomy to one result. Order follows TAXONOMY."""
    r = _d(result)
    cats: set[str] = set()
    app, cal = r.get("app"), _d(r.get("calibre"))
    verdict = r.get("expected_verdict")
    app_ok = None
    text_loss = False

    if isinstance(app, dict):
        app_ok = app.get("ok")
        if app_ok is False:
            err = app.get("error")
            if _is_harness_err(err) or err == _NO_APP_META:
                cats.add("harness-error")
            elif _is_timeout(app):
                cats.add("app-timeout")
            elif verdict == "error" and _specific_app_message(app.get("status_text")):
                # a clean refusal is only acceptable when Calibre could not convert the book either
                cats.add("input-repair" if cal.get("ok") is True else "app-clean-error")
            else:
                cats.add("app-error")
    if _is_harness_err(cal.get("error")):
        cats.add("harness-error")

    gate = _d(r.get("gate"))
    for key, cat in GATE_CATS:
        g = _d(gate.get(key))
        if _is_harness_err(g.get("err")):
            cats.add("harness-error")
        elif g.get("ok") is False:
            cats.add(cat)

    inv = r.get("invariants")
    if isinstance(inv, dict):
        if "harness" in _d(inv.get("errors")):
            cats.add("harness-error")
        t = _d(inv.get("text"))
        sp, mt = _int(t.get("spine_items")), _int(t.get("matching_items"))
        if sp is not None and mt is not None and mt < sp:
            cats.add("text-loss")
            text_loss = True
        # garbled = the writer introduced U+FFFD or CSS-in-text that the input did not already have
        f_out = _int(t.get("replacement_chars"))
        f_in = _int(t.get("replacement_chars_input"))
        if f_in is None:
            f_in = _int(t.get("fffd_in"))
        if f_out is not None:
            garbled = f_out > (f_in or 0)
        else:
            fd = _d(t.get("first_diff"))
            garbled = ("\ufffd" in str(fd.get("ours_excerpt") or "")
                       and "\ufffd" not in str(fd.get("input_excerpt") or ""))
        if t.get("css_in_text") and not t.get("css_in_text_input"):
            garbled = True
        if garbled:
            cats.add("text-garbled")
        if (_int(t.get("non_xhtml_spine_items")) or 0) > 0:
            cats.add("spine-non-xhtml")   # the writer gap stays visible without counting as text-loss

        im = _d(inv.get("images"))
        n_dim = _int(im.get("dimension_mismatch"))
        n_missing = _int(im.get("missing"))
        if n_missing is not None:
            if n_missing > 0:
                cats.add("images-missing")
        else:
            n_in, n_hash = _int(im.get("input")), _int(im.get("matched_by_hash"))
            if n_in is not None and n_hash is not None and n_hash < n_in:
                cats.add("images-missing")
        if n_dim:
            cats.add("images-resized")
        if (_int(im.get("unextractable")) or 0) > 0:
            cats.add("images-unextractable")
        if (_int(im.get("refs_total")) or 0) > 0 and \
                ((_int(im.get("refs_wrong_image")) or 0) > 0 or (_int(im.get("refs_missing")) or 0) > 0):
            cats.add("images-misreferenced")

        toc = _d(inv.get("toc"))
        ti, to, tm = _int(toc.get("input_entries")), _int(toc.get("output_entries")), _int(toc.get("matched"))
        di, do = _int(toc.get("depth_in")), _int(toc.get("depth_out"))
        if ti and to == 0:
            cats.add("toc-missing")
        elif to and di is not None and do is not None and do < di:
            cats.add("toc-flat")
        if ti is not None and to is not None and tm is not None and tm < min(ti, to):
            cats.add("toc-labels")

        lk = _d(inv.get("links"))
        tot, res = _int(lk.get("internal_total")), _int(lk.get("resolved"))
        if tot is not None and res is not None and res < tot:
            cats.add("links-unresolved")

        st = _d(inv.get("style"))
        sc = _int(st.get("score"))
        # input_css_rules counts only style sheets reachable from an XHTML spine document (link, style,
        # @import chain), without @font-face blocks; input_css_rules_unreferenced is not used here
        css_in, css_out = _int(st.get("input_css_rules")), _int(st.get("output_css_rules"))
        # MOBI v6 has no style sheets at all (Calibre's .mobi has none either): rule count is KF8 only
        css_dropped = bool(css_in) and css_out == 0 and r.get("format") != "mobi"
        if (sc is not None and sc < 0.5) or css_dropped:
            cats.add("style-lost")
        dsc = _int(st.get("device_score"))
        if dsc is not None and dsc < DEVICE_STYLE_MIN and r.get("format") != "mobi":
            cats.add("device-style-lost")
        hy = _d(inv.get("layout_hygiene"))
        if any((_int(hy.get(k)) or 0) > 0 for k in HYGIENE_KEYS):
            cats.add("layout-hygiene")

    if _fixed_layout(r):
        cats.add("fixed-layout-unsupported")

    hd = _d(r.get("calibre_diff")).get("header_fields_diff")
    if isinstance(hd, list) and hd:
        cats.add("calibre-header-diff")

    # input-repair: we failed/lost text on a malformed book that Calibre handled. It replaces the
    # generic category it explains so the book is not counted in two buckets.
    if verdict in ("error", "warning") and cal.get("ok") is True:
        if "app-error" in cats:
            cats.discard("app-error")
            cats.add("input-repair")
        if text_loss:
            cats.discard("text-loss")
            cats.add("input-repair")

    return [c for c in TAXONOMY if c in cats]


def _kind(cat: str, result: dict) -> str:
    """Kind of one category instance; `text-loss` ('transform or repair') is resolved here:
    on a book that is valid (or has no verdict) the loss is our fault, so it counts as a writer bug.
    Every category of a fixed-layout book is out of scope."""
    kind = TAXONOMY[cat][1]
    if kind in KINDS_ACTIONABLE + ("transform or repair",) and _fixed_layout(result):
        return "out of scope"
    if kind == "transform or repair":
        return "input repair" if result.get("expected_verdict") in ("error", "warning") else "writer bug"
    return kind


# ── helpers ─────────────────────────────────────────────────────────────────

def _cats_of(r: dict) -> list[str]:
    """Always recomputed, so a report reflects the current taxonomy rules even for results whose
    stored `categories` were written by an older check run."""
    return categorize(r)


def _gate_failures(r: dict) -> list[str]:
    g = _d(r.get("gate"))
    return [k for k, _ in GATE_CATS
            if _d(g.get(k)).get("ok") is False and not _is_harness_err(_d(g.get(k)).get("err"))]


def _gate_pass(r: dict):
    """True/False when all three parsers ran, None when the gate was not evaluated."""
    g = _d(r.get("gate"))
    oks = [None if _is_harness_err(_d(g.get(k)).get("err")) else _d(g.get(k)).get("ok")
           for k, _ in GATE_CATS]
    if any(o is False for o in oks):
        return False
    if all(o is True for o in oks):
        return True
    return None


def _score(r: dict):
    return _int(_d(_d(r.get("invariants")).get("style")).get("score"))


def _device_score(r: dict):
    return _int(_d(_d(r.get("invariants")).get("style")).get("device_score"))


def mean_score(rs: list[dict], fn, cats=("se", "pg")):
    """(mean of fn(r) over the results of corpus categories `cats` where it is a number, n);
    (None, 0) when there is none (e.g. results written before the field existed)."""
    v = [s for r in rs if r.get("category") in cats and (s := fn(r)) is not None]
    return (sum(v) / len(v), len(v)) if v else (None, 0)


def hygiene_pooled(rs: list[dict], key: str = "layout_hygiene"):
    """{count: sum} of invariants[key] over the results that have it, plus "books" (results with the
    field) and "books_nonzero"; None when no result has it."""
    tot = dict.fromkeys(HYGIENE_KEYS + HYGIENE_EXTRA_KEYS, 0)
    books = nonzero = 0
    for r in rs:
        h = _d(r.get("invariants")).get(key)
        if not isinstance(h, dict):
            continue
        books += 1
        nonzero += any((_int(h.get(k)) or 0) for k in HYGIENE_KEYS)
        for k in HYGIENE_KEYS + HYGIENE_EXTRA_KEYS:
            tot[k] += _int(h.get(k)) or 0
    return {**tot, "books": books, "books_nonzero": nonzero} if books else None


def hygiene_str(h, keys=HYGIENE_KEYS) -> str:
    return "n/a" if not h else " / ".join(str(h.get(k, 0)) for k in keys)


def _frac(a, b) -> str:
    return "-" if a is None or b is None else f"{a}/{b}"


def _pct(n, d) -> str:
    return "n/a" if not d else f"{100 * n / d:.0f}%"


def _yn(v) -> str:
    return "-" if v is None else ("yes" if v else "no")


def _md(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _short_id(i: str, n: int = 52) -> str:
    """Keep the leading path segment and the distinctive tail of long ids."""
    i = i or "?"
    if len(i) <= n:
        return i
    first = i.split("/", 1)[0]
    return first + "/…" + i[-(n - len(first) - 2):]


def _trunc(s, n: int = 90) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _gate_why(g: dict, n: int = 70) -> str:
    """One short, readable line for a failed parser: a parser hint (e.g. the FDST mismatch) if there
    is one, else the last 'XxxError: ...' line (tracebacks), else the first non-empty line."""
    import re
    hints = g.get("hints")
    if isinstance(hints, list) and hints:
        return _trunc(hints[0], n)
    lines = [ln.strip() for ln in str(g.get("err") or "").splitlines() if ln.strip()]
    if not lines:
        return "no message"
    exc = [ln for ln in lines if re.match(r"^[\w.]*(Error|Exception)\b", ln)]
    return _trunc(exc[-1] if exc else lines[0], n)


# ── review ranking ──────────────────────────────────────────────────────────

def _review_candidates(rs: list[dict]) -> list[dict]:
    """Books worth opening in Kindle Previewer, worst first.

    Only books for which we have an output file are eligible; fixed-layout books (out of scope)
    are not. Tiers, in order:
      0 gate failure (more failing parsers first, then lower style score)
      1 images-misreferenced (largest fraction of wrong/missing references first)
      2 style-lost (lowest score first)
      3 text-loss (largest fraction of missing items first)
      4 links-unresolved (largest fraction unresolved first)
    """
    out = []
    for r in rs:
        if not _d(r.get("app")).get("ok") or _fixed_layout(r):
            continue
        cats = _cats_of(r)
        inv = _d(r.get("invariants"))
        fails = _gate_failures(r)
        sc = _score(r)
        t = _d(inv.get("text"))
        lk = _d(inv.get("links"))
        im = _d(inv.get("images"))
        st = _d(inv.get("style"))
        reasons = []
        if fails:
            errs = "; ".join(f"{k}: {_gate_why(_d(_d(r.get('gate')).get(k)))}" for k in fails)
            reasons.append(f"gate failed ({errs})")
        rt = im.get("refs_total") or 0
        rbad = (im.get("refs_wrong_image") or 0) + (im.get("refs_missing") or 0)
        if "images-misreferenced" in cats:
            reasons.append(f"image refs {im.get('refs_correct')}/{rt} correct "
                           f"({im.get('refs_wrong_image')} wrong, {im.get('refs_missing')} missing)")
        if "style-lost" in cats:
            why = f"style score {sc:.2f}" if sc is not None else "style score -"
            if st.get("input_css_rules") and st.get("output_css_rules") == 0 and r.get("format") != "mobi":
                why += f", output has 0 of {st.get('input_css_rules')} CSS rules"
            reasons.append(why)
        if "text-loss" in cats or ("input-repair" in cats and t.get("matching_items") is not None
                                   and t.get("matching_items") < (t.get("spine_items") or 0)):
            reasons.append(f"text {t.get('matching_items')}/{t.get('spine_items')} spine items match")
        if "links-unresolved" in cats:
            reasons.append(f"links {lk.get('resolved')}/{lk.get('internal_total')} resolved")
        if not reasons:
            continue
        sp, mt = t.get("spine_items") or 0, t.get("matching_items") or 0
        lt, lr = lk.get("internal_total") or 0, lk.get("resolved") or 0
        if fails:
            key = (0, -len(fails), sc if sc is not None else 1.0, 0.0)
        elif "images-misreferenced" in cats:
            key = (1, -(rbad / rt if rt else 0.0), 0.0, 0.0)
        elif "style-lost" in cats:
            key = (2, sc if sc is not None else 0.0, 0.0, 0.0)
        elif any(x.startswith("text") for x in reasons):
            key = (3, -((sp - mt) / sp if sp else 0.0), 0.0, 0.0)
        else:
            key = (4, -((lt - lr) / lt if lt else 0.0), 0.0, 0.0)
        out.append({"id": r.get("id"), "category": r.get("category"), "tier": key[0],
                    "reasons": reasons, "_key": key + (str(r.get("id")),)})
    out.sort(key=lambda x: x["_key"])
    for o in out:
        del o["_key"]
    return out


# ── aggregation ─────────────────────────────────────────────────────────────

_GAP_KINDS = KINDS_ACTIONABLE


def _actionable_kinds(r: dict, cats: list[str]) -> set[str]:
    return {_kind(c, r) for c in cats} & set(_GAP_KINDS)


def _aggregate(rs: list[dict]) -> dict:
    n = len(rs)
    converted = [r for r in rs if _d(r.get("app")).get("ok")]
    gate_known = [r for r in converted if _gate_pass(r) is not None]
    gate_ok = [r for r in gate_known if _gate_pass(r)]
    cal_ok = [r for r in rs if _d(r.get("calibre")).get("ok")]

    books_per_cat: Counter = Counter()      # every book, for the breakdown tables
    actionable_cat: Counter = Counter()     # books per category, counted only where actionable
    kind_inst: Counter = Counter()
    kind_books: Counter = Counter()
    kind_cat: dict[str, Counter] = defaultdict(Counter)
    by_corpus: dict[str, Counter] = defaultdict(Counter)
    corpus_n: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)
    not_eval: Counter = Counter()
    no_gap = gap_books = fixed = harness = not_full = 0
    cat_conv: Counter = Counter()           # actionable category -> converted books carrying it
    for r in rs:
        cats = _cats_of(r)
        corpus_n[r.get("category") or "?"] += 1
        kinds = set()
        for c in cats:
            k = _kind(c, r)
            books_per_cat[c] += 1
            by_corpus[r.get("category") or "?"][c] += 1
            kind_inst[k] += 1
            if k in _GAP_KINDS:
                kinds.add(k)
                actionable_cat[c] += 1
                kind_cat[k][c] += 1
                if len(examples[c]) < 3:
                    examples[c].append(r.get("id"))
        for k in kinds:
            kind_books[k] += 1
        if _d(r.get("app")).get("ok") and not _fixed_layout(r):
            for c in cats:
                if _kind(c, r) in _GAP_KINDS:
                    cat_conv[c] += 1
        ne = _not_evaluated(r)
        for k in ne:
            not_eval[k] += 1
        fixed += _fixed_layout(r)
        harness += "harness-error" in cats
        if kinds:
            gap_books += 1
        elif _fixed_layout(r):
            pass                                  # out of scope: neither a gap nor gap-free
        elif "harness-error" in cats or "app-clean-error" in cats or ne:
            not_full += 1                         # not (fully) evaluated: no claim either way
        else:
            no_gap += 1

    # a category on >= 90% of the converted, non-fixed-layout books is one systemic defect that
    # swamps the kind totals: also report the kinds with those categories left out
    n_eval = sum(1 for r in rs if _d(r.get("app")).get("ok") and not _fixed_layout(r))
    systemic = sorted(c for c, v in cat_conv.items() if n_eval and v >= 0.9 * n_eval)
    kind_books_ex: Counter = Counter()
    gap_books_ex = 0
    if systemic:
        for r in rs:
            ks = {_kind(c, r) for c in _cats_of(r) if c not in systemic} & set(_GAP_KINDS)
            gap_books_ex += bool(ks)
            for k in ks:
                kind_books_ex[k] += 1

    tot_gap = sum(kind_inst[k] for k in _GAP_KINDS)
    # shares count books (a book with two writer bugs counts once for "writer bug"); they are
    # fractions of the books with any actionable gap, so they can add up to more than 100%
    shares = {k: (kind_books[k] / gap_books if gap_books else 0.0) for k in _GAP_KINDS}

    ranked = sorted(actionable_cat.items(), key=lambda x: (-x[1], list(TAXONOMY).index(x[0])))
    top5 = [{"category": c, "books": n_, "description": TAXONOMY[c][0], "kind": TAXONOMY[c][1],
             "examples": examples[c]} for c, n_ in ranked[:5]]

    dominant = (max(_GAP_KINDS, key=lambda k: (kind_books[k], -_GAP_KINDS.index(k)))
                if gap_books else None)
    top_by_kind = {k: (max(kind_cat[k].items(), key=lambda x: (x[1], -list(TAXONOMY).index(x[0])))[0]
                       if kind_cat[k] else None) for k in _GAP_KINDS}

    return {
        "books": n, "converted": len(converted), "calibre_ok": len(cal_ok),
        "gate_evaluated": len(gate_known), "gate_pass": len(gate_ok),
        "gate_pass_rate": (len(gate_ok) / len(gate_known)) if gate_known else None,
        "gate_failures_by_parser": {k: sum(1 for r in converted if k in _gate_failures(r)) for k, _ in GATE_CATS},
        "category_books": dict(books_per_cat),
        "actionable_category_books": dict(actionable_cat),
        "kind_books": {k: kind_books[k] for k in _GAP_KINDS},
        "kind_instances": {k: kind_inst[k] for k in _GAP_KINDS},
        "kind_not_actionable": {k: v for k, v in kind_inst.items() if k not in _GAP_KINDS},
        "kind_shares": shares, "gap_instances": tot_gap, "books_with_gap": gap_books,
        "dominant_kind": dominant,
        "top_category_by_kind": top_by_kind,
        "top5": top5, "worst5": _review_candidates(rs)[:5],
        "by_corpus_category": {c: dict(v) for c, v in by_corpus.items()},
        "corpus_category_books": dict(corpus_n),
        "systemic_categories": {c: cat_conv[c] for c in systemic},
        "systemic_eval_books": n_eval,
        "kind_books_excl_systemic": {k: kind_books_ex[k] for k in _GAP_KINDS} if systemic else None,
        "books_with_gap_excl_systemic": gap_books_ex if systemic else None,
        "books_with_no_gap": no_gap,
        "books_not_fully_evaluated": not_full,
        "books_fixed_layout": fixed, "books_harness_error": harness,
        "invariants_not_evaluated": {k: not_eval[k] for k in INVARIANTS},
        "style_score_se_pg": mean_score(rs, _score),
        "device_score_se_pg": mean_score(rs, _device_score),
        "layout_hygiene_pooled": hygiene_pooled(rs),
        "layout_hygiene_input_pooled": hygiene_pooled(rs, "layout_hygiene_input"),
    }


def _summary_paragraph(fmt: str, a: dict) -> str:
    n, conv = a["books"], a["converted"]
    s = [f"{n} books were run for {fmt.upper()}; {conv} ({_pct(conv, n)}) produced an output file"]
    if n - conv:
        s[0] += f" and {n - conv} did not"
    s[0] += "."
    if a["calibre_ok"] < n:
        s[0] += f" Calibre itself converted {a['calibre_ok']} of {n}."
    if a["gate_evaluated"]:
        fails = {k: v for k, v in a["gate_failures_by_parser"].items() if v}
        extra = (" Failures by parser: " + ", ".join(f"{k} {v}" for k, v in fails.items()) + ".") if fails else ""
        s.append(f"{a['gate_pass']} of {a['gate_evaluated']} ({_pct(a['gate_pass'], a['gate_evaluated'])}) "
                 f"converted books pass all three parser gates (mobitool, KindleUnpack, Calibre reader).{extra}")
    else:
        s.append("No book reached the parser gates, so the gate pass rate is not available.")
    gb = a["books_with_gap"]
    if gb:
        kb = a["kind_books"]
        parts = [f"{kb[k]} have {k} gaps ({_pct(kb[k], gb)})" for k in KINDS_ACTIONABLE]
        s.append(f"{gb} books carry at least one actionable gap (a book can carry several kinds): "
                 + ", ".join(parts) + f"; {a['gap_instances']} category findings in total.")
        dom = a["dominant_kind"]
        top = a["top_category_by_kind"].get(dom)
        verdict = (f"Verdict: {dom} gaps affect the most books ({_pct(kb[dom], gb)}), so the next effort "
                   f"should {KIND_ADVICE[dom]}" + (f", starting with `{top}`." if top else "."))
        if sum(1 for v in kb.values() if v == max(kb.values())) > 1:
            verdict = "Verdict: no single kind of gap dominates (a tie at the top); see the table below."
        s.append(verdict)
        if a.get("systemic_categories"):
            sysc = ", ".join(f"`{c}` ({v} of {a['systemic_eval_books']} converted books)"
                             for c, v in a["systemic_categories"].items())
            kx, gx = a["kind_books_excl_systemic"], a["books_with_gap_excl_systemic"]
            tie = gx and sum(1 for v in kx.values() if v == max(kx.values())) > 1
            domx = max(KINDS_ACTIONABLE, key=lambda k: (kx[k], -KINDS_ACTIONABLE.index(k)))
            s.append(f"Systemic defect(s) dominate the totals: {sysc}. Leaving them out, {gx} books still carry "
                     "an actionable gap: " + ", ".join(f"{kx[k]} {k} ({_pct(kx[k], gx)})" for k in KINDS_ACTIONABLE)
                     + ("." if not gx or tie else f"; {domx} gaps dominate once the systemic defect is set aside."))
    else:
        s.append("No actionable gap categories were found, so there is nothing to attribute.")
    s.append(f"{a['books_with_no_gap']} of {n} books have no actionable gap and were fully evaluated"
             + (f"; {a['books_not_fully_evaluated']} more book{'s' if a['books_not_fully_evaluated'] != 1 else ''} "
                "with no gap found "
                f"{'were' if a['books_not_fully_evaluated'] != 1 else 'was'} not fully evaluated "
                "(harness error, clean refusal or missing invariants)" if a["books_not_fully_evaluated"] else "")
             + (f"; {a['books_fixed_layout']} fixed-layout books are out of scope and not counted"
                if a["books_fixed_layout"] else "") + ".")
    ms, ns = a.get("style_score_se_pg") or (None, 0)
    md, nd = a.get("device_score_se_pg") or (None, 0)
    if ms is not None or md is not None:
        s.append(f"Mean style score on se+pg books: preservation {'n/a' if ms is None else f'{ms:.3f} (n={ns})'}"
                 + (f", Kindle device model {'n/a' if md is None else f'{md:.3f} (n={nd})'}" if fmt != "mobi" else "")
                 + ".")
    hy, hyi = a.get("layout_hygiene_pooled"), a.get("layout_hygiene_input_pooled")
    if hy:
        s.append(f"Layout hygiene, pooled over {hy['books']} books (empty blocks / trailing breaks / whitespace "
                 f"runs / nbsp indents): output {hygiene_str(hy)}, input {hygiene_str(hyi)}; "
                 f"{hy['books_nonzero']} books have at least one in the output. Not counted in "
                 "`layout-hygiene` (styled empty blocks / double trailing breaks / ambiguous nbsp indents): "
                 f"output {hygiene_str(hy, HYGIENE_EXTRA_KEYS)}, input {hygiene_str(hyi, HYGIENE_EXTRA_KEYS)}.")
    ne = {k: v for k, v in a["invariants_not_evaluated"].items() if v}
    if ne:
        s.append("Invariants not evaluated (books): " + ", ".join(f"{k} {v}" for k, v in ne.items()) + ".")
    if a["books_harness_error"]:
        s.append(f"{a['books_harness_error']} books hit a harness error and say nothing about the app.")
    na = {k: v for k, v in a["kind_not_actionable"].items()}
    if na:
        s.append("Not counted above (category findings): "
                 + ", ".join(f"{v} {k}" for k, v in sorted(na.items())) + ".")
    return " ".join(s)


# ── markdown ────────────────────────────────────────────────────────────────

def _table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_md(c) for c in row) + " |")
    return out


def _fmt_section(fmt: str, rs: list[dict], a: dict) -> list[str]:
    L = [f"## Format: {fmt}", "", "### 1. Summary", "", _summary_paragraph(fmt, a), ""]

    L += ["### 2. Top gap categories by affected books", ""]
    if a["top5"]:
        L += _table(["#", "category", "books", "% of books", "description", "kind"],
                    [[i + 1, f"`{t['category']}`", t["books"], _pct(t["books"], a["books"]),
                      t["description"], t["kind"]] for i, t in enumerate(a["top5"])])
        L += ["", ("Informational, acceptable, harness and out-of-scope categories are not ranked here "
              "(`calibre-header-diff`, `images-resized`, `images-unextractable`, `spine-non-xhtml`, `layout-hygiene`, "
              "`app-clean-error`, `harness-error`, "
              "`fixed-layout-unsupported`), and nothing on a fixed-layout book is; "
              "they appear in the per-category breakdown and the per-book table. "
              "`text-loss` counts as `input repair` on books whose verdict is error/warning, otherwise as `writer bug`."), ""]
    else:
        L += ["No actionable gap categories.", ""]

    L += ["### 3. Books most needing a manual look in Kindle Previewer", ""]
    if a["worst5"]:
        L += [("Ranked: gate failure, then misreferenced images, then lowest style score, then text-loss, "
               "then unresolved links. Only books with an output file are eligible; fixed-layout books are not."), ""]
        L += _table(["#", "book", "corpus category", "why"],
                    [[i + 1, f"`{_short_id(w['id'], 64)}`", w["category"], "; ".join(w["reasons"])]
                     for i, w in enumerate(a["worst5"])])
        L += [""]
    else:
        L += [("No converted book has a gate failure, misreferenced images, lost style, lost text or "
               "unresolved links."), ""]

    L += ["### 4. Gap categories by corpus category", ""]
    cols = [c for c in TAXONOMY if a["category_books"].get(c)]
    if cols:
        rows = []
        for cc in sorted(a["corpus_category_books"]):
            cnt = a["by_corpus_category"].get(cc, {})
            rows.append([cc, a["corpus_category_books"][cc]] + [cnt.get(c, "") or "" for c in cols])
        tot_row = ["**total**", a["books"]] + [a["category_books"].get(c, 0) for c in cols]
        L += _table(["corpus category", "books"] + [f"`{c}`" for c in cols], rows + [tot_row]) + [""]
    else:
        L += ["No gap categories were assigned.", ""]

    L += ["### 5. All books", ""]
    hdr = ["id", "category", "verdict", "app ok", "calibre ok", "gate pass", "text match/spine",
           "images matched/referenced", "image refs ok/total", "toc matched/input", "links resolved/total",
           "style", "device style", "hygiene out (e/b/ws/nb)", "css rules out/in", "categories"]
    rows = []
    for r in sorted(rs, key=lambda x: str(x.get("id"))):
        inv = _d(r.get("invariants"))
        t, im, toc, lk, st = (_d(inv.get(k)) for k in ("text", "images", "toc", "links", "style"))
        sc = _score(r)
        if im.get("referenced") is not None:
            img = _frac(im.get("referenced_matched_by_hash"), im.get("referenced"))
        else:
            img = _frac(im.get("matched_by_hash"), im.get("input"))
        rows.append([f"`{_short_id(r.get('id'))}`", r.get("category") or "-", r.get("expected_verdict") or "-",
                     _yn(_d(r.get("app")).get("ok")), _yn(_d(r.get("calibre")).get("ok")),
                     _yn(_gate_pass(r)),
                     _frac(t.get("matching_items"), t.get("spine_items")),
                     img, _frac(im.get("refs_correct"), im.get("refs_total")),
                     _frac(toc.get("matched"), toc.get("input_entries")),
                     _frac(lk.get("resolved"), lk.get("internal_total")),
                     "-" if sc is None else f"{sc:.2f}",
                     "-" if _device_score(r) is None else f"{_device_score(r):.2f}",
                     "-" if not isinstance(inv.get("layout_hygiene"), dict) else
                     "/".join(str(_int(inv["layout_hygiene"].get(k)) or 0) for k in HYGIENE_KEYS),
                     _frac(st.get("output_css_rules"), st.get("input_css_rules")),
                     ", ".join(_cats_of(r)) or "-"])
    L += _table(hdr, rows) + [""]
    return L


def write_report(results: list[dict], out_md: Path, out_json: Path, *, subset: str) -> None:
    out_md, out_json = Path(out_md), Path(out_json)
    by_fmt: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_fmt[r.get("format") or "azw3"].append(r)
    fmts = sorted(by_fmt, key=lambda f: (f != "azw3", f))
    aggs = {f: _aggregate(by_fmt[f]) for f in fmts}

    today = _dt.date.today().isoformat()
    L = [f"# Converter quality report: {subset} ({today})", "",
         (f"{len(results)} results across {', '.join(fmts) or 'no formats'}. "
          "Gap categories and their kinds are defined in `tests/harness/schema.md`; "
          "a book can carry several categories."), ""]
    for f in fmts:
        L += _fmt_section(f, by_fmt[f], aggs[f])
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")

    summary = {"subset": subset, "date": today, "total_results": len(results), "formats": aggs}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
