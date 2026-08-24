"""Render a drafted literature review as a self-contained HTML page.

Same content as the Markdown draft, laid out for reading rather than for a
text editor: measured line length, real heading hierarchy, and a sticky
contents list, so a 6,000-word draft can actually be read and navigated
before it is rewritten in the student's own voice.

The Markdown draft stays the file you edit; this is the one you read. No
external assets and no JS, so it opens straight off disk.
"""

from __future__ import annotations

import html as _html
import re
from typing import List, Tuple

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_UNDERSCORE_ITALIC_RE = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _inline(text: str) -> str:
    """Escape first, then re-introduce only the inline markup we emit — so a
    title containing < or & can never become markup."""
    out = _html.escape(text)
    out = _INLINE_CODE_RE.sub(r"<code>\1</code>", out)
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = _ITALIC_RE.sub(r"<em>\1</em>", out)
    out = _UNDERSCORE_ITALIC_RE.sub(r"<em>\1</em>", out)
    out = _LINK_RE.sub(r'<a href="\2" rel="noopener">\1</a>', out)
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "section"


def markdown_to_html(markdown: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Convert the subset of Markdown the drafter emits — headings,
    paragraphs, blockquotes, bullet lists and inline emphasis — into HTML.

    Deliberately not a general Markdown implementation: this only has to
    handle what literature_review.py writes, and a focused converter is far
    easier to keep correct than a partial general one.
    """
    html_parts: List[str] = []
    toc: List[Tuple[str, str]] = []
    paragraph: List[str] = []
    quote: List[str] = []
    bullets: List[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            html_parts.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_quote() -> None:
        if quote:
            body = "".join(f"<p>{_inline(line)}</p>" for line in quote)
            html_parts.append(f'<blockquote class="lr-callout">{body}</blockquote>')
            quote.clear()

    def flush_bullets() -> None:
        if bullets:
            items = "".join(f"<li>{_inline(b)}</li>" for b in bullets)
            html_parts.append(f"<ul>{items}</ul>")
            bullets.clear()

    def flush_all() -> None:
        flush_paragraph()
        flush_quote()
        flush_bullets()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_all()
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            flush_all()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level == 1:
                html_parts.append(f"<h1>{_inline(title)}</h1>")
            else:
                anchor = _slug(title)
                if level == 2:
                    toc.append((anchor, title))
                html_parts.append(f'<h{level} id="{anchor}">{_inline(title)}</h{level}>')
            continue

        if line.startswith(">"):
            flush_paragraph()
            flush_bullets()
            quote.append(line.lstrip("> ").strip())
            continue

        if line.startswith("- "):
            flush_paragraph()
            flush_quote()
            bullets.append(line[2:].strip())
            continue

        flush_quote()
        flush_bullets()
        paragraph.append(line.strip())

    flush_all()
    return "\n".join(html_parts), toc


_CSS = """
:root {
  color-scheme: light;
  --lr-page: #f9f9f7;
  --lr-surface: #fcfcfb;
  --lr-text: #0b0b0b;
  --lr-secondary: #52514e;
  --lr-muted: #898781;
  --lr-border: rgba(11,11,11,0.10);
  --lr-accent: #2a78d6;
  --lr-callout: rgba(250,178,25,0.12);
  --lr-callout-edge: #fab219;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --lr-page: #0d0d0d;
    --lr-surface: #1a1a19;
    --lr-text: #ffffff;
    --lr-secondary: #c3c2b7;
    --lr-muted: #898781;
    --lr-border: rgba(255,255,255,0.10);
    --lr-accent: #3987e5;
    --lr-callout: rgba(250,178,25,0.14);
    --lr-callout-edge: #fab219;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --lr-page: #0d0d0d;
  --lr-surface: #1a1a19;
  --lr-text: #ffffff;
  --lr-secondary: #c3c2b7;
  --lr-muted: #898781;
  --lr-border: rgba(255,255,255,0.10);
  --lr-accent: #3987e5;
  --lr-callout: rgba(250,178,25,0.14);
  --lr-callout-edge: #fab219;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--lr-page);
  color: var(--lr-text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.65;
}
.lr-wrap { display: grid; grid-template-columns: minmax(0, 1fr); gap: 40px; max-width: 1080px; margin: 0 auto; padding: 40px 24px 96px; }
@media (min-width: 900px) { .lr-wrap { grid-template-columns: 220px minmax(0, 1fr); } }
.lr-toc { display: none; }
@media (min-width: 900px) {
  .lr-toc { display: block; position: sticky; top: 40px; align-self: start; font-size: 0.85rem; max-height: calc(100vh - 80px); overflow-y: auto; }
}
.lr-toc-title { font-weight: 600; color: var(--lr-secondary); margin-bottom: 10px; font-size: 0.78rem; letter-spacing: 0.04em; text-transform: uppercase; }
.lr-toc ol { list-style: none; margin: 0; padding: 0; }
.lr-toc li { margin-bottom: 9px; }
.lr-toc a { color: var(--lr-secondary); text-decoration: none; display: block; border-left: 2px solid var(--lr-border); padding-left: 10px; }
.lr-toc a:hover { color: var(--lr-accent); border-left-color: var(--lr-accent); }
/* ~68 characters per line: past that the eye loses the start of the next
   line, which matters more here than anywhere else on a 6,000-word draft. */
.lr-body { max-width: 34em; }
h1 { font-size: 1.75rem; line-height: 1.25; margin: 0 0 8px; }
h2 { font-size: 1.2rem; line-height: 1.35; margin: 44px 0 12px; padding-top: 20px; border-top: 1px solid var(--lr-border); }
h3 { font-size: 1rem; margin: 28px 0 8px; }
p { margin: 0 0 16px; }
ul { margin: 0 0 16px; padding-left: 22px; }
li { margin-bottom: 8px; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.88em; background: var(--lr-surface); border: 1px solid var(--lr-border); border-radius: 4px; padding: 1px 4px; }
a { color: var(--lr-accent); }
blockquote.lr-callout { margin: 0 0 20px; padding: 14px 18px; background: var(--lr-callout); border-left: 3px solid var(--lr-callout-edge); border-radius: 0 8px 8px 0; color: var(--lr-secondary); font-size: 0.92rem; }
blockquote.lr-callout p:last-child { margin-bottom: 0; }
.lr-meta { list-style: none; margin: 0 0 8px; padding: 0; color: var(--lr-secondary); font-size: 0.9rem; }
.lr-print { color: var(--lr-muted); font-size: 0.8rem; margin-top: 40px; }
@media print {
  .lr-toc { display: none; }
  body { background: #fff; color: #000; }
  .lr-wrap { max-width: none; padding: 0; grid-template-columns: minmax(0, 1fr); }
  h2 { break-after: avoid; }
}
"""


def render_review_html(markdown: str, title: str = "Literature Review — Draft") -> str:
    """A complete, self-contained page. `markdown` is the draft exactly as
    written to the .md file, so the two can never drift apart."""
    body, toc = markdown_to_html(markdown)
    toc_html = ""
    if toc:
        items = "".join(f'<li><a href="#{anchor}">{_html.escape(text)}</a></li>' for anchor, text in toc)
        toc_html = f'<nav class="lr-toc"><div class="lr-toc-title">Contents</div><ol>{items}</ol></nav>'
    else:
        toc_html = "<div></div>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="lr-wrap">
  {toc_html}
  <main class="lr-body">
    {body}
    <p class="lr-print">Generated by thesis-tools. The Markdown version of this draft is the one to edit.</p>
  </main>
</div>
</body>
</html>"""
