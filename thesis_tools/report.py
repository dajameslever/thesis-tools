"""Render the Topic Finder results into a Markdown report."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import List, Optional

from .citations import format_citation
from .recency import newest_year, recency_label
from .relevance import OVERLAP_LABELS, overlap_flag
from .sources.base import Paper
from .subquestions import SubquestionAnalysis

_STANCE_ICONS = {"supports": "✅", "challenges": "❌", "mixed": "⚖️", "unrelated": "·"}


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
    subquestion_analysis: Optional[SubquestionAnalysis] = None,
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

    newest = newest_year([sp.paper.year for sp in scored_papers])

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

    if subquestion_analysis and subquestion_analysis.sub_questions:
        lines.extend(_render_subquestion_sections(subquestion_analysis))

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
            f"· **Found via:** {', '.join(p.sources)} · **{recency_label(p.year, newest_year_in_set=newest)}**"
        )
        lines.append("")
        if sp.summary:
            lines.append(sp.summary)
            lines.append("")
        if subquestion_analysis and subquestion_analysis.sub_questions:
            stance_bits = []
            stances = subquestion_analysis.stances_for(p)
            for j, question in enumerate(subquestion_analysis.sub_questions, start=1):
                stance = stances.get(question)
                if stance and stance.stance != "unrelated":
                    stance_bits.append(f"{_STANCE_ICONS.get(stance.stance, '·')} Q{j}: {stance.stance}")
            if stance_bits:
                lines.append(f"**Sub-question stances:** {' · '.join(stance_bits)}")
                lines.append("")
        lines.append(f"> {format_citation(p, style)}")
        lines.append("")
        if p.url:
            lines.append(f"[Link]({p.url})")
            lines.append("")

    if scored_papers:
        lines.extend(_render_compare_and_contrast(scored_papers, subquestion_analysis, newest))

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
    if subquestion_analysis and subquestion_analysis.tensions():
        lines.append("5. Look hard at the disagreements in 'Where the literature disagrees' above — an unresolved conflict in prior findings is often exactly the gap a thesis can fill.")
    lines.append("")

    return "\n".join(lines)


def _render_compare_and_contrast(
    scored_papers: List[ScoredPaper],
    subquestion_analysis: Optional[SubquestionAnalysis],
    newest: Optional[int],
) -> List[str]:
    lines: List[str] = []
    lines.append("## Compare and contrast")
    lines.append("")
    lines.append("A side-by-side view of everything found, so you can weigh sources against each other rather than reading them in isolation:")
    lines.append("")

    has_subquestions = bool(subquestion_analysis and subquestion_analysis.sub_questions)
    header = ["#", "Title", "Year", "Recency", "Relevance", "Cited by"]
    if has_subquestions:
        header.append("Stances")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    for i, sp in enumerate(scored_papers, start=1):
        p = sp.paper
        short_title = p.title if len(p.title) <= 60 else p.title[:59] + "…"
        row = [
            str(i),
            short_title,
            str(p.year) if p.year else "n.d.",
            "Older" if p.year and newest and (newest - p.year) >= 10 else "Recent",
            f"{sp.relevance:.0%}",
            str(p.citation_count) if p.citation_count is not None else "n/a",
        ]
        if has_subquestions:
            stances = subquestion_analysis.stances_for(p)
            bits = [
                _STANCE_ICONS.get(stances[q].stance, "·")
                for q in subquestion_analysis.sub_questions
                if q in stances
            ]
            row.append("".join(bits) if bits else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    years = [(sp.paper.year, sp.paper.title) for sp in scored_papers if sp.paper.year]
    if len(years) >= 2:
        oldest_year, oldest_title = min(years)
        newest_paper_year, newest_title = max(years)
        if newest_paper_year - oldest_year >= 10 and oldest_title != newest_title:
            lines.append(
                f"_This set spans {newest_paper_year - oldest_year} years, from \"{oldest_title}\" ({oldest_year}) to "
                f"\"{newest_title}\" ({newest_paper_year}). Worth checking whether the older source has been "
                f"superseded, corrected, or extended by the more recent one._"
            )
            lines.append("")

    return lines


def _render_subquestion_sections(analysis: SubquestionAnalysis) -> List[str]:
    lines: List[str] = []
    lines.append("## Sub-questions")
    lines.append("")
    lines.append(
        "Your topic broken into sharper sub-questions, each checked against the papers found above "
        "(✅ supports · ❌ challenges · ⚖️ mixed evidence):"
    )
    lines.append("")
    for i, question in enumerate(analysis.sub_questions, start=1):
        lines.append(f"{i}. {question}")
    lines.append("")

    for i, question in enumerate(analysis.sub_questions, start=1):
        grouped = analysis.titles_by_stance(question)
        supporters, challengers, mixed = grouped["supports"], grouped["challenges"], grouped["mixed"]

        lines.append(f"### Q{i}. {question}")
        lines.append("")
        if not supporters and not challengers and not mixed:
            lines.append("_No paper found above speaks directly to this sub-question yet — worth a targeted follow-up search._")
        else:
            if supporters:
                lines.append(f"- ✅ **Supports:** {', '.join(supporters)}")
            if challengers:
                lines.append(f"- ❌ **Challenges:** {', '.join(challengers)}")
            if mixed:
                lines.append(f"- ⚖️ **Mixed evidence:** {', '.join(mixed)}")
        lines.append("")

    tensions = analysis.tensions()
    if tensions:
        lines.append("### Where the literature disagrees")
        lines.append("")
        lines.append("These sub-questions have papers on both sides — a live tension your thesis could address:")
        lines.append("")
        for question, sides in tensions.items():
            lines.append(f"- **{question}**")
            lines.append(f"  - Supports: {', '.join(sides['supports'])}")
            lines.append(f"  - Challenges: {', '.join(sides['challenges'])}")
        lines.append("")

    return lines
