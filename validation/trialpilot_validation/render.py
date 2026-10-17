"""Markdown → standalone HTML pages for the validation package (no external assets)."""

from __future__ import annotations

import html

import markdown

from .context import DRAFT_STAMP

CSS = """
:root{--fg:#1f2933;--muted:#52606d;--line:#d9e2ec;--bg:#ffffff;--accent:#0b6e4f;--warn:#b42318;
--chip:#f0f4f8}
@media (prefers-color-scheme: dark){:root{--fg:#e4e7eb;--muted:#9aa5b1;--line:#334e68;--bg:#102a43;
--accent:#3ebd93;--warn:#f97066;--chip:#243b53}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
header.pkg{border-bottom:1px solid var(--line);margin-bottom:24px;padding-bottom:8px;color:var(--muted);
font-size:13px}header.pkg a{color:var(--accent)}
h1{font-size:26px;margin:8px 0 12px}h2{font-size:20px;margin-top:32px;border-bottom:1px solid var(--line);
padding-bottom:4px}h3{font-size:16px;margin-top:22px}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--chip)}code{background:var(--chip);padding:1px 4px;border-radius:4px;font-size:12.5px;
word-break:break-all}
.draft{border:2px solid var(--warn);color:var(--warn);font-weight:700;padding:8px 12px;margin:16px 0;
border-radius:6px;background:transparent}
blockquote{border-left:4px solid var(--line);margin:12px 0;padding:4px 12px;color:var(--muted)}
a{color:var(--accent)}
"""


def page(title: str, body_md: str, *, back: bool = True) -> str:
    body = markdown.markdown(body_md, extensions=["tables", "fenced_code", "sane_lists"])
    stamp = html.escape(DRAFT_STAMP)
    body = body.replace(f"<p>{stamp}", f'<p class="draft">{stamp}')
    nav = '<header class="pkg"><a href="index.html">← Validation package index</a></header>' \
        if back else ""
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body><main>{nav}{body}</main></body></html>\n"
    )
