# /// script
# requires-python = ">=3.13"
# dependencies = ["playwright", "pillow", "lxml"]
# ///
"""Self-test of the visibility check (oracles._COLLECT_JS `vt`, _VisAcc, report/compare wiring).

    uv run tests/harness/test_visibility.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compare as C  # noqa: E402
import oracles as O  # noqa: E402
import report as R  # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


# ── rendering: which texts does Chromium show? ───────────────────────────────

XHTML = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title><style>{css}</style></head><body>{body}</body></html>'

# (text, css, markup around it with {t}); the expected visible flag follows
CASES = [
    ("plain text visible", "", "<p>{t}</p>", True),
    ("hidden attribute (UA rule)", "", "<h2 hidden='hidden'>{t}</h2>", False),
    ("hidden attribute beaten by author display:block", "h2 {{ display: block }}", "<h2 hidden='hidden'>{t}</h2>", True),
    ("display none", ".x {{ display: none }}", "<p class='x'>{t}</p>", False),
    ("display none ancestor", ".x {{ display: none }}", "<div class='x'><p><b>{t}</b></p></div>", False),
    ("visibility hidden", ".x {{ visibility: hidden }}", "<p class='x'>{t}</p>", False),
    ("visibility collapse", ".x {{ visibility: collapse }}", "<p class='x'>{t}</p>", False),
    ("visibility hidden, child visible", ".x {{ visibility: hidden }} b {{ visibility: visible }}",
     "<p class='x'><b>{t}</b></p>", True),
    ("clip rect", ".x {{ position: absolute; clip: rect(1px, 1px, 1px, 1px) }}", "<p class='x'>{t}</p>", False),
    ("clip rect 0", ".x {{ position: absolute; clip: rect(0 0 0 0) }}", "<p class='x'>{t}</p>", False),
    ("clip-path inset 50%", ".x {{ clip-path: inset(50%) }}", "<p class='x'>{t}</p>", False),
    ("clip-path inset 10%", ".x {{ clip-path: inset(10%) }}", "<p class='x'>{t}</p>", True),
    ("1px box overflow hidden", ".x {{ width: 1px; height: 1px; overflow: hidden }}", "<div class='x'><p>{t}</p></div>", False),
    ("0 height overflow hidden", ".x {{ height: 0; overflow: hidden }}", "<div class='x'><p>{t}</p></div>", False),
    ("1px box without overflow clip", ".x {{ width: 1px; height: 1px }}", "<div class='x'>{t}</div>", True),
    ("off page left", ".x {{ position: absolute; left: -9999px }}", "<p class='x'>{t}</p>", False),
    ("off page text-indent", ".x {{ text-indent: -9999px }}", "<p class='x'>{t}</p>", False),
    ("just off page", ".x {{ position: absolute; left: -100px }}", "<p class='x'>{t}</p>", True),
    ("font-size 0", ".x {{ font-size: 0 }}", "<p class='x'>{t}</p>", False),
    ("display contents", ".x {{ display: contents }}", "<div><p class='x'>{t}</p></div>", True),
    ("long page, text far below", "", "<div style='height: 5000px'></div><p>{t}</p>", True),
    # normal-flow overflow to the right (wide table, unwrapped <pre> line) is not a hiding idiom
    ("wide table, cell text beyond the viewport", "td {{ width: 1500px }}",
     "<table><tr><td>filler</td><td>{t}</td></tr></table>", True),
    ("unwrapped pre line, text beyond the viewport", "", "<pre>" + "x" * 200 + "<b>{t}</b></pre>", True),
    ("positioned far right", ".x {{ position: absolute; left: 9999px }}", "<p class='x'>{t}</p>", False),
    ("positioned far right (ancestor)", ".x {{ position: relative; left: 3000px }}", "<div class='x'><p>{t}</p></div>", False),
]


def test_render(page) -> None:
    args = {"props": O.STYLE_PROPS, "anchors": sorted(O.ANCHOR_TAGS), "hidden": False, "mobiCss": None,
            "mobiBaseCss": O.MOBI_BASE_CSS, "mobiNoBox": O.MOBI_NO_BOX}
    for k, (name, css, markup, want) in enumerate(CASES):
        t = f"Marker text number {k}"
        page.set_content(XHTML.format(css=css.replace("{{", "{").replace("}}", "}"), body=markup.format(t=t)))
        d = page.evaluate(O._COLLECT_JS, args)
        got = {o.strip(): bool(v) for o, v in d["vt"]}.get(t)
        check(f"render: {name}", got, want)
    # elements without text of their own are not recorded; whitespace-only text neither
    page.set_content(XHTML.format(css="", body="<div> <p> </p><p><b>x y</b></p></div>"))
    check("render: text-bearing only", [o for o, _ in page.evaluate(O._COLLECT_JS, args)["vt"]], ["x y"])


# ── matching ─────────────────────────────────────────────────────────────────

def rows(*items, ch=0):
    return [(ch, t, 1 if v else 0) for t, v in items]


def run(rin, rout):
    acc = O._VisAcc()
    acc.add(rin, [(None, t, v) for _, t, v in rout])
    return acc.result()


def test_matching() -> None:
    body = ("Some visible paragraph one", True), ("Another visible paragraph", True)
    # the regression: a hidden title shown in the output
    r = run(rows(("Here, Perfect to a Wish", False), *body), rows(("Here,  Perfect to a Wish", True), *body))
    check("hidden->shown chars", r["hidden_in_input_shown_out_chars"], 19)
    check("hidden->shown elements", r["hidden_in_input_shown_out_elements"], 1)
    check("hidden->shown example", r["examples"]["hidden_in_input_shown_out"],
          [{"chapter": 0, "text": "Here, Perfect to a Wish", "chars": 19}])
    check("shown->hidden none", r["shown_in_input_hidden_out_chars"], 0)
    # reverse: visible in the input, hidden in the output
    r = run(rows(("A visible title here", True), *body), rows(("A visible title here", False), *body))
    check("shown->hidden", (r["hidden_in_input_shown_out_chars"], r["shown_in_input_hidden_out_chars"]), (0, 17))
    # hidden on both sides: nothing
    r = run(rows(("Hidden both title", False), *body), rows(("Hidden both title", False), *body))
    check("hidden both", (r["hidden_in_input_shown_out_chars"], r["shown_in_input_hidden_out_chars"]), (0, 0))
    # text loss is not a visibility change
    r = run(rows(("Hidden title lost", False), *body), rows(*body))
    check("lost hidden", r["hidden_in_input_shown_out_chars"], 0)
    r = run(rows(("Visible title lost", True), *body), rows(*body))
    check("lost visible", r["shown_in_input_hidden_out_chars"], 0)
    # a text visible on both sides as often cancels (a hidden copy of a visible heading)
    r = run(rows(("Chapter One", False), ("Chapter One", True), *body),
            rows(("Chapter One", False), ("Chapter One", True), *body))
    check("cancels", r["hidden_in_input_shown_out_chars"], 0)
    # the output splits a text over inline elements: matched on the whitespace-free concatenation
    r = run(rows(("Hidden Title Words", False), *body), rows(("Hidden", True), ("Title Words", True), *body))
    check("split output", r["hidden_in_input_shown_out_chars"], 16)
    # short texts are not matched; the count is bounded by the number of hidden elements
    r = run(rows(("12", False), *body), rows(("12", True), *body))
    check("short", r["hidden_in_input_shown_out_chars"], 0)
    r = run(rows(("Folio page", False), *body), rows(("Folio page", True), ("Folio page", True), *body))
    check("bounded", r["hidden_in_input_shown_out_elements"], 1)
    # an output element hidden: the chapter is the input element's (concat mode)
    r = run(rows(("Title in two", True), ch=3) + rows(*body, ch=4), rows(("Title in two", False), *body))
    check("out chapter", r["examples"]["shown_in_input_hidden_out"][0]["chapter"], 3)
    # examples: at most 5 per direction, text <= 80 chars
    many = [(f"Hidden title number {i:03d} " + "x" * 90, False) for i in range(9)]
    r = run(rows(*many, *body), rows(*[(t, True) for t, _ in many], *body))
    check("example cap", (len(r["examples"]["hidden_in_input_shown_out"]), r["hidden_in_input_shown_out_elements"]), (5, 9))
    check("example width", max(len(e["text"]) for e in r["examples"]["hidden_in_input_shown_out"]), 80)


# ── category and comparison ──────────────────────────────────────────────────

def result(hs=0, sh=0, dhs=0, dsh=0, with_field=True) -> dict:
    st = {"score": 1.0, "device_score": 1.0}
    if with_field:
        st["visibility"] = {"hidden_in_input_shown_out_chars": hs, "shown_in_input_hidden_out_chars": sh}
        st["device_visibility"] = {"hidden_in_input_shown_out_chars": dhs, "shown_in_input_hidden_out_chars": dsh}
    return {"id": "x", "sha256": "s", "format": "azw3", "category": "se", "expected_verdict": "valid",
            "app": {"ok": True}, "calibre": {"ok": True},
            "gate": {k: {"ok": True} for k in ("mobitool", "kindleunpack", "calibre_reader")},
            "invariants": {"style": st}}


def test_report() -> None:
    n = R.VISIBILITY_MIN_CHARS
    check("category below", "visibility-changed" in R.categorize(result(n, n, n, n)), False)
    check("category hidden->shown", "visibility-changed" in R.categorize(result(n + 1)), True)
    check("category shown->hidden", "visibility-changed" in R.categorize(result(0, n + 1)), True)
    check("category device only", "visibility-changed" in R.categorize(result(dsh=n + 1)), True)
    check("category old result", "visibility-changed" in R.categorize(result(with_field=False)), False)
    check("kind", R.TAXONOMY["visibility-changed"][1], "unported Calibre transform")
    p = R.visibility_pooled([result(30, 5), result(0, 0), result(with_field=False)])
    check("pooled", p, {"hidden_shown": 30, "shown_hidden": 5, "books": 2, "books_over": 1})
    check("pooled none", R.visibility_pooled([result(with_field=False)]), None)
    check("cell", R._vis_cell({"visibility": {"hidden_in_input_shown_out_chars": 3},
                               "device_visibility": {"shown_in_input_hidden_out_chars": 4}}), "3/0 (0/4)")
    check("cell old", R._vis_cell({}), "-")
    # compare: a rise is a regression, equal/lower is not, a baseline without the field is not compared
    why = lambda b, a: [k for k, _ in C._regression_reasons(b, a, C._cats(b), C._cats(a))]  # noqa: E731
    check("regress rise", "visibility changed" in why(result(0), result(5)), True)
    check("regress device rise", "device visibility changed" in why(result(), result(dsh=7)), True)
    check("no regress equal", why(result(30), result(30)).count("visibility changed"), 0)
    check("no regress lower", [w for w in why(result(30, 30), result(10, 5)) if "visibility" in w], [])
    check("old baseline", [w for w in why(result(with_field=False), result(50)) if w == "visibility changed"], [])
    check("old baseline not a new category", "new category" in why(result(with_field=False), result(50)), False)
    check("new category", "new category" in why(result(0), result(50)), True)
    m = C._metrics([result(30, 5)])
    check("metric", R.visibility_str(m["visibility"]), "30 / 5")
    rendered = C.render(C.compare([result(0)], [result(30, 5)]), "x")
    check("render row", "visibility changed, pooled chars (hidden→shown / shown→hidden) | 0 / 0 | 30 / 5" in rendered, True)


def main() -> int:
    test_matching()
    test_report()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright missing: render tests skipped")
    else:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                page = b.new_context(viewport=O.STYLE_VIEWPORT).new_page()
                test_render(page)
            finally:
                b.close()
    for f in FAILS:
        print("FAIL", f)
    print("visibility self-test:", "OK" if not FAILS else f"{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
