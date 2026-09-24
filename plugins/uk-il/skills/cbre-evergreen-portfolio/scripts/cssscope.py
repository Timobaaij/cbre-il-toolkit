# -*- coding: utf-8 -*-
"""Scope a stylesheet under a single ancestor selector.

The storyline and the dashboard share one document, and their stylesheets
collide on 27 selectors including :root, body, html, *, svg, table, td and
both @media print blocks. Rather than hand-prefix hundreds of rules, each
sheet is rewritten at build time so every selector is confined to its view.

Document-level at-rules (@font-face, @keyframes, @page) are hoisted out
unchanged, because they are global by definition and cannot be scoped.
"""
import re

HOISTED = ("@font-face", "@keyframes", "@-webkit-keyframes", "@page",
           "@import", "@charset", "@namespace", "@property", "@counter-style")
NESTED = ("@media", "@supports", "@container", "@layer")


def _blocks(css):
    """Split CSS into (prelude, body) pairs plus bare statements.

    Walks character by character so that braces inside strings, comments and
    url() do not desynchronise the parser.
    """
    out, i, n, start = [], 0, len(css), 0
    depth = 0
    prelude = None
    while i < n:
        c = css[i]
        if c == "/" and i + 1 < n and css[i + 1] == "*":
            j = css.find("*/", i + 2)
            i = (j + 2) if j != -1 else n
            continue
        if c in "\"'":
            q, i = c, i + 1
            while i < n and css[i] != q:
                i += 2 if css[i] == "\\" else 1
            i += 1
            continue
        if c == "{":
            if depth == 0:
                prelude = css[start:i]
                body_start = i + 1
            depth += 1
            i += 1
            continue
        if c == "}":
            depth -= 1
            if depth == 0:
                out.append((prelude, css[body_start:i]))
                start = i + 1
            i += 1
            continue
        if c == ";" and depth == 0:
            stmt = css[start:i].strip()
            if stmt:
                out.append((stmt + ";", None))
            start = i + 1
            i += 1
            continue
        i += 1
    tail = css[start:].strip()
    if tail:
        out.append((tail, None))
    return out


def _split_selectors(sel):
    """Split a selector list on top-level commas only."""
    parts, depth, buf, i, n = [], 0, [], 0, len(sel)
    while i < n:
        c = sel[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c in "\"'":
            q = c
            buf.append(c)
            i += 1
            while i < n and sel[i] != q:
                buf.append(sel[i])
                i += 2 if sel[i] == "\\" else 1
            # fall through to append the closing quote
        if c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


# :root / html / body at the head of a selector all mean "the view root",
# keeping any attribute qualifiers such as body[data-mode="light"].
_ROOTISH = re.compile(r'^(?::root|html|body)((?:\[[^\]]*\]|[.:][\w-]+(?:\([^)]*\))?)*)(.*)$')


def _scope_one(sel, scope):
    sel = sel.strip()
    if not sel:
        return sel
    m = _ROOTISH.match(sel)
    if m:
        qualifiers, rest = m.group(1), m.group(2)
        # a pseudo-class that belongs to the element, e.g. body:focus-within
        return scope + qualifiers + rest
    return scope + " " + sel


def scope_css(css, scope, hoist):
    """Return css with every selector confined to `scope`.

    Document-level at-rules are appended to the `hoist` list instead.
    """
    out = []
    for prelude, body in _blocks(css):
        # A comment before a rule lands in its prelude. Left in, it hides the
        # selector from the :root/body rewrite — "/* TOKENS */ :root" became
        # "#view-dash :root", which matches nothing, and every token was lost.
        p = re.sub(r"/\*.*?\*/", "", prelude or "", flags=re.S).strip()
        if body is None:
            if p:
                hoist.append(p)
            continue
        low = p.lower()
        if low.startswith(HOISTED):
            hoist.append(p + "{" + body + "}")
        elif low.startswith(NESTED):
            inner = scope_css(body, scope, hoist)
            if inner.strip():
                out.append(p + "{" + inner + "}")
        elif low.startswith("@"):
            hoist.append(p + "{" + body + "}")
        else:
            sels = ",".join(_scope_one(s, scope) for s in _split_selectors(p))
            out.append(sels + "{" + body + "}")
    return "\n".join(out)
