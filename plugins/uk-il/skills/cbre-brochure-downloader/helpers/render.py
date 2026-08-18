"""Inject the payload into the HTML template.

The template is a complete standalone page; rendering only substitutes placeholders, so
there is no build step and the template can be opened directly while developing.
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "tool.html"


def _safe_json(data: dict) -> str:
    """JSON safe to embed inside a <script> element.

    A literal "</script>" in the data would end the element early, and U+2028/U+2029 are
    line terminators in JavaScript source. Escaping them keeps the page parseable
    whatever a spreadsheet contains.
    """
    text = json.dumps(data, ensure_ascii=False)
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def render(data: dict, client: str, out_path: str | Path, template: str | Path | None = None) -> Path:
    """Write the tool HTML for `data`, returning the path written."""
    tpl_path = Path(template) if template else TEMPLATE
    html = tpl_path.read_text(encoding="utf-8")

    if "__PAYLOAD__" not in html:
        raise ValueError(f"template has no __PAYLOAD__ placeholder: {tpl_path}")

    html = html.replace("__PAYLOAD__", _safe_json(data))
    html = html.replace("__CLIENT__", _escape_html(client))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _escape_html(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
