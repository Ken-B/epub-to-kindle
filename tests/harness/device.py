"""device: a Kindle "device model" for the AZW3 style oracle, and static layout-hygiene counters.

    from device import KINDLE_UA_CSS, device_css, device_document, layout_hygiene_doc

* ``device_css(css, stats)`` rewrites one style sheet into what the device model assumes a Kindle
  applies (see DEVICE_MODEL below); ``device_document(data, stats)`` does the same for the inline
  ``<style>`` blocks of an (X)HTML document and puts KINDLE_UA_CSS in front of every author sheet.
  oracles.inv_style serves the output documents through these (Playwright route fulfil) and scores
  the result against the browser rendering of the input (``style.device_score``).
* ``layout_hygiene_doc(root, pre, counts, examples)`` counts markup that renders badly on a Kindle
  (empty paragraphs, trailing <br>, raw whitespace runs, &nbsp; indents) in one parsed document.

Pure standard library (the hygiene counters walk an lxml tree they are given). The CSS rewriter is a
small tokeniser, not a regex over the sheet: strings, comments, escapes, ``url(...)`` and nested
blocks are skipped as units, so a ``{`` in a string or an escaped ``\\+`` in a class name cannot
derail it. Self-test: ``uv run tests/harness/test_device.py``.
"""
from __future__ import annotations

import re
from collections import Counter

# ════════════════════════════════════════════════════════════════════════════
# device model
# ════════════════════════════════════════════════════════════════════════════

DEVICE_MODEL = "kindle-v1"   # bump when KINDLE_UA_CSS or the rewrite rules change

# Kindle UA approximation, applied as the FIRST style sheet of every output document (under the author
# sheets, which override it rule by rule). A tunable MODEL ASSUMPTION, not a measured fact: it encodes
# where Kindle readers are believed to differ from a browser, so that a default the writer leaves
# unpinned (a <p> whose margins the author never set, an hgroup relying on display:block) is
# penalised. p and blockquote are the same assumption as oracles.MOBI_BASE_CSS (Calibre's MobiReader
# base CSS); the HTML5 sectioning/grouping elements are treated as unknown elements (inline).
KINDLE_UA_CSS = """\
p { margin: 0; text-indent: 1.5em }
blockquote { margin: 0 0 0 2em }
h1, h2, h3, h4, h5, h6 { margin: 0 }
ul, ol { margin: 0; padding-left: 2em }
section, article, aside, nav, header, footer, main, figure, figcaption, hgroup, details, summary { display: inline }
"""

# at-rules removed with their whole block (never inlined): conditional/grouping rules a Kindle is
# assumed not to evaluate, and @namespace (so namespace-qualified selectors go too, see _selector_ok)
DROP_AT_RULES = frozenset({"media", "supports", "namespace", "layer", "container", "scope", "document",
                           "-moz-document", "starting-style"})
# pseudo-classes whose selectors are dropped: the logical combinators and every structural one but
# :first-child. Others (:link, :visited, :lang(), :hover...) and pseudo-elements (::before,
# :first-letter, ...) are kept.
DROP_PSEUDO = frozenset({
    "not", "is", "where", "has", "matches", "any", "-webkit-any", "-moz-any",
    "root", "empty", "last-child", "only-child", "nth-child", "nth-last-child", "nth-of-type",
    "nth-last-of-type", "first-of-type", "last-of-type", "only-of-type", "nth-col", "nth-last-col",
})

_WS = " \t\n\r\f"
_IDENT_RE = re.compile(r"-?(?:[A-Za-z_\-]|[^\x00-\x7f]|\\.)(?:[A-Za-z0-9_\-]|[^\x00-\x7f]|\\.)*", re.S)
_URL_START_RE = re.compile(r"url\(", re.I)


def _skip_comment(s: str, i: int) -> int:
    """s[i:i+2] == '/*': index after the closing '*/' (an unclosed comment runs to the end)."""
    j = s.find("*/", i + 2)
    return len(s) if j < 0 else j + 2


def _skip_string(s: str, i: int) -> int:
    """s[i] is a quote: index after the closing quote. Backslash escapes are skipped; an unescaped
    newline ends the (bad) string, as in CSS Syntax."""
    q, n = s[i], len(s)
    i += 1
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == q:
            return i + 1
        if c == "\n":
            return i
        i += 1
    return n


def _skip_url(s: str, i: int) -> int | None:
    """At `url(` (s[i] == 'u'/'U', preceded by a non-name char): for an UNQUOTED url, the index after
    its ')'; None when the argument is quoted (then it is an ordinary function, the string is skipped
    by the caller)."""
    j, n = i + 4, len(s)
    while j < n and s[j] in _WS:
        j += 1
    if j < n and s[j] in "\"'":
        return None
    while j < n:
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == ")":
            return j + 1
        j += 1
    return n


def _is_url_at(s: str, i: int) -> bool:
    return (s[i] in "uU" and _URL_START_RE.match(s, i) is not None
            and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "-_\\")))


def _scan(s: str, i: int, stops: str) -> int:
    """Index of the first char of `stops` at nesting depth 0 (parentheses/brackets) from i, skipping
    comments, strings, escapes and unquoted url(); len(s) when there is none. A '{' that is not a
    stop opens a block that is skipped whole."""
    n, depth = len(s), 0
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "/" and s.startswith("/*", i):
            i = _skip_comment(s, i)
            continue
        if c in "\"'":
            i = _skip_string(s, i)
            continue
        if _is_url_at(s, i):
            j = _skip_url(s, i)
            if j is not None:
                i = j
                continue
        if depth == 0 and c in stops:
            return i
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        elif c == "{":
            i = _block_end(s, i)
            continue
        i += 1
    return n


def _block_end(s: str, i: int) -> int:
    """s[i] == '{': index after the matching '}' (nested blocks, strings, comments, escapes and
    unquoted url() skipped); len(s) for a block left open at the end of the sheet."""
    n, depth = len(s), 0
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "/" and s.startswith("/*", i):
            i = _skip_comment(s, i)
            continue
        if c in "\"'":
            i = _skip_string(s, i)
            continue
        if _is_url_at(s, i):
            j = _skip_url(s, i)
            if j is not None:
                i = j
                continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def strip_comments(s: str) -> str:
    """s without /* comments */ (comment markers inside strings are kept)."""
    out, i, n, k = [], 0, len(s), 0
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
        elif c in "\"'":
            i = _skip_string(s, i)
        elif c == "/" and s.startswith("/*", i):
            out.append(s[k:i])
            i = k = _skip_comment(s, i)
            out.append(" ")
        else:
            i += 1
    out.append(s[k:])
    return "".join(out)


def parse_sheet(css: str) -> list[tuple]:
    """Top-level statements of a style sheet, in order:
    ("at", name (lower case, no '@'), prelude, block content | None, raw text),
    ("rule", prelude, block content, raw text), ("junk", raw text) for a stray '}'.
    Comments and CDO/CDC (`<!--`, `-->`) between statements are dropped."""
    items: list[tuple] = []
    i, n = 0, len(css)
    while i < n:
        c = css[i]
        if c in _WS:
            i += 1
            continue
        if css.startswith("/*", i):
            i = _skip_comment(css, i)
            continue
        if css.startswith("<!--", i):
            i += 4
            continue
        if css.startswith("-->", i):
            i += 3
            continue
        if c == "}":
            items.append(("junk", "}"))
            i += 1
            continue
        if c == "@":
            m = _IDENT_RE.match(css, i + 1)
            name = m.group(0).lower() if m else ""
            j = _scan(css, i, ";{}")
            if j < n and css[j] == "{":
                k = _block_end(css, j)
                inner_end = k - 1 if k <= n and css[k - 1] == "}" else k
                items.append(("at", name, css[i + 1 + len(name):j], css[j + 1:inner_end], css[i:k]))
                i = k
            elif j < n and css[j] == ";":
                items.append(("at", name, css[i + 1 + len(name):j], None, css[i:j + 1]))
                i = j + 1
            else:                       # '}' (stray, left for the next round) or the end of the sheet
                items.append(("at", name, css[i + 1 + len(name):j], None, css[i:j]))
                i = j
            continue
        j = _scan(css, i, "{}")
        if j < n and css[j] == "{":
            k = _block_end(css, j)
            inner_end = k - 1 if css[k - 1] == "}" else k
            items.append(("rule", css[i:j], css[j + 1:inner_end], css[i:k]))
            i = k
        else:
            items.append(("junk", css[i:j]))   # a prelude without a block: invalid, kept as is
            i = j
    return items


def split_selectors(prelude: str) -> list[str]:
    """Selector list split at the top-level commas (not inside (), [], strings or escapes)."""
    out, i, n = [], 0, len(prelude)
    while True:
        j = _scan(prelude, i, ",")
        out.append(prelude[i:j])
        if j >= n:
            return out
        i = j + 1


def selector_ok(sel: str) -> bool:
    """Whether the device model keeps one (comment-free) selector: no sibling combinator (+ ~), no
    attribute selector, no namespace prefix (|), none of DROP_PSEUDO. Pseudo-elements are kept."""
    s = sel.strip(_WS)
    if not s:
        return False
    i, n, depth = 0, len(s), 0
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c in "\"'":
            i = _skip_string(s, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            if c in "[+~|":
                return False
            if c == ":":
                if s.startswith("::", i):
                    i += 2
                    continue        # pseudo-element: its name is read as plain chars
                m = _IDENT_RE.match(s, i + 1)
                if m and m.group(0).lower() in DROP_PSEUDO:
                    return False
        i += 1
    return True


_IMPORT_URL_RE = re.compile(r"""url\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|([^)\s]*))\s*\)"""
                            r"""|"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'""", re.I | re.S)


def _import_ok(prelude: str) -> bool:
    """An @import is kept when it names a relative URL (served, and rewritten, like every sheet) and
    has no condition (a media list, supports() or layer(): the device model has no @media)."""
    p = strip_comments(prelude).strip(_WS)
    m = _IMPORT_URL_RE.match(p)
    if not m:
        return False
    url = next(g for g in m.groups() if g is not None).strip()
    rest = p[m.end():].strip(_WS).lower()
    if not url or re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", url) or url.startswith("//"):
        return False
    return rest in ("", "all")


def device_css(css: str, stats: Counter | None = None) -> str:
    """The device model's reading of one style sheet (see DEVICE_MODEL / KINDLE_UA_CSS):
    * @media, @supports, @namespace, @layer (and the other DROP_AT_RULES) are removed with their
      block; @charset is removed (the result is served as UTF-8); @import is kept only for a
      relative, unconditional URL (its target goes through this function too); other at-rules
      (@font-face, @page, @keyframes, ...) are kept verbatim;
    * every rule keeps only the selectors selector_ok accepts and is removed when none is left;
      declarations are kept verbatim.
    `stats` (optional) counts what was removed: at:<name>, import, selectors, rules, rules_kept."""
    st = stats if stats is not None else Counter()
    out: list[str] = []
    for it in parse_sheet(css):
        kind = it[0]
        if kind == "junk":
            out.append(it[1])
        elif kind == "at":
            _, name, prelude, _block, raw = it
            if name in DROP_AT_RULES or name == "charset":
                st[f"at:{name}"] += 1
            elif name == "import":
                if _import_ok(prelude):
                    out.append(raw)
                else:
                    st["import"] += 1
            else:
                out.append(raw)
        else:
            _, prelude, body, _raw = it
            sels = split_selectors(strip_comments(prelude))
            keep = [x.strip(_WS) for x in sels if selector_ok(x)]
            st["selectors"] += len(sels) - len(keep)
            if keep:
                st["rules_kept"] += 1
                out.append(", ".join(keep) + " {" + body + "}")
            else:
                st["rules"] += 1
    return "\n".join(out) + ("\n" if out else "")


_HEAD_RE = re.compile(rb"<head\b[^>]*>", re.I)
_HTML_RE = re.compile(rb"<html\b[^>]*>", re.I)
_STYLE_RE = re.compile(rb"(<style\b[^>]*(?<!/)>)(.*?)(</style\s*>)", re.I | re.S)
_CDATA_RE = re.compile(rb"^(\s*<!\[CDATA\[)(.*?)(\]\]>\s*)$", re.S)
UA_STYLE = (b'<style xmlns="http://www.w3.org/1999/xhtml" type="text/css">\n' + KINDLE_UA_CSS.encode()
            + b"</style>")

# The device score's INPUT reference: the author's intended look on a page whose side margins the
# device owns. Injected after the author sheets (and !important), so percentages of the descendants
# resolve against the same content box as on the output, whose writer zeroes them on purpose.
INPUT_PAGE_CSS = ("html, body { margin-left: 0 !important; margin-right: 0 !important; "
                  "padding-left: 0 !important; padding-right: 0 !important }")
INPUT_PAGE_STYLE = (b'<style xmlns="http://www.w3.org/1999/xhtml" type="text/css">' + INPUT_PAGE_CSS.encode()
                    + b"</style>")
_BODY_END_RE = re.compile(rb"</body\s*>", re.I)
_HTML_END_RE = re.compile(rb"</html\s*>", re.I)


def input_reference_document(data: bytes, stats: Counter | None = None) -> bytes:
    """An input (X)HTML document with INPUT_PAGE_STYLE inserted before its last </body> (else before
    </html>); author CSS untouched. A UTF-16/32 document (BOM) or one without either end tag is
    returned unchanged (stats["input_page_not_injected"])."""
    st = stats if stats is not None else Counter()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or data[:4] in (b"\x00\x00\xfe\xff",):
        st["input_page_not_injected"] += 1
        return data
    for rx in (_BODY_END_RE, _HTML_END_RE):
        ms = list(rx.finditer(data))
        if ms:
            k = ms[-1].start()
            return data[:k] + INPUT_PAGE_STYLE + data[k:]
    st["input_page_not_injected"] += 1
    return data


def device_document(data: bytes, stats: Counter | None = None) -> bytes:
    """An (X)HTML document as the device model reads it: every inline <style> rewritten with
    device_css (CDATA wrappers kept; a block holding an XML comment `<!--` is left alone, its
    meaning differs between the XML and HTML parsers) and KINDLE_UA_CSS inserted as the first
    style sheet, right after <head ...> (else after <html ...>, inside a new <head>)."""
    st = stats if stats is not None else Counter()

    def style(m):
        inner = m.group(2)
        if b"<!--" in inner:
            st["style_left_alone"] += 1
            return m.group(0)
        cd = _CDATA_RE.match(inner)
        pre, css, post = (cd.group(1), cd.group(2), cd.group(3)) if cd else (b"", inner, b"")
        new = device_css(css.decode("utf-8", "replace"), st).encode("utf-8")
        return m.group(1) + pre + new + post + m.group(3)
    data = _STYLE_RE.sub(style, data)
    m = _HEAD_RE.search(data)
    if m and not data[m.end() - 2:m.end()] == b"/>":
        return data[:m.end()] + UA_STYLE + data[m.end():]
    m = _HTML_RE.search(data)
    if m and not data[m.end() - 2:m.end()] == b"/>":
        return data[:m.end()] + b"<head>" + UA_STYLE + b"</head>" + data[m.end():]
    st["ua_not_injected"] += 1
    return data


# ════════════════════════════════════════════════════════════════════════════
# layout hygiene (static, lxml)
# ════════════════════════════════════════════════════════════════════════════

HYGIENE_KEYS = ("empty_blocks", "trailing_breaks", "whitespace_runs", "nbsp_indents")
# stricter facts, kept visible but out of the `layout-hygiene` category (intentional or ambiguous markup)
HYGIENE_EXTRA_KEYS = ("empty_blocks_styled", "trailing_breaks_double", "nbsp_indents_ambiguous")
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
EMPTY_TAGS = {"p", "div"}
BREAK_BLOCKS = {"p", "div", "li", "blockquote", "dd", "dt"} | _HEADINGS
NBSP_BLOCKS = {"p", "div", "li", "dd", "dt"} | _HEADINGS
# block-level elements (a <br> right after one, or one nested in an nbsp block, is not the simple case)
BLOCKISH = BREAK_BLOCKS | {"ul", "ol", "dl", "table", "tr", "td", "th", "tbody", "thead", "tfoot", "section",
                           "article", "aside", "header", "footer", "nav", "main", "figure", "figcaption",
                           "hgroup", "hr", "pre", "address", "center", "form", "fieldset", "details", "summary"}
PRE_TAGS = {"pre", "textarea", "listing", "plaintext", "xmp"}
# svg/math: not HTML text flow (whitespace there is not laid out as text)
NO_TEXT_TAGS = {"style", "script", "template", "noscript", "svg", "math"}
# elements a trailing <br> may sit in on its way up to its block (anything else stops the walk)
INLINE_TAGS = {"a", "abbr", "b", "bdi", "bdo", "big", "cite", "code", "del", "dfn", "em", "font", "i",
               "ins", "kbd", "label", "mark", "q", "s", "samp", "small", "span", "strike", "strong",
               "sub", "sup", "time", "tt", "u", "var"}
_WS_RUN_RE = re.compile(r"[\n\t\r]|  ")
_PRE_DECL_RE = re.compile(r"white-space\s*:\s*(?:pre|break-spaces)", re.I)
# declarations that make an empty p/div an intentional marker or spacer (page break, rule, box, spacing)
_MARKER_DECL_RE = re.compile(r"(?<![\w-])(?:page-break-(?:before|after|inside)|break-(?:before|after|inside)"
                             r"|border(?:-[a-z-]+)?|background(?:-[a-z-]+)?|height|min-height|width|clear"
                             r"|padding|padding-top|padding-bottom)\s*:", re.I)
_LAST_COMPOUND_RE = re.compile(r"(?:^|[\s>+~])([A-Za-z][\w-]*)?((?:\.[\w-]+)*)\s*$")
_NBSP2 = "\u00a0\u00a0"
# a leading nbsp run followed by a short non-letter mark (ditto, dash, ...) and more nbsp: table columns
_NBSP_COLUMN_RE = re.compile(r"^[ \t\n\r\f\u00a0]*[^\w\s]{1,3} *\u00a0")
MAX_EXAMPLES = 3


def _local(el) -> str:
    t = el.tag
    return t.rsplit("}", 1)[-1].lower() if isinstance(t, str) else ""


def _attr(el, name: str):
    for k, v in el.attrib.items():
        if k == name or k.rsplit("}", 1)[-1] == name:
            return v
    return None


def sheet_selectors(css_texts, decl_re, acc: tuple[set, set] | None = None) -> tuple[set, set]:
    """(tags, classes) named by the last compound of each selector (`pre.x`, `.verse`, `div`) of the
    rules whose declarations match decl_re; @media/@supports/@layer blocks are looked into. An
    approximation: the combinators before the last compound are ignored."""
    tags, classes = acc if acc is not None else (set(), set())

    def walk(css: str, depth: int = 0):
        for it in parse_sheet(css):
            if it[0] == "at" and it[3] is not None and it[1] in ("media", "supports", "layer") and depth < 8:
                walk(it[3], depth + 1)
            elif it[0] == "rule" and decl_re.search(it[2]):
                for sel in split_selectors(strip_comments(it[1])):
                    m = _LAST_COMPOUND_RE.search(re.sub(r"::?[\w-]+(?:\([^)]*\))?", "", sel.strip()))
                    if not m:
                        continue
                    if m.group(2):
                        classes.update(c for c in m.group(2).split(".") if c)
                    elif m.group(1):
                        tags.add(m.group(1).lower())
    for css in css_texts:
        walk(css)
    return tags, classes


def pre_selectors(css_texts, acc: tuple[set, set] | None = None) -> tuple[set, set]:
    """(tags, classes) whose rules set `white-space: pre*` (or break-spaces)."""
    return sheet_selectors(css_texts, _PRE_DECL_RE, acc)


def marker_selectors(css_texts, acc: tuple[set, set] | None = None) -> tuple[set, set]:
    """(tags, classes) whose rules set a page break, border, background, height/min-height, width,
    clear or vertical padding (_MARKER_DECL_RE): an empty p/div with them is a marker/spacer."""
    return sheet_selectors(css_texts, _MARKER_DECL_RE, acc)


def _matches(el, sel: tuple[set, set], decl_re) -> bool:
    if _local(el) in sel[0] or decl_re.search(_attr(el, "style") or ""):
        return True
    cls = _attr(el, "class")
    return bool(cls and sel[1] and any(c in sel[1] for c in cls.split()))


def _nodes(el):
    """Document-order walk of el's content: ('el', element) at each start tag (el itself excluded)
    and ('text', string, owner element) for each text/tail; text of NO_TEXT_TAGS skipped."""
    stack = [(el, False)]
    while stack:
        e, done = stack.pop()
        if done:
            if e is not el and e.tail:
                yield ("text", e.tail, e.getparent())
            continue
        if e is not el:
            yield ("el", e)
        stack.append((e, True))
        if isinstance(e.tag, str) and _local(e) not in NO_TEXT_TAGS:
            if e.text:
                yield ("text", e.text, e)
            stack.extend((c, False) for c in reversed(e))
        # a comment / PI has no text of its own; its tail follows


def _label(el, doc: str) -> str:
    cls = _attr(el, "class")
    txt = " ".join("".join(el.itertext()).split())[:40]
    return f"{doc}: <{_local(el)}{f' class={cls!r}' if cls else ''}> {txt!r}"


def _ex(examples: dict | None, key: str, s: str) -> None:
    if examples is not None:
        lst = examples.setdefault(key, [])
        if len(lst) < MAX_EXAMPLES:
            lst.append(s[:120])


def layout_hygiene_doc(body, pre: tuple[set, set] = (set(), set()), counts: Counter | None = None,
                       examples: dict | None = None, doc: str = "",
                       markers: tuple[set, set] = (set(), set())) -> Counter:
    """Add one document's counts (HYGIENE_KEYS + HYGIENE_EXTRA_KEYS) to `counts`; `body` is its <body>.
    * empty_blocks: p/div with no element child, no text (only ASCII whitespace; U+00A0 is text) and
      no id (`<p><br/></p>` is not empty: the <br> is content); one whose tag/class rule (`markers`,
      see marker_selectors) or style attribute sets a page break, border, background, height,
      width, clear or vertical padding is an intentional marker/spacer: empty_blocks_styled;
    * trailing_breaks: a <br> that is the last non-whitespace node of a p/div/li/h1-h6/blockquote/
      dd/dt (directly, or through inline elements that end there too) whose nearest preceding
      non-whitespace content (looking back through inline wrappers; empty ones such as `<a id>` are
      passed over) is text or a non-<br> inline element (`<p><br/></p>`, a blank line, does not
      count); when it is another <br> after such content (`text<br/><br/>`): trailing_breaks_double;
    * whitespace_runs: text nodes (incl. whitespace-only ones between blocks and tails) holding a
      newline, tab or CR or two ASCII spaces in a row, outside pre/textarea/listing/plaintext/xmp
      and elements whose style attribute, or a rule matching their tag/class (`pre`), sets
      white-space: pre*;
    * nbsp_indents: p/div/li/dd/dt/h1-h6 whose text (leading ASCII whitespace ignored) starts with
      two or more U+00A0 (counted on the innermost such block), with no nested block, no other line
      (after a <br>) also starting with U+00A0 (verse) and no column pattern (the nbsp run followed by
      a short non-letter mark such as a ditto and more U+00A0); those are nbsp_indents_ambiguous."""
    c = counts if counts is not None else Counter()
    for k in HYGIENE_KEYS + HYGIENE_EXTRA_KEYS:
        c.setdefault(k, 0)
    in_pre: dict = {}
    in_pre[body] = _matches(body, pre, _PRE_DECL_RE) or _local(body) in PRE_TAGS

    def pre_of(e) -> bool:
        if e is None:
            return False
        v = in_pre.get(e)
        if v is None:
            chain = []
            x = e
            while x is not None and in_pre.get(x) is None:
                chain.append(x)
                x = x.getparent()
            v = in_pre.get(x, False) if x is not None else False
            for y in reversed(chain):
                v = v or _local(y) in PRE_TAGS or _matches(y, pre, _PRE_DECL_RE)
                in_pre[y] = v
            v = in_pre[e]
        return v

    def add(key: str, label: str) -> None:
        c[key] += 1
        _ex(examples, key, label)

    for kind, *rest in _nodes(body):
        if kind == "text":
            s, owner = rest
            if _WS_RUN_RE.search(s) and not pre_of(owner):
                add("whitespace_runs", f"{doc}: in <{_local(owner)}> {s[:40]!r}")
            continue
        e = rest[0]
        if not isinstance(e.tag, str):
            continue
        tag = _local(e)
        if tag in EMPTY_TAGS and _attr(e, "id") is None:
            kids = [x for x in e if isinstance(x.tag, str)]
            text = (e.text or "") + "".join(x.tail or "" for x in e)
            if not kids and not text.strip(_WS):
                add("empty_blocks_styled" if _matches(e, markers, _MARKER_DECL_RE) else "empty_blocks",
                    _label(e, doc))
        if tag == "br":
            kind_br = _trailing_br(e)
            if kind_br:
                blk = e.getparent()
                while blk is not None and _local(blk) not in BREAK_BLOCKS:
                    blk = blk.getparent()
                add("trailing_breaks" if kind_br == "single" else "trailing_breaks_double",
                    _label(blk if blk is not None else e, doc))
        if tag in NBSP_BLOCKS:
            k = _nbsp_indent(e)
            if k:
                add("nbsp_indents" if k == "clean" else "nbsp_indents_ambiguous", _label(e, doc))
    return c


def _ends_here(node) -> bool:
    """node is the last non-whitespace content of its parent (only comments/PIs and whitespace
    after it)."""
    if (node.tail or "").strip(_WS):
        return False
    for sib in node.itersiblings():
        if isinstance(sib.tag, str) or (sib.tail or "").strip(_WS):
            return False
    return True


def _last_content(el):
    """(kind, node) of the last non-whitespace content inside inline element el: ("text", owner),
    ("br", br), ("inline", element) for any other non-block element; ("block", el) for a block;
    None when el holds nothing visible (an empty anchor)."""
    for ch in reversed(el):
        if (ch.tail or "").strip(_WS):
            return ("text", el)
        if not isinstance(ch.tag, str):
            continue
        t = _local(ch)
        if t == "br":
            return ("br", ch)
        if t in BLOCKISH:
            return ("block", ch)
        if t in INLINE_TAGS:
            got = _last_content(ch)
            if got:
                return got
            continue
        if t not in NO_TEXT_TAGS:
            return ("inline", ch)      # img, svg, object, ...
    if (el.text or "").strip(_WS):
        return ("text", el)
    return None


def _prev_content(node, block):
    """(kind, node) of the nearest non-whitespace content before `node` inside `block` (kinds as
    _last_content), looking back through the inline wrappers node sits in; None at the block start."""
    while node is not block and node is not None:
        prev = node.getprevious()
        while prev is not None:
            if (prev.tail or "").strip(_WS):
                return ("text", prev)
            if isinstance(prev.tag, str):
                t = _local(prev)
                if t == "br":
                    return ("br", prev)
                if t in BLOCKISH:
                    return ("block", prev)
                if t in INLINE_TAGS:
                    got = _last_content(prev)
                    if got:
                        return got
                elif t not in NO_TEXT_TAGS:
                    return ("inline", prev)
            prev = prev.getprevious()
        parent = node.getparent()
        if parent is None:
            return None
        if (parent.text or "").strip(_WS):
            return ("text", parent)
        node = parent
    return None


def _trailing_br(br) -> str | None:
    """"single" (trailing_breaks), "double" (trailing_breaks_double) or None, see layout_hygiene_doc."""
    node = br
    while True:
        parent = node.getparent()
        if parent is None or not _ends_here(node):
            return None
        ptag = _local(parent)
        if ptag in BREAK_BLOCKS:
            block = parent
            break
        if ptag not in INLINE_TAGS:
            return None
        node = parent
    got = _prev_content(br, block)
    if got is None or got[0] == "block":
        return None
    if got[0] != "br":
        return "single"
    while got is not None and got[0] == "br":      # a run of <br>: is there content before it?
        got = _prev_content(got[1], block)
    return "double" if got is not None and got[0] in ("text", "inline") else None


def _nbsp_indent(block) -> str | None:
    """"clean" (nbsp_indents), "ambiguous" (nbsp_indents_ambiguous) or None, see layout_hygiene_doc."""
    lead, owner = "", None
    for kind, *rest in _nodes(block):
        if kind != "text":
            continue
        s = rest[0] if lead else rest[0].lstrip(_WS)
        if not s:
            continue
        if owner is None:
            owner = rest[1]
        lead += s
        if len(lead) >= 24:
            break
    if not lead.startswith(_NBSP2):
        return None
    x = owner
    while x is not None and x is not block:
        if _local(x) in NBSP_BLOCKS or _local(x) == "blockquote":
            return None       # the text belongs to a nested block: counted there
        x = x.getparent()
    if any(_local(d) in BLOCKISH for d in block.iterdescendants()):
        return "ambiguous"
    if _NBSP_COLUMN_RE.match(lead):
        return "ambiguous"
    lines, cur = [], []
    for kind, *rest in _nodes(block):
        if kind == "el":
            if _local(rest[0]) == "br":
                lines.append("".join(cur))
                cur = []
        else:
            cur.append(rest[0])
    lines.append("".join(cur))
    if any(ln.lstrip(_WS).startswith("\u00a0") for ln in lines[1:]):
        return "ambiguous"
    return "clean"
