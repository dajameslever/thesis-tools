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
import json as _json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .. import llm
from ..links import doi_url, google_scholar_search_url, sciencedirect_search_url
from ..recency import DEFAULT_OLD_THRESHOLD_YEARS, age_years, newest_year
from ..relevance import score_relevance
from ..subquestions import SubquestionAnalysis, analyze_subquestions
from .citation_graph import (
    DEFAULT_MIN_GAP_RELEVANCE,
    build_coverage,
    build_exploration_tree,
    build_internal_links,
    split_by_relevance,
)
from .index_store import LibraryEntry, LibraryIndex
from .literature_matrix import build_literature_matrix_workbook
from .themes import documents_from_entries, extract_themes

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

# Stance is a polarity, not a status: a paper challenging your assumption is
# the opposite pole of one supporting it, not a "bad" outcome — so it gets the
# palette's diverging pair (blue <-> red, neutral gray midpoint) rather than
# the reserved good/critical status colors. Referenced as CSS custom
# properties (defined in _CSS, per-mode) so the dark theme gets its own steps
# instead of reusing light-surface hexes. Every place these appear also
# carries a glyph or a written label, so color never carries the meaning
# alone.
STANCE_COLOR_VAR = {
    "supports": "var(--viz-stance-supports)",
    "challenges": "var(--viz-stance-challenges)",
    "mixed": "var(--viz-stance-mixed)",
    "unrelated": "var(--viz-stance-unrelated)",
}
STANCE_GLYPH = {"supports": "+", "challenges": "\u2212", "mixed": "~", "unrelated": ""}
STANCE_LABEL = {
    "supports": "Supports",
    "challenges": "Challenges",
    "mixed": "Mixed evidence",
    "unrelated": "Unrelated",
}

# Rows rendered in the relevance grid. A personal library can run to
# hundreds of papers; past ~40 rows the grid stops being a visualization and
# becomes a spreadsheet — which is exactly what the companion .xlsx already
# is, so the tail is pointed there rather than rendered twice.
MAX_HEATMAP_ROWS = 40

SOURCE_CONCENTRATION_WARN_THRESHOLD = 0.7  # one source supplying 70%+ of the library
NO_ABSTRACT_WARN_THRESHOLD = 0.3  # 30%+ of papers missing an abstract
OLD_PAPERS_WARN_THRESHOLD = 0.5  # 50%+ of papers past the "old" age threshold
MISSING_REFERENCES_WARN_THRESHOLD = 0.5  # 50%+ of cited references not in the library
LOW_RELEVANCE_THRESHOLD = 0.12  # same default as topic-finder's --min-relevance


def _primary_source(entry: LibraryEntry) -> str:
    sources = entry.paper.sources or []
    return sources[0] if sources else "unknown"


def compute_stats(
    index: LibraryIndex,
    sub_questions: Optional[List[str]] = None,
    use_llm: bool = False,
    llm_model: str = llm.DEFAULT_EXTRACTION_MODEL,
    research_question: Optional[str] = None,
    stance_cache_path: Optional[str] = None,
    min_gap_relevance: float = DEFAULT_MIN_GAP_RELEVANCE,
) -> dict:
    """Pure computation over an already-loaded index — no I/O, easy to unit
    test independently of the HTML it ends up rendered into.

    `sub_questions`, when given, anchors the whole page around them: every
    indexed paper is classified as supporting/challenging/mixed/unrelated to
    each one (same analyzer Part 2's Markdown report and Part 3's literature
    review both use), so the visualization shows the same coverage gaps
    those already surface — rather than being purely library-wide stats
    with no connection to the actual research questions. `research_question`,
    when given, additionally flags papers with low relevance to it (same
    scorer used elsewhere) — the "why is this even in my library" check.

    `stance_cache_path`, with use_llm, persists each paper's Claude-
    classified stances to disk and reuses a cached result on a later run
    instead of another Claude call, as long as neither that paper's text
    nor sub_questions have changed since — restoring this module's "cheap
    to regenerate any time" promise even with --llm-summaries on."""
    entries = index.entries
    total = len(entries)
    sub_questions = sub_questions or []

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
    internal_links = build_internal_links(entries)

    # Everything the library cites but does not hold, scored against the
    # questions being asked. `questions` is the research question plus each
    # sub-question kept separate, not concatenated — see
    # citation_graph.question_term_weights for why that matters.
    questions = [q for q in ([research_question] + list(sub_questions or [])) if q]
    exploration = build_exploration_tree(entries, questions, min_gap_relevance)
    relevant_gaps, off_topic_gaps = split_by_relevance(
        coverage["frequently_missing"], questions, min_gap_relevance
    )

    subquestion_coverage: List[dict] = []
    analysis: Optional[SubquestionAnalysis] = None
    if sub_questions:
        analysis = analyze_subquestions(
            sub_questions,
            [e.paper for e in entries],
            use_llm=use_llm,
            model=llm_model,
            cache_path=stance_cache_path,
        )
        for question in sub_questions:
            grouped = analysis.titles_by_stance(question)
            subquestion_coverage.append(
                {
                    "question": question,
                    "supports": grouped["supports"],
                    "challenges": grouped["challenges"],
                    "mixed": grouped["mixed"],
                }
            )

    # Papers that never showed up in ANY sub-question's supports/challenges/
    # mixed lists — i.e. classified "unrelated" to every single one. Only
    # meaningful once sub-questions are actually configured.
    no_subquestion_coverage_titles: List[str] = []
    if sub_questions:
        covered_titles = {
            title
            for c in subquestion_coverage
            for title in (*c["supports"], *c["challenges"], *c["mixed"])
        }
        no_subquestion_coverage_titles = [e.paper.title for e in entries if e.paper.title not in covered_titles]

    low_relevance_titles: List[str] = []
    if research_question:
        for entry in entries:
            if score_relevance(research_question, entry.paper) < LOW_RELEVANCE_THRESHOLD:
                low_relevance_titles.append(entry.paper.title)

    # One row per paper for the relevance grid: its relevance to the overall
    # research question plus its stance on each sub-question. Sorted most-
    # relevant first, so the top of the grid is the part worth reading and
    # the tail is the "why is this here" end — same ordering question the
    # low-relevance weakness flag answers, but shown per paper rather than
    # as a single count.
    relevance_rows: List[dict] = []
    # Captured while the rows are built, before they are sorted — the rows
    # lose their pairing with `entries` the moment they are reordered.
    engaged_keys: Set[str] = set()
    for entry in entries:
        stances = analysis.stances_for(entry.paper) if analysis else {}
        row_stances = [
            (stances[q].stance if q in stances else "unrelated") for q in sub_questions
        ]
        relevance_rows.append(
            {
                "title": entry.paper.title,
                "year": entry.paper.year,
                "doi": entry.doi or entry.paper.doi,
                "relevance": score_relevance(research_question, entry.paper) if research_question else None,
                "stances": row_stances,
                # How many sub-questions this paper actually speaks to —
                # the secondary sort, and what makes a zero row obvious.
                "engaged": sum(1 for st in row_stances if st != "unrelated"),
            }
        )
        if any(st != "unrelated" for st in row_stances):
            engaged_keys.add(entry.paper.key())
    relevance_rows.sort(key=lambda r: (r["relevance"] or 0, r["engaged"]), reverse=True)

    # Themes come from the papers' own words rather than from the questions,
    # so this is the one view that can show a cluster the questions never
    # reach. Each theme carries the papers using it, so the page can open
    # them.
    # First entry wins, so a paper saved to two files renders one row
    # pointing at a stable copy rather than flipping between them run to run.
    by_key: Dict[str, LibraryEntry] = {}
    for entry in entries:
        by_key.setdefault(entry.paper.key(), entry)
    themes = []
    for theme in extract_themes(documents_from_entries(entries, engaged_keys)):
        papers = []
        for key in theme.paper_keys:
            entry = by_key.get(key)
            if entry is None:
                continue
            papers.append(
                {
                    # The paper's identity, so other views (the criticality
                    # chart) can match a paper to its themes without
                    # re-deriving it from a title string.
                    "key": key,
                    "title": entry.paper.title,
                    "year": entry.paper.year,
                    "doi": entry.doi or entry.paper.doi,
                    "file_path": entry.file_path,
                    "engaged": key in engaged_keys,
                }
            )
        papers.sort(key=lambda p: (not p["engaged"], -(p["year"] or 0), p["title"]))
        themes.append(
            {
                "term": theme.term,
                "label": theme.label,
                "papers": papers,
                "engaged_papers": theme.engaged_papers,
            }
        )

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
        "internal_links": internal_links,
        "exploration": exploration,
        "relevant_gaps": relevant_gaps,
        "off_topic_gaps": off_topic_gaps,
        "min_gap_relevance": min_gap_relevance,
        "references_fetched": references_fetched,
        "sub_questions": sub_questions,
        "subquestion_coverage": subquestion_coverage,
        "no_subquestion_coverage_titles": no_subquestion_coverage_titles,
        "research_question": research_question,
        "low_relevance_titles": low_relevance_titles,
        "relevance_rows": relevance_rows,
        "themes": themes,
        # Not rendered directly by render_html() — kept so build_literature_matrix()
        # can reuse the same stance classification build_visualization_html()
        # already computed, instead of re-running (and re-billing) it.
        "_stance_analysis": analysis,
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

    no_coverage = [
        c["question"] for c in stats.get("subquestion_coverage", []) if not (c["supports"] or c["challenges"] or c["mixed"])
    ]
    if no_coverage:
        weaknesses.append(
            {
                "level": "serious",
                "title": f"{len(no_coverage)} of {len(stats['sub_questions'])} sub-question(s) have no supporting paper at all",
                "detail": "A real gap in your library, not just a display quirk — the same thing Part 3's literature review "
                "would flag for a follow-up search.",
                "items": no_coverage,
            }
        )

    not_linked = stats.get("no_subquestion_coverage_titles") or []
    if not_linked:
        weaknesses.append(
            {
                "level": "warning",
                "title": f"{len(not_linked)} paper(s) don't relate to any of your sub-questions",
                "detail": "Classified \"unrelated\" to every sub-question checked — worth a look to confirm they still "
                "belong in this library, or that a sub-question should be added to cover what they're actually about.",
                "items": not_linked,
            }
        )

    low_relevance = stats.get("low_relevance_titles") or []
    if low_relevance:
        weaknesses.append(
            {
                "level": "warning",
                "title": f"{len(low_relevance)} paper(s) have low relevance to your research question",
                "detail": f'Title/text overlap with "{stats.get("research_question")}" scored below '
                f"{LOW_RELEVANCE_THRESHOLD:.0%} — worth confirming these still belong here.",
                "items": low_relevance,
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
    """`rows`: [(label, count, color), ...] in the order to render, top to
    bottom. Self-contained inline SVG — a labeled horizontal bar per row, a
    visible count beside it (never color alone)."""
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
        parts.append(
            f'<text x="0" y="{text_y:.0f}" class="viz-bar-label">{_esc(_fit_label(label, label_width))}</text>'
        )
        if bar_w:
            parts.append(_bar_path(label_width, y, bar_w, bar_height, color))
        parts.append(f'<text x="{label_width + bar_w + 8}" y="{text_y:.0f}" class="viz-bar-count">{count}</text>')
        y += bar_height + gap
    parts.append("</svg>")
    return "\n".join(parts)


# .viz-bar-label renders at 12px; ~6.6px per character is a safe upper bound
# for the system sans at that size, so a label budgeted this way never runs
# under the bar it belongs to.
_LABEL_PX_PER_CHAR = 6.6


def _fit_label(label: str, label_width: int) -> str:
    """Truncate a bar's label to what its column can actually hold. The
    column is fixed and the bars start right after it, so an over-long
    label would render *underneath* the first bar rather than being
    clipped — worse than a visible ellipsis."""
    budget = max(int((label_width - 10) / _LABEL_PX_PER_CHAR), 8)
    return label if len(label) <= budget else label[: budget - 1] + "\u2026"


def _bar_path(x: float, y: float, width: float, height: float, color: str) -> str:
    """A bar rounded at its data end only, square against the baseline —
    rounding all four corners detaches the bar from the axis it is measured
    from."""
    r = min(4.0, width / 2, height / 2)
    d = (
        f"M {x:.1f} {y:.1f} H {x + width - r:.1f} A {r:.1f} {r:.1f} 0 0 1 {x + width:.1f} {y + r:.1f} "
        f"V {y + height - r:.1f} A {r:.1f} {r:.1f} 0 0 1 {x + width - r:.1f} {y + height:.1f} "
        f"H {x:.1f} Z"
    )
    return f'<path d="{d}" fill="{color}"/>' 


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
  --viz-stance-supports: #2a78d6;
  --viz-stance-challenges: #e34948;
  --viz-stance-mixed: #c3c2b7;
  --viz-stance-unrelated: transparent;
  --viz-accent: #2a78d6;
  --viz-accent-soft: rgba(42,120,214,0.16);
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
    --viz-stance-supports: #3987e5;
    --viz-stance-challenges: #e66767;
    --viz-stance-mixed: #4a4a46;
    --viz-stance-unrelated: transparent;
    --viz-accent: #3987e5;
    --viz-accent-soft: rgba(57,135,229,0.22);
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
  --viz-stance-supports: #3987e5;
  --viz-stance-challenges: #e66767;
  --viz-stance-mixed: #4a4a46;
  --viz-stance-unrelated: transparent;
  --viz-accent: #3987e5;
  --viz-accent-soft: rgba(57,135,229,0.22);
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
.viz-subq-card { margin-bottom: 16px; }
.viz-subq-question { font-weight: 600; margin: 0 0 10px; }
.viz-subq-stance-label { font-weight: 600; font-size: 0.85rem; margin: 10px 0 2px; }
.viz-legend { display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.8rem; color: var(--viz-text-secondary); margin: 0 0 14px; align-items: center; }
.viz-swatch { display: inline-block; width: 11px; height: 11px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; border: 1px solid var(--viz-border); }
.viz-theme-group { font-size: 0.8rem; font-weight: 600; color: var(--viz-text-secondary); margin: 18px 0 8px; }
.viz-theme-group:first-of-type { margin-top: 4px; }
.viz-theme-cloud { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.viz-theme-chip {
  /* A chip, not coloured text: the label stays on ink tokens at full
     contrast while the fill carries state, and the padding gives every
     chip — including the smallest — a hit target past 24px. */
  display: inline-flex; align-items: baseline; gap: 7px;
  font-family: inherit; font-weight: 500; line-height: 1.25;
  color: var(--viz-text-primary); background: var(--viz-accent-soft);
  border: 1px solid transparent; border-radius: 999px;
  padding: 7px 13px; min-height: 26px; cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}
.viz-theme-chip:hover { border-color: var(--viz-accent); }
.viz-theme-chip:focus-visible { outline: 2px solid var(--viz-accent); outline-offset: 2px; }
.viz-theme-chip[aria-pressed="true"] { border-color: var(--viz-accent); background: var(--viz-accent-soft); box-shadow: inset 0 0 0 1px var(--viz-accent); }
.viz-theme-count { font-size: 0.7rem; font-weight: 600; color: var(--viz-text-secondary); font-variant-numeric: tabular-nums; }
.viz-theme-panel { margin-top: 18px; border-top: 1px solid var(--viz-border); padding-top: 14px; }
.viz-theme-panel-title { font-weight: 600; margin: 0 0 10px; }
.viz-theme-papers { margin: 0; padding-left: 18px; }
.viz-theme-papers li { margin-bottom: 10px; }
.viz-theme-links { font-size: 0.82rem; }
.viz-theme-empty { margin: 18px 0 0; border-top: 1px solid var(--viz-border); padding-top: 14px; }
/* Without scripting nothing could ever be revealed, so show every theme's
   papers instead of a cloud that does nothing when clicked. */
.viz-no-js .viz-theme-panel { display: block; }
.viz-no-js .viz-theme-empty { display: none; }
.viz-lede { margin: 0 0 14px; color: var(--viz-text-secondary); font-size: 0.9rem; }
.viz-lede strong { color: var(--viz-text-primary); font-variant-numeric: tabular-nums; }
.viz-scroll { overflow-x: auto; }
.viz-arc { width: 100%; height: auto; display: block; }
.viz-arc-link { fill: none; stroke: var(--viz-text-secondary); stroke-opacity: 0.45; stroke-width: 1.5; transition: stroke-opacity 0.12s, stroke 0.12s; }
.viz-arc-node { transition: opacity 0.12s; }
.viz-arc-hit { fill: transparent; }
.viz-arc-node:focus { outline: none; }
.viz-arc-node:focus-visible .viz-arc-dot { stroke: var(--viz-text-primary); stroke-width: 2.5; }
.viz-arc-dot { stroke: var(--viz-surface); stroke-width: 2; }
.viz-arc-axis { stroke: var(--viz-border); stroke-width: 1; }
.viz-arc-tick { font-size: 9px; fill: var(--viz-muted); text-anchor: middle; font-variant-numeric: tabular-nums; }
.viz-arc-caption { font-size: 10px; fill: var(--viz-muted); }
.viz-arc.viz-arc-active .viz-arc-link { stroke-opacity: 0.1; }
.viz-arc.viz-arc-active .viz-arc-link.viz-on { stroke-opacity: 1; stroke: var(--viz-accent); stroke-width: 2; }
.viz-arc.viz-arc-active .viz-arc-node { opacity: 0.3; }
.viz-arc.viz-arc-active .viz-arc-node.viz-on { opacity: 1; }
.viz-grid { border-collapse: separate; border-spacing: 2px; font-size: 0.82rem; }
.viz-grid th { font-weight: 600; color: var(--viz-text-secondary); text-align: center; padding: 4px 6px; font-size: 0.78rem; }
.viz-grid th.viz-grid-rowhead, .viz-grid td.viz-grid-rowhead { text-align: left; min-width: 220px; max-width: 320px; }
.viz-grid td { padding: 4px 6px; }
.viz-grid-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.viz-grid th.viz-grid-year-col, .viz-grid td.viz-grid-year-col { color: var(--viz-muted); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.viz-cell { width: 30px; height: 22px; border-radius: 4px; text-align: center; font-weight: 700; color: #ffffff; border: 1px solid transparent; }
.viz-cell-unrelated { border-color: var(--viz-border); color: var(--viz-muted); font-weight: 400; }
.viz-relbar-track { position: relative; width: 76px; height: 16px; background: var(--viz-accent-soft); border-radius: 3px; }
.viz-relbar-fill { position: absolute; inset: 0 auto 0 0; background: var(--viz-accent); border-radius: 3px; }
.viz-relbar-value { font-size: 0.75rem; color: var(--viz-text-secondary); font-variant-numeric: tabular-nums; margin-left: 6px; }
.viz-relbar { display: flex; align-items: center; }
.viz-qkey { margin: 14px 0 0; padding-left: 20px; font-size: 0.85rem; color: var(--viz-text-secondary); }
.viz-tree { margin: 4px 0 0; }
.viz-branch { border-left: 2px solid var(--viz-border); padding: 0 0 0 12px; margin: 0 0 4px; }
.viz-branch > summary { cursor: pointer; padding: 5px 4px; list-style: none; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; border-radius: 4px; }
.viz-branch > summary::-webkit-details-marker { display: none; }
/* Drawn with borders rather than a glyph: a font that lacks the triangle
   character renders tofu, and tofu inside a flex row also breaks the
   alignment of everything beside it. */
.viz-branch > summary::before { content: ""; flex: 0 0 auto; width: 0; height: 0; margin-right: 2px;
  border-left: 5px solid var(--viz-muted); border-top: 4px solid transparent; border-bottom: 4px solid transparent;
  transition: transform 0.12s; }
.viz-branch[open] > summary::before { transform: rotate(90deg); }
.viz-branch > summary:hover { background: var(--viz-accent-soft); border-radius: 4px; }
.viz-branch-body { padding: 2px 0 10px 12px; }
.viz-branch-label { font-size: 0.8rem; font-weight: 600; color: var(--viz-text-secondary); margin: 8px 0 4px; }
.viz-explore-title { color: var(--viz-text-primary); }
.viz-explore-list { margin: 0; padding-left: 18px; font-size: 0.85rem; color: var(--viz-text-secondary); }
.viz-explore-list li { margin-bottom: 4px; }
.viz-explore-held .viz-explore-title { color: var(--viz-text-secondary); }
.viz-explore-links { font-size: 0.78rem; white-space: nowrap; }
.viz-badge { display: inline-block; font-size: 0.72rem; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--viz-border); color: var(--viz-text-secondary); white-space: nowrap; }
.viz-badge-accent { background: var(--viz-accent-soft); border-color: transparent; color: var(--viz-text-primary); }
.viz-badge-quiet { color: var(--viz-muted); }
.viz-details { margin-top: 14px; font-size: 0.85rem; }
.viz-details summary { cursor: pointer; color: var(--viz-text-secondary); }
.viz-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
"""


def _render_subquestion_coverage_section(stats: dict) -> str:
    """The page's organizing anchor, when sub-questions are known: for each
    one, how many indexed papers support/challenge/give mixed evidence on
    it — the same supports/challenges/mixed classification Part 2's
    Markdown report and Part 3's literature review both already compute,
    so this view and those agree rather than being yet another independent
    library-wide stat with no connection to the actual research questions."""
    if not stats.get("sub_questions"):
        return (
            '<div class="viz-section"><p class="viz-muted">No sub-questions configured for this run — pass '
            "<code>--sub-questions</code>, or set them once via <code>configure</code>/<code>topic-finder</code> "
            "and re-run <code>visualize-library</code>, to anchor this page around them.</p></div>"
        )

    cards = []
    for i, c in enumerate(stats["subquestion_coverage"], start=1):
        # Same diverging palette the relevance grid uses, so one stance
        # never means two different colours on one page.
        counts = [
            ("Supports", len(c["supports"]), STANCE_COLOR_VAR["supports"]),
            ("Challenges", len(c["challenges"]), STANCE_COLOR_VAR["challenges"]),
            ("Mixed", len(c["mixed"]), STANCE_COLOR_VAR["mixed"]),
        ]
        if not any(n for _, n, _ in counts):
            body = (
                '<p class="viz-none">No paper in your library speaks directly to this sub-question — '
                "a gap worth targeting with a follow-up search.</p>"
            )
        else:
            body = _bar_chart_svg([row for row in counts if row[1] > 0], width=560, label_width=140)
            for label, key in (("Supports", "supports"), ("Challenges", "challenges"), ("Mixed evidence", "mixed")):
                titles = c[key]
                if not titles:
                    continue
                shown = titles[:6]
                items = "".join(f"<li>{_esc(t)}</li>" for t in shown)
                rest = len(titles) - len(shown)
                more = f'<li class="viz-muted">…and {rest} more</li>' if rest > 0 else ""
                body += f'<p class="viz-subq-stance-label">{label}</p><ul class="viz-weakness-items">{items}{more}</ul>'
        cards.append(
            f'<div class="viz-section viz-subq-card">'
            f'<p class="viz-subq-question">{i}. {_esc(c["question"])}</p>'
            f"{body}"
            "</div>"
        )
    return "".join(cards)


def render_html(stats: dict, matrix_filename: Optional[str] = None) -> str:
    """Renders `stats` (from `compute_stats`) into a complete, self-contained
    HTML document — no external requests, opens correctly straight off disk.

    `matrix_filename`, when given, adds a download link for the companion
    Excel synthesis matrix (see literature_matrix.py) — a relative path so
    it resolves whether the two files sit in the same folder or the matrix
    was written somewhere nearby."""
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

        <h2>Themes across your library</h2>
        {_render_themes_section(stats)}

        <h2>Coverage by sub-question</h2>
        {_render_subquestion_coverage_section(stats)}

        <h2>Relevance to your questions</h2>
        {_render_relevance_grid_section(stats)}

        <h2>How your papers connect</h2>
        {_render_connections_section(stats)}

        <h2>Where to explore next</h2>
        {_render_exploration_section(stats)}

        <h2>Papers worth adding next</h2>
        {_render_papers_to_consider_section(stats)}

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

    matrix_link_html = ""
    if total > 0 and matrix_filename:
        matrix_link_html = (
            f'<p class="viz-subtitle"><a href="{_esc(matrix_filename)}" download>'
            "⬇ Download as Excel (.xlsx)</a> — one row per paper, in academic "
            "literature-review synthesis-matrix format</p>"
        )

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
  {matrix_link_html}
  {body}
</div>
</body>
</html>"""


def _truncate(text: str, max_len: int) -> str:
    text = text or "Untitled"
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


# --- Connected articles (arc diagram) -------------------------------------
#
# Deliberately NOT a force-directed graph. A force layout gives a personal
# library of a few dozen papers an unreadable hairball whose shape changes
# every run and whose labels collide; nothing about the picture answers
# "which of my papers talk to each other?". An arc diagram fixes the papers
# on one axis in a meaningful order (oldest first, so citations arc
# right-to-left), which makes the layout deterministic, label collisions
# impossible, and the reading trivial: an arc is one paper citing another.

MAX_ARC_HEIGHT = 130
ARC_VIEWBOX_WIDTH = 700
ARC_MARGIN = 18


def _arc_diagram_svg(internal: dict) -> str:
    papers = internal["papers"]
    links = internal["links"]
    count = len(papers)
    if count == 0:
        return '<p class="viz-none">Nothing indexed yet.</p>'

    span = ARC_VIEWBOX_WIDTH - 2 * ARC_MARGIN
    step = span / (count - 1) if count > 1 else 0

    def x_of(i: int) -> float:
        return ARC_MARGIN + span / 2 if count == 1 else ARC_MARGIN + i * step

    radii = [min(abs(x_of(l["target"]) - x_of(l["source"])) / 2, MAX_ARC_HEIGHT) for l in links]
    baseline = 10 + (max(radii) if radii else 0) + 6
    height = baseline + 34

    parts = [
        f'<svg id="viz-arc" class="viz-arc" viewBox="0 0 {ARC_VIEWBOX_WIDTH} {height:.0f}" '
        f'role="img" aria-label="Arc diagram: which indexed papers cite which others, oldest on the left">'
    ]
    parts.append(f'<line class="viz-arc-axis" x1="{ARC_MARGIN}" y1="{baseline:.1f}" x2="{ARC_VIEWBOX_WIDTH - ARC_MARGIN}" y2="{baseline:.1f}"/>')

    for i, link in enumerate(links):
        x1, x2 = x_of(link["source"]), x_of(link["target"])
        left, right = (x1, x2) if x1 <= x2 else (x2, x1)
        rx = (right - left) / 2
        ry = min(rx, MAX_ARC_HEIGHT)
        # sweep-flag 1 with left->right bulges the arc upward (SVG y grows down).
        parts.append(
            f'<path class="viz-arc-link" data-a="{link["source"]}" data-b="{link["target"]}" '
            f'd="M {left:.1f} {baseline:.1f} A {rx:.1f} {ry:.1f} 0 0 1 {right:.1f} {baseline:.1f}"/>'
        )

    # Only number the ticks when they will not collide; past that the
    # tooltip and the table below carry identity instead of a smear of
    # overlapping digits.
    label_every = 1 if step >= 15 or count == 1 else max(1, round(count / 20))

    for paper in papers:
        i = paper["index"]
        x = x_of(i)
        linked = paper["cites"] or paper["cited_by"]
        fill = "var(--viz-accent)" if linked else "var(--viz-muted)"
        year = f' ({paper["year"]})' if paper["year"] else ""
        tip = (
            f'{i + 1}. {paper["title"]}{year} — '
            + (f'cites {paper["cites"]}, cited by {paper["cited_by"]} in this library' if linked
               else "no citation link to anything else in this library")
        )
        parts.append(f'<g class="viz-arc-node" data-i="{i}"><title>{_esc(tip)}</title>')
        # An invisible hit column so the target is a comfortable ~24px+
        # rather than the 9px dot itself, and so the tick number under the
        # dot is part of the same target instead of a dead gap.
        hit_w = max(24.0, min(step or 24.0, 34.0))
        parts.append(
            f'<rect class="viz-arc-hit" x="{x - hit_w / 2:.1f}" y="{baseline - 14:.1f}" '
            f'width="{hit_w:.1f}" height="34"/>'
        )
        parts.append(f'<circle class="viz-arc-dot" cx="{x:.1f}" cy="{baseline:.1f}" r="4.5" fill="{fill}"/>')
        if i % label_every == 0:
            parts.append(f'<text class="viz-arc-tick" x="{x:.1f}" y="{baseline + 15:.1f}">{i + 1}</text>')
        parts.append("</g>")

    parts.append(
        f'<text class="viz-arc-caption" x="{ARC_MARGIN}" y="{height - 2:.0f}">oldest</text>'
        f'<text class="viz-arc-caption" x="{ARC_VIEWBOX_WIDTH - ARC_MARGIN}" y="{height - 2:.0f}" '
        f'text-anchor="end">newest</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


# Hover highlight only — the diagram is fully readable without it (native
# <title> tooltips on every node, plus the link list below), so this
# enhances and never gates.
_THEMES_JS = """
(function() {
  const root = document.querySelector('.viz-theme-cloud');
  if (!root) { return; }
  const section = root.closest('.viz-section');
  const chips = Array.prototype.slice.call(section.querySelectorAll('.viz-theme-chip'));
  const panels = Array.prototype.slice.call(section.querySelectorAll('.viz-theme-panel'));
  const empty = section.querySelector('.viz-theme-empty');
  // Scripting is present, so the no-JS fallback (every panel expanded) is
  // no longer what we want.
  section.classList.remove('viz-no-js');

  function select(index) {
    chips.forEach(function(chip) {
      chip.setAttribute('aria-pressed', String(chip.dataset.theme === index));
    });
    panels.forEach(function(panel) {
      panel.hidden = panel.id !== 'viz-theme-panel-' + index;
    });
    if (empty) { empty.hidden = index !== null; }
  }

  function clear() {
    chips.forEach(function(chip) { chip.setAttribute('aria-pressed', 'false'); });
    panels.forEach(function(panel) { panel.hidden = true; });
    if (empty) { empty.hidden = false; }
  }

  chips.forEach(function(chip) {
    chip.addEventListener('click', function() {
      // Clicking the selected theme again clears it, so the cloud is never
      // a trap the reader has to reload out of.
      if (chip.getAttribute('aria-pressed') === 'true') { clear(); }
      else { select(chip.dataset.theme); }
    });
  });

  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') { clear(); }
  });
})();
"""


_ARC_JS = """
(function() {
  const svg = document.getElementById('viz-arc');
  if (!svg) { return; }
  const links = Array.prototype.slice.call(svg.querySelectorAll('.viz-arc-link'));
  const nodes = Array.prototype.slice.call(svg.querySelectorAll('.viz-arc-node'));
  function clear() {
    svg.classList.remove('viz-arc-active');
    links.forEach(function(l) { l.classList.remove('viz-on'); });
    nodes.forEach(function(n) { n.classList.remove('viz-on'); });
  }
  nodes.forEach(function(node) {
    function on() {
      clear();
      const i = node.getAttribute('data-i');
      const partners = {};
      partners[i] = true;
      links.forEach(function(link) {
        const a = link.getAttribute('data-a'), b = link.getAttribute('data-b');
        if (a === i || b === i) {
          link.classList.add('viz-on');
          partners[a] = true;
          partners[b] = true;
        }
      });
      nodes.forEach(function(n) {
        if (partners[n.getAttribute('data-i')]) { n.classList.add('viz-on'); }
      });
      svg.classList.add('viz-arc-active');
    }
    node.addEventListener('mouseenter', on);
    node.addEventListener('focus', on);
    node.setAttribute('tabindex', '0');
  });
  svg.addEventListener('mouseleave', clear);
})();
"""


def _render_connections_section(stats: dict) -> str:
    internal = stats["internal_links"]
    papers = internal["papers"]
    links = internal["links"]

    if not stats["references_fetched"]:
        return (
            '<div class="viz-section"><p class="viz-muted">No reference lists fetched yet, so there is nothing '
            "to connect — re-run <code>index-library --fetch-references</code> to build this view.</p></div>"
        )
    if not links:
        return (
            f'<div class="viz-section"><p class="viz-none">None of your {len(papers)} indexed paper(s) cites '
            "another one in this library. That is common early on, and it means each paper stands alone rather "
            "than forming a conversation — the papers below are where that conversation is happening "
            "instead.</p></div>"
        )

    by_index = {p["index"]: p for p in papers}
    link_rows = "".join(
        "<tr><td>{src}</td><td>{tgt}</td></tr>".format(
            src=_esc("{}. {}".format(l["source"] + 1, _truncate(by_index[l["source"]]["title"], 60))),
            tgt=_esc("{}. {}".format(l["target"] + 1, _truncate(by_index[l["target"]]["title"], 60))),
        )
        for l in links
    )
    key_rows = "".join(
        "<tr><td>{n}</td><td>{title}</td><td>{year}</td><td>{cites}</td><td>{cited_by}</td></tr>".format(
            n=paper["index"] + 1,
            title=_esc(paper["title"]),
            year=_esc(paper["year"] or "—"),
            cites=paper["cites"],
            cited_by=paper["cited_by"],
        )
        for paper in papers
    )

    return f"""
    <div class="viz-section">
      <p class="viz-lede">Each dot is one indexed paper, oldest on the left. An arc joins two papers when one
      cites the other — so an arc is a conversation happening inside your own library.
      <strong>{internal['connected_count']}</strong> of <strong>{len(papers)}</strong> paper(s) are connected
      to at least one other, across <strong>{len(links)}</strong> citation link(s);
      <strong>{internal['isolated_count']}</strong> stand alone.</p>
      <div class="viz-legend">
        <span><span class="viz-swatch" style="background:var(--viz-accent)"></span> Connected to another paper here</span>
        <span><span class="viz-swatch" style="background:var(--viz-muted)"></span> No link to anything here</span>
      </div>
      <div class="viz-scroll">{_arc_diagram_svg(internal)}</div>
      <p class="viz-muted">Hover or tab to a dot to isolate its links.</p>
      <details class="viz-details">
        <summary>Which paper is which — all {len(papers)}, numbered as on the axis</summary>
        <table class="viz-table">
          <thead><tr><th>#</th><th>Paper</th><th>Year</th><th>Cites</th><th>Cited by</th></tr></thead>
          <tbody>{key_rows}</tbody>
        </table>
      </details>
      <details class="viz-details">
        <summary>All {len(links)} link(s), as a table</summary>
        <table class="viz-table">
          <thead><tr><th>This paper…</th><th>…cites this one</th></tr></thead>
          <tbody>{link_rows}</tbody>
        </table>
      </details>
    </div>
    <script>{_ARC_JS}</script>
    """


# --- Papers worth adding next ---------------------------------------------


def _render_papers_to_consider_section(stats: dict) -> str:
    """The "what should I read next" answer: references that several of your
    own papers cite but that you do not have. A ranked bar is the right form
    for it — the question is purely one of magnitude ("how many of mine cite
    this?"), which a network node's size answers far less legibly."""
    gaps = stats["relevant_gaps"]
    off_topic = stats["off_topic_gaps"]

    if not stats["references_fetched"]:
        return (
            '<div class="viz-section"><p class="viz-muted">Not analyzed yet — re-run '
            "<code>index-library --fetch-references</code> to see which works your papers keep citing "
            "that you do not have.</p></div>"
        )
    if not gaps and not off_topic:
        return (
            '<div class="viz-section"><p class="viz-none">No work is cited by two or more of your papers '
            "without already being in your library — nothing obvious to add next.</p></div>"
        )
    if not gaps:
        return (
            f'<div class="viz-section"><p class="viz-none">All {len(off_topic)} recurring gap(s) scored '
            "off-topic against your questions — nothing here looks worth adding on this topic.</p>"
            f"{_off_topic_details(off_topic)}</div>"
        )

    # Relevance is the filter here, not the ranking: the question this
    # section answers is "which of these is most foundational", which is the
    # citation count. A bar chart whose bars are not in length order is
    # unreadable regardless of what it was sorted by.
    gaps = sorted(gaps, key=lambda g: len(g["cited_by"]), reverse=True)
    rows = []
    for gap in gaps:
        year = " ({})".format(gap["year"]) if gap.get("year") else ""
        rows.append(((gap["title"] or "Untitled") + year, len(gap["cited_by"]), "var(--viz-accent)"))
    chart = _bar_chart_svg(rows, width=700, label_width=330, bar_height=22, gap=8)
    cited_total = sum(len(g["cited_by"]) for g in gaps)
    filtered = (
        f" A further <strong>{len(off_topic)}</strong> scored off-topic against your questions and "
        "are held back rather than padding the list."
        if off_topic
        else ""
    )

    return f"""
    <div class="viz-section">
      <p class="viz-lede">Works your own papers cite that are <em>not</em> in your library yet, ranked by how
      many of your papers cite each one — a work several of your sources lean on is usually foundational.
      <strong>{len(gaps)}</strong> such work(s) are on-topic for your questions, accounting for
      <strong>{cited_total}</strong> citation(s) from across your library.{filtered}</p>
      {chart}
      {_frequently_missing_table(gaps)}
      {_off_topic_details(off_topic)}
    </div>
    """


def _off_topic_details(off_topic: List[dict]) -> str:
    """Filtered-out suggestions stay one click away rather than vanishing —
    a title-only keyword match will occasionally misjudge something genuinely
    relevant, and a silent drop gives no way to notice."""
    if not off_topic:
        return ""
    items = "".join(
        f'<li><span class="viz-explore-title">{_esc(g["title"])}</span>'
        + (f' <span class="viz-grid-year">{_esc(g["year"])}</span>' if g.get("year") else "")
        + f' <span class="viz-badge viz-badge-quiet">relevance {g["relevance"]:.2f}</span> '
        + f'<span class="viz-explore-links">{_find_it_links_html(g["title"], g.get("doi"))}</span></li>'
        for g in off_topic
    )
    return (
        f'<details class="viz-details"><summary>Show the {len(off_topic)} held back as off-topic</summary>'
        f'<ul class="viz-explore-list">{items}</ul></details>'
    )


def _work_links_html(work: dict) -> str:
    return _find_it_links_html(work.get("title") or "", work.get("doi"))


def _explore_item_html(work: dict, show_relevance: bool) -> str:
    year = f' <span class="viz-grid-year">{_esc(work["year"])}</span>' if work.get("year") else ""
    badges = []
    cited_by = work.get("cited_by_count") or 1
    if cited_by > 1:
        badges.append(f'<span class="viz-badge">cited by {cited_by} of yours</span>')
    if show_relevance and work.get("relevance") is not None:
        badges.append(f'<span class="viz-badge viz-badge-quiet">relevance {work["relevance"]:.2f}</span>')
    return (
        f'<li><span class="viz-explore-title">{_esc(work.get("title") or "Untitled")}</span>{year} '
        f'{"".join(badges)} <span class="viz-explore-links">{_work_links_html(work)}</span></li>'
    )


def _render_exploration_section(stats: dict) -> str:
    """The mind-map: your library at the root, each paper a branch, and under
    each branch the works it cites — the ones you already hold, and the ones
    you have not imported yet.

    Built from nested <details>, not a drawn tree, so expanding is native
    (works with no JS, keyboard, and screen readers), branches can be opened
    one at a time instead of all competing for space at once, and a paper
    citing eighty works costs nothing until you actually open it.
    """
    exploration = stats["exploration"]
    papers = exploration["papers"]

    if not stats["references_fetched"]:
        return (
            '<div class="viz-section"><p class="viz-muted">No reference lists fetched yet — re-run '
            "<code>index-library --fetch-references</code> to build this view.</p></div>"
        )

    with_route = [p for p in papers if p["to_explore_total"]]
    if not with_route and not exploration["distinct_off_topic"]:
        return (
            '<div class="viz-section"><p class="viz-none">Every work your papers cite is already in your '
            "library — no unexplored route from here.</p></div>"
        )

    show_relevance = exploration["questions_configured"]
    branches = []
    for paper in papers:
        if not (paper["to_explore_total"] or paper["in_library"]):
            continue
        year = f' <span class="viz-grid-year">{_esc(paper["year"])}</span>' if paper["year"] else ""
        counts = []
        if paper["to_explore_total"]:
            counts.append(f'<span class="viz-badge viz-badge-accent">{paper["to_explore_total"]} to explore</span>')
        if paper["in_library"]:
            counts.append(f'<span class="viz-badge viz-badge-quiet">{len(paper["in_library"])} already held</span>')

        body = []
        if paper["to_explore_total"]:
            shown = "".join(_explore_item_html(w, show_relevance) for w in paper["to_explore"])
            rest = paper["to_explore_total"] - len(paper["to_explore"])
            more = f'<li class="viz-muted">…and {rest} more</li>' if rest > 0 else ""
            body.append(
                '<p class="viz-branch-label">Cites, not in your library — worth a look</p>'
                f'<ul class="viz-explore-list">{shown}{more}</ul>'
            )
        if paper["in_library"]:
            held = "".join(
                f'<li><span class="viz-explore-title">{_esc(w["title"])}</span>'
                + (f' <span class="viz-grid-year">{_esc(w["year"])}</span>' if w.get("year") else "")
                + "</li>"
                for w in paper["in_library"]
            )
            body.append(
                '<p class="viz-branch-label">Cites, already in your library</p>'
                f'<ul class="viz-explore-list viz-explore-held">{held}</ul>'
            )
        if paper["off_topic_count"]:
            body.append(
                f'<p class="viz-muted">{paper["off_topic_count"]} further cited work(s) scored off-topic '
                "for your questions and are not listed here.</p>"
            )

        branches.append(
            '<details class="viz-branch"><summary>'
            f'<span class="viz-explore-title">{_esc(paper["title"])}</span>{year} {"".join(counts)}'
            f'</summary><div class="viz-branch-body">{"".join(body)}</div></details>'
        )

    filtered_note = ""
    if show_relevance and exploration["distinct_off_topic"]:
        filtered_note = (
            f'<p class="viz-muted">{exploration["distinct_off_topic"]} distinct cited work(s) scored below '
            f'{exploration["min_relevance"]:.2f} against your questions and are left out of the branches above — '
            "raise or lower the bar with <code>--min-gap-relevance</code>, or set it to <code>0</code> to keep "
            "everything.</p>"
        )
    elif not show_relevance:
        filtered_note = (
            '<p class="viz-muted">No research question or sub-questions configured, so nothing is filtered — '
            "set them and re-run to keep off-topic citations out of this route.</p>"
        )

    return f"""
    <div class="viz-section">
      <p class="viz-lede">Where to go next from what you already have. Expand a paper to see what it cites:
      the works you have not imported yet — your exploration route —
      {"and " if show_relevance else ""}the ones already in your library.
      <strong>{exploration['distinct_to_explore']}</strong> distinct work(s) are cited but not imported.</p>
      <div class="viz-tree">{''.join(branches)}</div>
      {filtered_note}
    </div>
    """


# --- Relevance to your questions (heatmap) --------------------------------


def _stance_cell_html(stance: str, title: str, question_label: str) -> str:
    cls = "viz-cell viz-cell-unrelated" if stance == "unrelated" else "viz-cell"
    style = "" if stance == "unrelated" else f' style="background:{STANCE_COLOR_VAR[stance]}"'
    glyph = STANCE_GLYPH[stance] or "·"
    tip = f"{title} — {question_label}: {STANCE_LABEL[stance]}"
    return f'<td class="{cls}"{style} title="{_esc(tip)}"><span aria-hidden="true">{glyph}</span>' \
           f'<span class="viz-sr">{_esc(STANCE_LABEL[stance])}</span></td>'


# Font size carries how many papers a theme reaches. The floor is a
# readable body size rather than a vanishing one — a theme that made the cut
# recurs across papers and should not need squinting at — and the ceiling is
# set so the largest chip still wraps sanely on a narrow screen.
THEME_MIN_FONT_PX = 13
THEME_MAX_FONT_PX = 30


def _theme_font_size(count: int, lowest: int, highest: int) -> int:
    if highest <= lowest:
        return (THEME_MIN_FONT_PX + THEME_MAX_FONT_PX) // 2
    share = (count - lowest) / (highest - lowest)
    return round(THEME_MIN_FONT_PX + share * (THEME_MAX_FONT_PX - THEME_MIN_FONT_PX))


def _theme_paper_links(paper: dict) -> str:
    """Ways to actually get to the paper. The local file comes first where
    there is one: this library was built from files on disk, and opening the
    PDF you already have beats a search box every time."""
    links = []
    path = paper.get("file_path")
    if path:
        links.append(
            f'<a href="{_esc(Path(path).absolute().as_uri())}" target="_blank" rel="noopener">Open file</a>'
        )
    links.append(_find_it_links_html(paper["title"], paper.get("doi")))
    return " · ".join(part for part in links if part)


def _render_theme_panel(index: int, theme: dict) -> str:
    items = []
    for paper in theme["papers"]:
        year = f' <span class="viz-grid-year-col">{paper["year"]}</span>' if paper.get("year") else ""
        engaged = "" if paper.get("engaged") else ' <span class="viz-muted">· speaks to none of your questions</span>'
        items.append(
            f'<li><strong>{_esc(paper["title"])}</strong>{year}{engaged}'
            f'<br><span class="viz-theme-links">{_theme_paper_links(paper)}</span></li>'
        )
    return (
        f'<div class="viz-theme-panel" id="viz-theme-panel-{index}" hidden>'
        f'<p class="viz-theme-panel-title">{len(theme["papers"])} paper(s) using '
        f'\u201c{_esc(theme["label"])}\u201d</p>'
        f'<ul class="viz-theme-papers">{"".join(items)}</ul></div>'
    )


def _render_theme_chips(themes: List[Tuple[int, dict]], lowest: int, highest: int) -> str:
    chips = []
    for index, theme in themes:
        size = _theme_font_size(len(theme["papers"]), lowest, highest)
        chips.append(
            f'<button type="button" class="viz-theme-chip" style="font-size:{size}px" '
            f'aria-pressed="false" aria-controls="viz-theme-panel-{index}" data-theme="{index}">'
            f'{_esc(theme["label"])}'
            f'<span class="viz-theme-count">{len(theme["papers"])}</span></button>'
        )
    return f'<div class="viz-theme-cloud">{"".join(chips)}</div>'


def _render_themes_section(stats: dict) -> str:
    """The one view built from the papers' own words rather than from the
    questions — so it can show a cluster in the library that none of the
    questions reach, which nothing built from the questions ever could.

    Size carries reach (how many distinct papers use the term). Colour is
    left free for selection state rather than repeating what size already
    says, and the count is printed on every chip so the magnitude is never
    size-alone.
    """
    themes = stats.get("themes") or []
    if not themes:
        return (
            '<div class="viz-section"><p class="viz-muted">No recurring themes found — with this few '
            "papers (or this little abstract text), no phrase appears in more than one of them "
            "yet.</p></div>"
        )

    counts = [len(t["papers"]) for t in themes]
    lowest, highest = min(counts), max(counts)
    indexed = list(enumerate(themes))
    engaged = [(i, t) for i, t in indexed if t["engaged_papers"]]
    unengaged = [(i, t) for i, t in indexed if not t["engaged_papers"]]

    lede = (
        '<p class="viz-lede">Recurring phrases in your papers\u2019 titles and abstracts, sized by how '
        "many <strong>different</strong> papers use them \u2014 a phrase repeated fifteen times inside one "
        "paper is that paper\u2019s vocabulary, not a theme. Pick one to see the papers it comes from.</p>"
    )

    groups = []
    if stats.get("sub_questions") and engaged and unengaged:
        groups.append(
            '<p class="viz-theme-group">Themes your questions reach</p>'
            + _render_theme_chips(engaged, lowest, highest)
        )
        groups.append(
            '<p class="viz-theme-group">In your library, but no paper using it speaks to any of your '
            "questions</p>" + _render_theme_chips(unengaged, lowest, highest)
        )
    else:
        groups.append(_render_theme_chips(indexed, lowest, highest))

    panels = "".join(_render_theme_panel(i, t) for i, t in indexed)
    empty = (
        '<p class="viz-theme-empty viz-muted">Pick a theme above to list the papers it appears in.</p>'
    )
    # Ships with the no-JS class already on: if the script never runs, every
    # theme's papers are visible instead of a cloud that does nothing when
    # clicked. The script's first act is to take it off.
    return (
        f'<div class="viz-section viz-no-js">{lede}{"".join(groups)}{empty}{panels}'
        f"<script>{_THEMES_JS}</script></div>"
    )


def _render_relevance_grid_section(stats: dict) -> str:
    rows = stats.get("relevance_rows") or []
    sub_questions = stats.get("sub_questions") or []
    research_question = stats.get("research_question")

    if not rows:
        return '<div class="viz-section"><p class="viz-none">Nothing indexed yet.</p></div>'
    if not sub_questions and not research_question:
        return (
            '<div class="viz-section"><p class="viz-muted">No research question or sub-questions configured, '
            "so there is nothing to score relevance against — pass <code>--question</code>/"
            "<code>--sub-questions</code>, or set them once via <code>configure</code>, and re-run.</p></div>"
        )

    shown = rows[:MAX_HEATMAP_ROWS]
    headers = ['<th class="viz-grid-rowhead">Paper</th>', '<th class="viz-grid-year-col">Year</th>']
    if research_question:
        headers.append('<th title="Keyword overlap with your research question">Relevance</th>')
    for i, question in enumerate(sub_questions, start=1):
        headers.append(f'<th title="{_esc(question)}">Q{i}</th>')

    body = []
    for row in shown:
        cells = [
            f'<td class="viz-grid-rowhead" title="{_esc(row["title"])}">'
            f'<span class="viz-grid-title">{_esc(row["title"])}</span></td>',
            f'<td class="viz-grid-year-col">{_esc(row["year"] or "")}</td>',
        ]
        if research_question:
            score = row["relevance"] or 0.0
            # A bar, not a second color scale: relevance is magnitude while
            # the stance cells beside it are polarity, and two color ramps
            # in one grid would blur into each other.
            cells.append(
                '<td><div class="viz-relbar">'
                f'<div class="viz-relbar-track"><div class="viz-relbar-fill" style="width:{min(score, 1.0) * 100:.0f}%"></div></div>'
                f'<span class="viz-relbar-value">{score:.2f}</span></div></td>'
            )
        for qi, stance in enumerate(row["stances"], start=1):
            cells.append(_stance_cell_html(stance, row["title"], f"Q{qi}"))
        body.append(f"<tr>{''.join(cells)}</tr>")

    legend = "".join(
        f'<span><span class="viz-swatch" style="background:{STANCE_COLOR_VAR[key]}"></span>'
        f"{STANCE_GLYPH[key] or '·'} {STANCE_LABEL[key]}</span>"
        for key in ("supports", "challenges", "mixed", "unrelated")
    ) if sub_questions else ""

    qkey = ""
    if sub_questions:
        items = "".join(f"<li>{_esc(q)}</li>" for q in sub_questions)
        qkey = f'<ol class="viz-qkey">{items}</ol>'

    truncated = ""
    if len(rows) > len(shown):
        truncated = (
            f'<p class="viz-muted">Showing the {len(shown)} most relevant of {len(rows)} paper(s) — '
            "the companion Excel matrix has every row.</p>"
        )

    engaged_none = sum(1 for r in rows if sub_questions and r["engaged"] == 0)
    lede_tail = (
        f" <strong>{engaged_none}</strong> paper(s) speak to none of them."
        if sub_questions and engaged_none
        else ""
    )

    return f"""
    <div class="viz-section">
      <p class="viz-lede">Every indexed paper against every question you are asking, most relevant first —
      so a paper that earns its place is obvious at the top, and one that does not is obvious at the
      bottom.{lede_tail}</p>
      <div class="viz-legend">{legend}</div>
      <div class="viz-scroll">
        <table class="viz-grid">
          <thead><tr>{''.join(headers)}</tr></thead>
          <tbody>{''.join(body)}</tbody>
        </table>
      </div>
      {truncated}
      {qkey}
    </div>
    """


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


def build_visualization_html(
    index: LibraryIndex,
    sub_questions: Optional[List[str]] = None,
    use_llm: bool = False,
    llm_model: str = llm.DEFAULT_EXTRACTION_MODEL,
    research_question: Optional[str] = None,
    stance_cache_path: Optional[str] = None,
    matrix_filename: Optional[str] = None,
    min_gap_relevance: float = DEFAULT_MIN_GAP_RELEVANCE,
) -> str:
    """Convenience entry point used by the CLI: compute + render in one call."""
    return render_html(
        compute_stats(
            index,
            sub_questions=sub_questions,
            use_llm=use_llm,
            llm_model=llm_model,
            research_question=research_question,
            stance_cache_path=stance_cache_path,
            min_gap_relevance=min_gap_relevance,
        ),
        matrix_filename=matrix_filename,
    )


def build_literature_matrix(index: LibraryIndex, stats: dict, style: str = "apa"):
    """The companion Excel synthesis matrix for a visualize-library run —
    built from the same `stats` compute_stats() already produced, so it
    reuses whatever stance analysis that run already computed (cached or
    freshly classified) instead of triggering a second round of Claude
    calls. Returns an openpyxl Workbook; call `.save(path)` on it."""
    return build_literature_matrix_workbook(
        index,
        style=style,
        sub_questions=stats.get("sub_questions") or [],
        research_question=stats.get("research_question"),
        analysis=stats.get("_stance_analysis"),
        themes=stats.get("themes"),
    )
