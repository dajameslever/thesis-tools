"""Part 2 add-on: a self-contained HTML visualization of what's indexed —
where each paper's metadata actually came from, how much of what your
papers cite is already in your library, and what's worth a second look
before you rely on this library for your thesis.

Pure local computation over the already-built index (no network calls), so
it's cheap to regenerate any time the index changes. No JS charting
library and no external assets — everything (including the bar charts) is
inline SVG generated directly by `render_html()`, so the page opens
correctly straight off disk (`file://...`) as well as from a web server.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
from typing import Dict, List, Optional, Tuple

from ..links import doi_url, google_scholar_search_url, sciencedirect_search_url
from ..recency import DEFAULT_OLD_THRESHOLD_YEARS, age_years, newest_year
from .citation_graph import build_coverage
from .index_store import LibraryEntry, LibraryIndex

# Display labels and a fixed order for the "by source" breakdown — the
# order matches the categorical palette below, so the same source always
# gets the same color across runs.
SOURCE_LABELS = {
    "crossref": "Crossref",
    "semanticscholar": "Semantic Scholar",
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
    "local-heuristic": "Local heuristics (unresolved)",
}
SOURCE_ORDER = ["crossref", "semanticscholar", "openalex", "arxiv", "local-heuristic"]

CONFIDENCE_LABELS = {
    "verified-doi": "Verified via DOI",
    "verified-title-match": "Verified via title match",
    "unresolved": "Unresolved",
}
CONFIDENCE_ORDER = ["verified-doi", "verified-title-match", "unresolved"]

# thesis-tools/dataviz reference palette — categorical slots 1-5 (fixed
# order, never cycled) and the fixed status palette.
_CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
_STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

SOURCE_CONCENTRATION_WARN_THRESHOLD = 0.7  # one source supplying 70%+ of the library
NO_ABSTRACT_WARN_THRESHOLD = 0.3  # 30%+ of papers missing an abstract
OLD_PAPERS_WARN_THRESHOLD = 0.5  # 50%+ of papers past the "old" age threshold
MISSING_REFERENCES_WARN_THRESHOLD = 0.5  # 50%+ of cited references not in the library


def _primary_source(entry: LibraryEntry) -> str:
    sources = entry.paper.sources or []
    return sources[0] if sources else "unknown"


def compute_stats(index: LibraryIndex) -> dict:
    """Pure computation over an already-loaded index — no I/O, easy to unit
    test independently of the HTML it ends up rendered into."""
    entries = index.entries
    total = len(entries)

    by_confidence: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    by_year: Dict[int, int] = {}
    by_file_type: Dict[str, int] = {}
    no_abstract: List[LibraryEntry] = []
    old_papers: List[LibraryEntry] = []
    unresolved_entries: List[LibraryEntry] = []

    for entry in entries:
        by_confidence[entry.confidence] = by_confidence.get(entry.confidence, 0) + 1
        by_source[_primary_source(entry)] = by_source.get(_primary_source(entry), 0) + 1
        by_file_type[entry.file_type] = by_file_type.get(entry.file_type, 0) + 1
        if entry.paper.year:
            by_year[entry.paper.year] = by_year.get(entry.paper.year, 0) + 1
        if not entry.paper.abstract:
            no_abstract.append(entry)
        age = age_years(entry.paper.year)
        if age is not None and age >= DEFAULT_OLD_THRESHOLD_YEARS:
            old_papers.append(entry)
        if entry.confidence == "unresolved":
            unresolved_entries.append(entry)

    duplicates = index.duplicates_by_doi()
    coverage = build_coverage(entries)
    references_fetched = any(e.references for e in entries)

    stats = {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": total,
        "by_confidence": by_confidence,
        "by_source": by_source,
        "by_year": by_year,
        "by_file_type": by_file_type,
        "newest_year": newest_year([e.paper.year for e in entries]),
        "duplicates": duplicates,
        "no_abstract_count": len(no_abstract),
        "no_abstract_titles": [e.paper.title for e in no_abstract],
        "old_papers_count": len(old_papers),
        "unresolved_entries": unresolved_entries,
        "coverage": coverage,
        "references_fetched": references_fetched,
    }
    stats["weaknesses"] = _compute_weaknesses(stats)
    return stats


def _compute_weaknesses(stats: dict) -> List[dict]:
    """Each weakness is {"level", "title", "detail", "items"} — level is one
    of the fixed status roles ("good" used here only for a neutral/
    informational note, never a real problem)."""
    total = stats["total"]
    if total == 0:
        return []

    weaknesses: List[dict] = []
    unresolved = stats["unresolved_entries"]
    duplicates = stats["duplicates"]
    by_source = stats["by_source"]
    coverage = stats["coverage"]

    if unresolved:
        weaknesses.append(
            {
                "level": "warning",
                "title": f"{len(unresolved)} file(s) unresolved — no verified metadata",
                "detail": "Title/author/year came from the file alone (no confident DOI or title match). Double-check before citing.",
                "items": [e.paper.title for e in unresolved],
                "item_links": [_find_it_links_html(e.paper.title) for e in unresolved],
            }
        )

    if duplicates:
        weaknesses.append(
            {
                "level": "serious",
                "title": f"{len(duplicates)} possible duplicate download(s)",
                "detail": "The same DOI was found in more than one file — likely the same paper saved twice.",
                "items": [f"DOI {doi}" for doi in duplicates],
            }
        )

    no_abstract_share = stats["no_abstract_count"] / total
    if no_abstract_share >= NO_ABSTRACT_WARN_THRESHOLD:
        weaknesses.append(
            {
                "level": "warning",
                "title": f"{stats['no_abstract_count']} paper(s) ({no_abstract_share:.0%}) have no abstract on record",
                "detail": "Summaries and relevance scoring for these rely on whatever full text was extracted, if any.",
                "items": stats["no_abstract_titles"],
            }
        )

    verified_by_source = {k: v for k, v in by_source.items() if k != "local-heuristic"}
    if verified_by_source:
        top_source, top_count = max(verified_by_source.items(), key=lambda kv: kv[1])
        share = top_count / total
        if share >= SOURCE_CONCENTRATION_WARN_THRESHOLD:
            label = SOURCE_LABELS.get(top_source, top_source)
            weaknesses.append(
                {
                    "level": "warning",
                    "title": f"{share:.0%} of your library was verified through a single source ({label})",
                    "detail": "One database's coverage and biases may be shaping what counts as 'found' — consider cross-checking against another.",
                    "items": [],
                }
            )

    if not stats["references_fetched"]:
        weaknesses.append(
            {
                "level": "good",
                "title": "Citation coverage not analyzed yet",
                "detail": "Re-run `index-library --fetch-references` to see what your papers cite that isn't in your library yet.",
                "items": [],
            }
        )
    elif coverage["total_references"] > 0:
        share_missing = coverage["missing_references"] / coverage["total_references"]
        if share_missing >= MISSING_REFERENCES_WARN_THRESHOLD:
            top_gaps = coverage["frequently_missing"][:5]
            weaknesses.append(
                {
                    "level": "warning",
                    "title": f"{coverage['missing_references']} of {coverage['total_references']} cited references "
                    f"({share_missing:.0%}) aren't in your library",
                    "detail": "See 'Frequently missing' below for the recurring gaps worth tracking down first.",
                    "items": [g["title"] for g in top_gaps],
                    "item_links": [_find_it_links_html(g["title"], g.get("doi")) for g in top_gaps],
                }
            )

    old_share = stats["old_papers_count"] / total
    if old_share >= OLD_PAPERS_WARN_THRESHOLD:
        weaknesses.append(
            {
                "level": "warning",
                "title": f"{stats['old_papers_count']} paper(s) ({old_share:.0%}) are {DEFAULT_OLD_THRESHOLD_YEARS}+ years old",
                "detail": "Worth checking whether more recent work has superseded these findings.",
                "items": [],
            }
        )

    return weaknesses


def _esc(text: object) -> str:
    return _html.escape(str(text if text is not None else ""))


def _find_it_links_html(title: str, doi: Optional[str] = None) -> str:
    """A DOI link when we actually have one (most likely to land straight on
    the canonical record), plus Google Scholar / ScienceDirect deep-search
    links as a fallback — neither is an API call, just a pre-filled search
    URL, same pattern used for "Needs manual review" in the Markdown report."""
    links = []
    if doi:
        links.append(f'<a href="{_esc(doi_url(doi))}" target="_blank" rel="noopener">DOI</a>')
    links.append(f'<a href="{_esc(google_scholar_search_url(title))}" target="_blank" rel="noopener">Google Scholar</a>')
    links.append(f'<a href="{_esc(sciencedirect_search_url(title))}" target="_blank" rel="noopener">ScienceDirect</a>')
    return " · ".join(links)


def _bar_chart_svg(
    rows: List[Tuple[str, int, str]],
    *,
    width: int = 620,
    bar_height: int = 26,
    gap: int = 10,
    label_width: int = 220,
) -> str:
    """`rows`: [(label, count, hex_color), ...] in the order to render,
    top to bottom. Self-contained inline SVG — a labeled horizontal bar per
    row, a visible count beside it (never color alone)."""
    if not rows:
        return '<p class="viz-muted">No data yet.</p>'

    max_count = max((c for _, c, _ in rows), default=0) or 1
    chart_width = width - label_width - 60
    height = len(rows) * (bar_height + gap) + gap

    parts = [f'<svg viewBox="0 0 {width} {height}" class="viz-chart" role="img" aria-label="bar chart">']
    y = gap
    for label, count, color in rows:
        bar_w = max(int((count / max_count) * chart_width), 2) if count else 0
        text_y = y + bar_height / 2 + 4
        parts.append(f'<text x="0" y="{text_y:.0f}" class="viz-bar-label">{_esc(label)}</text>')
        if bar_w:
            parts.append(f'<rect x="{label_width}" y="{y}" width="{bar_w}" height="{bar_height}" rx="4" fill="{color}"/>')
        parts.append(f'<text x="{label_width + bar_w + 8}" y="{text_y:.0f}" class="viz-bar-count">{count}</text>')
        y += bar_height + gap
    parts.append("</svg>")
    return "\n".join(parts)


def _confidence_rows(stats: dict) -> List[Tuple[str, int, str]]:
    colors = {"verified-doi": _STATUS["good"], "verified-title-match": _CATEGORICAL[0], "unresolved": _STATUS["warning"]}
    return [
        (CONFIDENCE_LABELS[key], stats["by_confidence"].get(key, 0), colors[key])
        for key in CONFIDENCE_ORDER
        if stats["by_confidence"].get(key, 0) > 0
    ]


def _source_rows(stats: dict) -> List[Tuple[str, int, str]]:
    rows = []
    for i, key in enumerate(SOURCE_ORDER):
        count = stats["by_source"].get(key, 0)
        if count > 0:
            rows.append((SOURCE_LABELS[key], count, _CATEGORICAL[i % len(_CATEGORICAL)]))
    # Any source key not in the known order (shouldn't normally happen) still shows up.
    for key, count in stats["by_source"].items():
        if key not in SOURCE_ORDER and count > 0:
            rows.append((key, count, "#898781"))
    return rows


def _year_rows(stats: dict) -> List[Tuple[str, int, str]]:
    by_year = stats["by_year"]
    if not by_year:
        return []
    years = sorted(by_year)
    span = years[-1] - years[0]
    if span <= 20:
        return [(str(y), by_year[y], _CATEGORICAL[0]) for y in years]
    # Wide range — bin into 5-year buckets so the chart stays a sane height.
    bucketed: Dict[int, int] = {}
    for year, count in by_year.items():
        bucket_start = (year // 5) * 5
        bucketed[bucket_start] = bucketed.get(bucket_start, 0) + count
    return [(f"{b}–{b + 4}", bucketed[b], _CATEGORICAL[0]) for b in sorted(bucketed)]


def _stat_tile(label: str, value: object, level: Optional[str] = None) -> str:
    color = _STATUS.get(level, "var(--viz-text-primary)") if level else "var(--viz-text-primary)"
    return (
        '<div class="viz-tile">'
        f'<div class="viz-tile-value" style="color:{color}">{_esc(value)}</div>'
        f'<div class="viz-tile-label">{_esc(label)}</div>'
        "</div>"
    )


_LEVEL_ICON = {"good": "ℹ️", "warning": "⚠️", "serious": "❗", "critical": "\U0001f6d1"}


def _weakness_card(weakness: dict) -> str:
    level = weakness["level"]
    icon = _LEVEL_ICON.get(level, "⚠️")
    color = _STATUS.get(level, _STATUS["warning"])
    items_html = ""
    if weakness["items"]:
        shown = weakness["items"][:8]
        item_links = weakness.get("item_links") or []
        rest = len(weakness["items"]) - len(shown)
        li_parts = []
        for i, item in enumerate(shown):
            link_html = f" — {item_links[i]}" if i < len(item_links) else ""
            li_parts.append(f"<li>{_esc(item)}{link_html}</li>")
        more = f'<li class="viz-muted">…and {rest} more</li>' if rest > 0 else ""
        items_html = f'<ul class="viz-weakness-items">{"".join(li_parts)}{more}</ul>'
    return (
        f'<div class="viz-weakness" style="border-left-color:{color}">'
        f'<div class="viz-weakness-title"><span aria-hidden="true">{icon}</span> {_esc(weakness["title"])}</div>'
        f'<div class="viz-weakness-detail">{_esc(weakness["detail"])}</div>'
        f"{items_html}"
        "</div>"
    )


_CSS = """
.viz-root {
  color-scheme: light;
  --viz-surface: #fcfcfb;
  --viz-page: #f9f9f7;
  --viz-text-primary: #0b0b0b;
  --viz-text-secondary: #52514e;
  --viz-muted: #898781;
  --viz-border: rgba(11,11,11,0.10);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--viz-page);
  color: var(--viz-text-primary);
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .viz-root {
    color-scheme: dark;
    --viz-surface: #1a1a19;
    --viz-page: #0d0d0d;
    --viz-text-primary: #ffffff;
    --viz-text-secondary: #c3c2b7;
    --viz-muted: #898781;
    --viz-border: rgba(255,255,255,0.10);
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --viz-surface: #1a1a19;
  --viz-page: #0d0d0d;
  --viz-text-primary: #ffffff;
  --viz-text-secondary: #c3c2b7;
  --viz-muted: #898781;
  --viz-border: rgba(255,255,255,0.10);
}
.viz-root h1 { font-size: 1.5rem; margin: 0 0 4px; }
.viz-root h2 { font-size: 1.1rem; margin: 40px 0 12px; }
.viz-subtitle { color: var(--viz-text-secondary); margin: 0 0 28px; font-size: 0.9rem; }
.viz-section { background: var(--viz-surface); border: 1px solid var(--viz-border); border-radius: 10px; padding: 20px 24px; }
.viz-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 8px; }
.viz-tile { background: var(--viz-surface); border: 1px solid var(--viz-border); border-radius: 10px; padding: 14px 16px; }
.viz-tile-value { font-size: 1.6rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.viz-tile-label { font-size: 0.8rem; color: var(--viz-text-secondary); margin-top: 2px; }
.viz-chart { width: 100%; height: auto; }
.viz-bar-label { font-size: 12px; fill: var(--viz-text-secondary); dominant-baseline: middle; }
.viz-bar-count { font-size: 12px; fill: var(--viz-text-primary); font-variant-numeric: tabular-nums; dominant-baseline: middle; }
.viz-muted { color: var(--viz-muted); font-size: 0.85rem; }
.viz-weakness { border-left: 4px solid; padding: 10px 16px; margin-bottom: 12px; background: var(--viz-surface); border-radius: 0 8px 8px 0; border-top: 1px solid var(--viz-border); border-right: 1px solid var(--viz-border); border-bottom: 1px solid var(--viz-border); }
.viz-weakness-title { font-weight: 600; margin-bottom: 4px; }
.viz-weakness-detail { color: var(--viz-text-secondary); font-size: 0.9rem; }
.viz-weakness-items { margin: 8px 0 0; padding-left: 20px; font-size: 0.85rem; color: var(--viz-text-secondary); }
.viz-none { color: var(--viz-muted); font-style: italic; }
table.viz-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 8px; }
table.viz-table th, table.viz-table td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--viz-border); }
table.viz-table th { color: var(--viz-text-secondary); font-weight: 600; }
.viz-root a { color: #2a78d6; text-decoration: none; }
.viz-root a:hover { text-decoration: underline; }
.viz-root a:visited { opacity: 0.85; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .viz-root a { color: #3987e5; } }
:root[data-theme="dark"] .viz-root a { color: #3987e5; }
"""


def render_html(stats: dict) -> str:
    """Renders `stats` (from `compute_stats`) into a complete, self-contained
    HTML document — no external requests, opens correctly straight off disk."""
    total = stats["total"]
    coverage = stats["coverage"]

    if total == 0:
        body = '<p class="viz-none">Nothing indexed yet — run `index-library` first.</p>'
    else:
        tiles = "".join(
            [
                _stat_tile("Files indexed", total),
                _stat_tile("Verified", sum(stats["by_confidence"].get(k, 0) for k in ("verified-doi", "verified-title-match")), "good"),
                _stat_tile("Unresolved", stats["by_confidence"].get("unresolved", 0), "warning" if stats["by_confidence"].get("unresolved") else None),
                _stat_tile("Possible duplicates", len(stats["duplicates"]), "serious" if stats["duplicates"] else None),
            ]
        )

        weaknesses_html = (
            "".join(_weakness_card(w) for w in stats["weaknesses"])
            if stats["weaknesses"]
            else '<p class="viz-none">No notable weaknesses detected in what’s currently indexed.</p>'
        )

        coverage_html = ""
        if coverage["total_references"] > 0:
            included_pct = coverage["included_references"] / coverage["total_references"]
            coverage_bars = _bar_chart_svg(
                [
                    ("In your library", coverage["included_references"], _STATUS["good"]),
                    ("Missing", coverage["missing_references"], _STATUS["warning"]),
                ]
            )
            coverage_html = f"""
            <div class="viz-section">
              <p>Across your indexed papers' own reference lists: <strong>{coverage['included_references']} of
              {coverage['total_references']}</strong> cited works ({included_pct:.0%}) are already in your library.</p>
              {coverage_bars}
              {_frequently_missing_table(coverage['frequently_missing'])}
            </div>
            """
        elif not stats["references_fetched"]:
            coverage_html = (
                '<div class="viz-section"><p class="viz-muted">Citation coverage hasn’t been analyzed — '
                "re-run <code>index-library --fetch-references</code> to see it here.</p></div>"
            )
        else:
            coverage_html = '<div class="viz-section"><p class="viz-none">No references recorded to compare.</p></div>'

        body = f"""
        <div class="viz-tiles">{tiles}</div>

        <h2>Where your metadata came from</h2>
        <div class="viz-section">{_bar_chart_svg(_source_rows(stats))}</div>

        <h2>Verification confidence</h2>
        <div class="viz-section">{_bar_chart_svg(_confidence_rows(stats))}</div>

        <h2>Publication years</h2>
        <div class="viz-section">{_bar_chart_svg(_year_rows(stats))}</div>

        <h2>Citation coverage</h2>
        {coverage_html}

        <h2>Weaknesses worth a second look</h2>
        {weaknesses_html}
        """

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Library Visualization</title>
<style>{_CSS}</style>
</head>
<body>
<div class="viz-root">
  <h1>Library Visualization</h1>
  <p class="viz-subtitle">Generated {_esc(stats.get('generated_at', ''))} · {total} file(s) indexed</p>
  {body}
</div>
</body>
</html>"""


def _frequently_missing_table(frequently_missing: List[dict]) -> str:
    if not frequently_missing:
        return ""
    rows = "".join(
        f"<tr><td>{_esc(g['title'])}</td><td>{_esc(g['year'] or '–')}</td>"
        f"<td>{len(g['cited_by'])}</td><td>{_find_it_links_html(g['title'], g.get('doi'))}</td></tr>"
        for g in frequently_missing
    )
    return f"""
    <p><strong>Frequently missing</strong> — cited by 2+ of your papers but not yet in your library. A direct
    DOI link is shown where one is known; otherwise use the search links to track it down:</p>
    <table class="viz-table">
      <thead><tr><th>Title</th><th>Year</th><th>Cited by</th><th>Find it</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def build_visualization_html(index: LibraryIndex) -> str:
    """Convenience entry point used by the CLI: compute + render in one call."""
    return render_html(compute_stats(index))
