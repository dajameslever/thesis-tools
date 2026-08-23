"""Render the Topic Finder results into a Markdown report."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import List, Optional

from .citations import format_citation
from .relevance import OVERLAP_LABELS, overlap_flag
from .sources.base import Paper


@dataclass
class ScoredPaper:
    paper: Paper
    relevance: float
    title_similarity: float
    summary: Optional[str] = None

    @property
    def flag(self) -> str:
        return overlap_flag(self.title_similarity)


def build_report(
    *,
    field: str,
    working_title: str,
    research_question: Optional[str],
    keywords: List[str],
    style: str,
    scored_papers: List[ScoredPaper],
    sources_used: List[str],
    total_found: int,
) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: List[str] = []

    lines.append(f"# Thesis Topic Finder — Report")
    lines.append("")
    lines.append(f"*Generated {now}*")
    lines.append("")
    lines.append(f"- **Field:** {field}")
    lines.append(f"- **Proposed working title:** {working_title}")
    if research_question:
        lines.append(f"- **Research question:** {research_question}")
    if keywords:
        lines.append(f"- **Keywords used for search:** {', '.join(keywords)}")
    lines.append(f"- **Sources searched:** {', '.join(sources_used)}")
    lines.append(f"- **Citation style:** {style.upper()}")
    lines.append(f"- **Candidates found (after de-duplication):** {total_found}, showing top {len(scored_papers)}")
    lines.append("")
    lines.append(
        "> ⚠️ **Coverage note:** this scan covers Semantic Scholar, OpenAlex, Crossref and arXiv "
        "(all free, no-login sources). It does **not** query ScienceDirect or Google Scholar "
        "directly — neither offers a supported way to do that programmatically (ScienceDirect "
        "needs a paid Elsevier API key/institutional access; Google Scholar has no public API "
        "and blocks automated queries). The sources above index the same underlying journal "
        "articles Google Scholar would surface for a novelty check, but treat 'nothing found' "
        "as 'nothing found in these sources' — not proof no one has asked your question. Always "
        "also do a manual check in your institution's library database before finalizing a topic."
    )
    lines.append("")

    critical = [sp for sp in scored_papers if sp.flag == "critical"]
    high = [sp for sp in scored_papers if sp.flag == "high"]

    lines.append("## Novelty check")
    lines.append("")
    if not critical and not high:
        lines.append(
            "No existing paper title found is a close textual match to your proposed title. "
            "That's a good sign for novelty, but keep reading the 'related' section below — "
            "someone may have answered your underlying *question* while phrasing the title "
            "differently."
        )
    else:
        if critical:
            lines.append(f"**{len(critical)} near-identical title(s) found.** Your proposed title may already be taken:")
            lines.append("")
            for sp in critical:
                lines.append(f"- \"{sp.paper.title}\" ({sp.paper.year or 'n.d.'}) — title similarity {sp.title_similarity:.0%}")
            lines.append("")
        if high:
            lines.append(f"**{len(high)} paper(s) with high title overlap** — read these closely and narrow/differentiate your angle:")
            lines.append("")
            for sp in high:
                lines.append(f"- \"{sp.paper.title}\" ({sp.paper.year or 'n.d.'}) — title similarity {sp.title_similarity:.0%}")
            lines.append("")

    lines.append("## Related work (ranked by relevance)")
    lines.append("")
    if not scored_papers:
        lines.append("No related papers were found in the searched sources for this topic/keywords.")
    for i, sp in enumerate(scored_papers, start=1):
        p = sp.paper
        authors = ", ".join(p.authors[:3]) + (" et al." if len(p.authors) > 3 else "")
        lines.append(f"### {i}. {p.title}")
        lines.append("")
        lines.append(f"*{authors or 'Unknown authors'} — {p.year or 'n.d.'} — {p.venue or 'Unknown venue'}*")
        lines.append("")
        lines.append(
            f"**Relevance:** {sp.relevance:.0%} · **Title overlap:** {OVERLAP_LABELS[sp.flag]} "
            f"· **Cited by:** {p.citation_count if p.citation_count is not None else 'n/a'} "
            f"· **Found via:** {', '.join(p.sources)}"
        )
        lines.append("")
        if sp.summary:
            lines.append(sp.summary)
            lines.append("")
        lines.append(f"> {format_citation(p, style)}")
        lines.append("")
        if p.url:
            lines.append(f"[Link]({p.url})")
            lines.append("")

    lines.append("## Full bibliography")
    lines.append("")
    lines.append(f"*({style.upper()} style — verify against your institution's exact requirements before submitting)*")
    lines.append("")
    sorted_for_biblio = sorted(scored_papers, key=lambda sp: (sp.paper.authors[0] if sp.paper.authors else sp.paper.title))
    for i, sp in enumerate(sorted_for_biblio, start=1):
        lines.append(f"{format_citation(sp.paper, style, ref_number=i)}")
        lines.append("")

    lines.append("## Suggested next steps")
    lines.append("")
    lines.append("1. Read the abstracts of anything flagged 🟠 or ⚠️ above in full before committing to this title.")
    lines.append(
        "2. If there's overlap, differentiate along one axis the closest papers don't cover: a different "
        "population/dataset, geography, time period, method, or scale."
    )
    lines.append("3. Turn your working title into a one-sentence research question and re-run this tool against just that question.")
    lines.append("4. Run a manual search in your university library's database (ScienceDirect, JSTOR, etc.) for a final check — this report is a fast first pass, not a substitute for a full literature review.")
    lines.append("")

    return "\n".join(lines)
