# /// script
# requires-python = ">=3.13"
# dependencies = ["lxml"]
# ///
"""Self-test of device.py (CSS device-model rewriter, layout-hygiene counters).

    uv run tests/harness/test_device.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lxml import etree  # noqa: E402

import device as D  # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def norm(css: str) -> str:
    return " ".join(css.split())


def test_css() -> None:
    st = Counter()
    css = """@charset "utf-8";
@namespace epub "http://www.idpf.org/2007/ops";
@import url("other.css");
@import "print.css" print;
@import url(https://example.com/x.css);
/* a { comment } with braces */
p { margin: 0; text-indent: 1em }
h2 + p, h2 ~ p, p.first { text-indent: 0 }
@media (min-width: 10em) { p { color: red } div { color: blue } }
@supports (display: grid) { .g { display: grid } }
@layer base { p { color: green } }
@layer base, extra;
[epub|type~="z3998:poem"] p { margin-left: 2em }
abbr[title], abbr { font-variant: small-caps }
p:not(.x), li:nth-child(2n+1), li:last-child, p:first-child, a:link, p::first-letter, p:first-line { color: black }
section > p:first-of-type { x: 1 }
.a\\+b, .c\\~d { content: "+ ~ [ { } ;" }
.q { content: '}'; background: url(img{x}.png) }
epub|x { y: 1 }
"""
    out = D.device_css(css, st)
    want = norm("""@import url("other.css");
p { margin: 0; text-indent: 1em }
p.first { text-indent: 0 }
abbr { font-variant: small-caps }
p:first-child, a:link, p::first-letter, p:first-line { color: black }
.a\\+b, .c\\~d { content: "+ ~ [ { } ;" }
.q { content: '}'; background: url(img{x}.png) }
""")
    check("device_css", norm(out), want)
    check("stats media", st["at:media"], 1)
    check("stats layer", st["at:layer"], 2)
    check("stats namespace", st["at:namespace"], 1)
    check("stats import", st["import"], 2)
    check("stats rules dropped", st["rules"], 3)   # [epub|type] p, section > p:first-of-type, epub|x
    # unterminated block / string at the end of the sheet do not loop or crash
    check("unterminated", norm(D.device_css("p { color: red")), "p { color: red}")
    check("unterminated str", D.device_css('p { content: "abc'), 'p { content: "abc}\n')
    check("stray brace", norm(D.device_css("} p { a: b }")), "} p { a: b }")
    check("cdo", norm(D.device_css("<!-- p { a: b } -->")), "p { a: b }")
    check("selector comment", norm(D.device_css("h1 /* + */ , h2+p { a: b }")), "h1 { a: b }")
    check("split", D.split_selectors('a, b:is(c, d), [x=","]'), ["a", " b:is(c, d)", ' [x=","]'])
    check("nested at", norm(D.device_css("@media print { @media screen { p { a: b } } } q { c: d }")), "q { c: d }")
    check("font-face kept", "@font-face" in D.device_css("@font-face { font-family: x; src: url(a.ttf) }"), True)


def test_document() -> None:
    st = Counter()
    doc = (b'<?xml version="1.0"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title>'
           b'<style type="text/css"><![CDATA[ h2 + p { a: b } p { c: d } ]]></style>'
           b"<style><!-- h2 + p { a: b } --></style><style/></head><body><p>x</p></body></html>")
    out = D.device_document(doc, st)
    check("ua first", out.index(b"text-indent: 1.5em") < out.index(b"<title>"), True)
    check("cdata kept", b"<![CDATA[" in out and b"h2 + p" not in out.split(b"<!--")[0], True)
    check("comment style untouched", b"<!-- h2 + p { a: b } -->" in out, True)
    etree.fromstring(out)   # still well-formed
    ref = D.input_reference_document(b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>x</p></body></html>')
    check("input ref", ref.endswith(D.INPUT_PAGE_STYLE + b"</body></html>"), True)
    etree.fromstring(ref)
    check("input ref utf16", D.input_reference_document(b"\xff\xfe<\x00"), b"\xff\xfe<\x00")
    check("no head", D.device_document(b"<html><body/></html>").startswith(b"<html><head><style"), True)


def body_of(markup: str):
    root = etree.fromstring(f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{markup}</body></html>')
    return root[0]


def hyg(markup: str, pre=(set(), set()), markers=(set(), set())) -> dict:
    c = D.layout_hygiene_doc(body_of(markup), pre, markers=markers)
    return {k: c[k] for k in D.HYGIENE_KEYS + D.HYGIENE_EXTRA_KEYS}


def test_hygiene() -> None:
    z = dict.fromkeys(D.HYGIENE_KEYS + D.HYGIENE_EXTRA_KEYS, 0)
    check("clean", hyg("<p>a b</p><p>c</p>"), z)
    check("empty p", hyg("<p></p><div> </div><p>\u00a0</p><p><br/></p><p id='x'></p><p><!-- c --></p>"),
          {**z, "empty_blocks": 3})
    check("empty styled", hyg("<div class='kp1'></div><div class='kp2 x'/><p style='page-break-after: always'/>"
                              "<div class='kp3'></div>", markers=(set(), {"kp1", "kp2"})),
          {**z, "empty_blocks": 1, "empty_blocks_styled": 3})
    tags, classes = D.marker_selectors([".kp1 { margin: 0 } .kp2 { page-break-before: always } "
                                        "div.kp3 { border-top: 1px solid } .kp4 { line-height: 2 } "
                                        ".kp5 { min-height: 1em } .kp6 { padding-top: 1em }"])
    check("marker selectors", (tags, classes), (set(), {"kp2", "kp3", "kp5", "kp6"}))
    check("trailing br", hyg("<p>a<br/></p><li>b<br/> </li><p><br/></p><p><br/><br/></p>"
                             "<p>a<br/>b</p><p><span>a<br/></span></p><p><img/><br/></p>"
                             "<p class='kp15'><br /></p><p><a id='p5'></a><br/></p><p>x<a id='q'/><br/></p>"),
          {**z, "trailing_breaks": 5})
    check("double br", hyg("<p>text<br/><br/></p><p>Frietchie.<br /><br /></p><p><i>a</i><br/> <br/><br/></p>"
                           "<div><p>x</p><br/></div>"),
          {**z, "trailing_breaks_double": 3})
    check("ws runs", hyg("<p>a\nb</p>\n<p>a  b</p><p>a\tb</p><pre>a\n  b</pre><p>a\u00a0 b</p>"),
          {**z, "whitespace_runs": 4})
    check("ws in styled pre", hyg("<div style='white-space: pre-wrap'>a\n b</div><div class='v x'>a\n</div>",
                                  ({"q"}, {"v"})), z)
    check("nbsp", hyg("<p>\u00a0\u00a0a</p><p>\u00a0a</p><div><p>\u00a0\u00a0x</p></div>"
                      "<p><span>\u00a0</span>\u00a0y</p><p> \u00a0\u00a0z</p>"),
          {**z, "nbsp_indents": 4})
    check("nbsp ambiguous", hyg("<p>\u00a0\u00a0\"I wish<br/>\u00a0\u00a0Some line</p>"
                                "<div>\u00a0\u00a0\u201d\u00a0\u00a0C.H. Allen</div>"
                                "<div>\u00a0\u00a0x<p>y</p></div>"
                                "<p>\u00a0\u00a0\"Long ago<br/>I was</p>"),
          {**z, "nbsp_indents": 1, "nbsp_indents_ambiguous": 3})
    tags, classes = D.pre_selectors(["pre.code, .verse { white-space: pre-line } div p { white-space: pre }"
                                     " .no { white-space: normal }"])
    check("pre selectors", (tags, classes), ({"p"}, {"code", "verse"}))


def main() -> int:
    test_css()
    test_document()
    test_hygiene()
    for f in FAILS:
        print("FAIL", f)
    print("device self-test:", "OK" if not FAILS else f"{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
