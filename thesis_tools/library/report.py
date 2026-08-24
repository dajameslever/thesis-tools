"""Render the Library Indexer's results into a Markdown report."""

from __future__ import annotations

import datetime as _dt
from typing import Dict, Optional

from ..citations import format_citation
from ..links import google_scholar_search_url, sciencedirect_search_url
from ..recency import newest_year, recency_label
from ..subquestions import SubquestionAnalysis
from .citation_graph import build_coverage, build_mermaid_mindmap, indexed_dois, split_by_relevance
from .index_store import LibraryIndex

_STANCE_ICONS = {"supports": "✅", "challenges": "❌", "mixed": "⚖️", "unrelated": "·"}


def _deep_search_lines(query: str) -> str:
    return (
        f"[Search Google Scholar]({google_scholar_search_url(query)}) · "
        f"[Search ScienceDirect]({sciencedirect_search_url(query)})"
    )


def build_library_report(
    index: LibraryIndex,
    style: str,
    research_question: Optional[str] = None,
    subquestion_analysis: Optional[SubquestionAnalysis] = None,
    summaries: Optional[Dict[str, str]] = None,
    relevance_scores: Optional[Dict[str, float]] = None,
) -> str:
    summaries = summaries or {}
    relevance_scores = relevance_scores or {}
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []

    lines.append("# Local Library Index")
    lines.append("")
    lines.append(f"*Generated {now}*")
    lines.append("")

    verified = [e for e in index.entries if e.confidence.startswith("verified")]
    unresolved = [e for e in index.entries if e.confidence == "unresolved"]
    duplicates = index.duplicates_by_doi()
    newest = newest_year([e.paper.year for e in index.entries])

    lines.append(f"- **Files indexed:** {len(index.entries)}")
    lines.append(f"- **Verified against Crossref/Semantic Scholar:** {len(verified)}")
    lines.append(f"- **Unresolved (local metadata only, needs a manual check):** {len(unresolved)}")
    if duplicates:
        lines.append(f"- **⚠️ Possible duplicate downloads (same DOI, different files):** {len(duplicates)}")
    if research_question:
        lines.append(f"- **Research question:** {research_question}")
    if subquestion_analysis and subquestion_analysis.sub_questions:
        lines.append(f"- **Sub-questions:** {len(subquestion_analysis.sub_questions)} (see below)")
    lines.append(f"- **Citation style:** {style.upper()}")
    lines.append("")

    if duplicates:
        lines.append("## Possible duplicate downloads")
        lines.append("")
        lines.append("These files share a DOI — likely the same paper saved more than once:")
        lines.append("")
        for doi, group in duplicates.items():
            lines.append(f"- DOI `{doi}`:")
            for entry in group:
                lines.append(f"  - `{entry.file_path}`")
        lines.append("")

    if unresolved:
        lines.append("## Needs manual review")
        lines.append("")
        lines.append(
            "Metadata for these files couldn't be verified against Crossref or Semantic Scholar "
            "(no DOI found in the file, and no confident title match). Double-check the title, "
            "author, and year before citing them — use these to find the canonical record by hand:"
        )
        lines.append("")
        for entry in unresolved:
            lines.append(f"- `{entry.file_path}` — best guess: \"{entry.paper.title}\" ({entry.paper.year or 'year unknown'})")
            lines.append(f"  {_deep_search_lines(entry.paper.title)}")
        lines.append("")

    coverage = build_coverage(index.entries)
    if coverage["total_references"] > 0:
        lines.append("## Citation coverage")
        lines.append("")
        lines.append(
            f"Across your indexed papers' own reference lists: **{coverage['included_references']} of "
            f"{coverage['total_references']}** cited works are already in your library; "
            f"**{coverage['missing_references']}** aren't (many will be older, foundational papers)."
        )
        lines.append("")
        # Same relevance split the HTML visualization applies, so the two do
        # not recommend different reading lists off one index. Suggesting
        # whatever gets cited most fills a reading list with well-cited work
        # that has nothing to do with the thesis.
        questions = [q for q in ([research_question] + list(subquestion_analysis.sub_questions if subquestion_analysis else [])) if q]
        on_topic_gaps, off_topic_gaps = split_by_relevance(coverage["frequently_missing"], questions)
        if on_topic_gaps:
            lines.append("**Recurring gaps** — cited by 2+ of your papers but not yet in your library:")
            lines.append("")
            for gap in on_topic_gaps:
                label = recency_label(gap["year"], newest_year_in_set=newest)
                lines.append(f"- \"{gap['title']}\" — {label} — cited by {len(gap['cited_by'])}: {', '.join(gap['cited_by'])}")
                lines.append(f"  {_deep_search_lines(gap['title'])}")
            lines.append("")
            lines.append("```mermaid")
            lines.append(build_mermaid_mindmap(index.entries, {"frequently_missing": on_topic_gaps}))
            lines.append("```")
            lines.append("")
        if off_topic_gaps:
            lines.append(
                f"_{len(off_topic_gaps)} further recurring gap(s) scored off-topic against your "
                "question(s) and are left out above: "
                + ", ".join(f'"{g["title"]}"' for g in off_topic_gaps)
                + "._"
            )
            lines.append("")

    if subquestion_analysis and subquestion_analysis.sub_questions:
        lines.append("## Sub-questions")
        lines.append("")
        for i, question in enumerate(subquestion_analysis.sub_questions, start=1):
            lines.append(f"{i}. {question}")
        lines.append("")
        for i, question in enumerate(subquestion_analysis.sub_questions, start=1):
            grouped = subquestion_analysis.titles_by_stance(question)
            lines.append(f"### Q{i}. {question}")
            lines.append("")
            if not any(grouped.values()):
                lines.append("_No indexed paper speaks directly to this sub-question yet._")
            else:
                if grouped["supports"]:
                    lines.append(f"- ✅ **Supports:** {', '.join(grouped['supports'])}")
                if grouped["challenges"]:
                    lines.append(f"- ❌ **Challenges:** {', '.join(grouped['challenges'])}")
                if grouped["mixed"]:
                    lines.append(f"- ⚖️ **Mixed evidence:** {', '.join(grouped['mixed'])}")
            lines.append("")
        tensions = subquestion_analysis.tensions()
        if tensions:
            lines.append("### Where the literature disagrees")
            lines.append("")
            for question, sides in tensions.items():
                lines.append(f"- **{question}**")
                lines.append(f"  - Supports: {', '.join(sides['supports'])}")
                lines.append(f"  - Challenges: {', '.join(sides['challenges'])}")
            lines.append("")

    lines.append("## Full bibliography")
    lines.append("")
    lines.append(f"*({style.upper()} style — verify against your institution's exact requirements before submitting)*")
    lines.append("")

    sorted_entries = sorted(
        index.entries,
        key=lambda e: (e.paper.authors[0] if e.paper.authors else e.paper.title),
    )
    known_dois = indexed_dois(index.entries)
    for i, entry in enumerate(sorted_entries, start=1):
        paper = entry.paper
        flag = "" if entry.confidence.startswith("verified") else " ⚠️ *unverified — see above*"
        lines.append(f"{i}. {format_citation(paper, style, ref_number=i)}{flag}")
        lines.append(f"   *(file: `{entry.file_path}`)*")

        key = paper.key()
        summary = summaries.get(key)
        if summary:
            lines.append(f"   - **What it's about:** {summary}")
        contributors = ", ".join(paper.authors) if paper.authors else "Unknown"
        lines.append(f"   - **Contributors:** {contributors}")
        cite_bits = [f"cited by {paper.citation_count} other work(s)" if paper.citation_count is not None else "citation count unknown"]
        if entry.references:
            in_library = sum(1 for r in entry.references if (r.get("doi") or "").strip().lower() in known_dois)
            cite_bits.append(f"cites {len(entry.references)} work(s), {in_library} already in your library")
        lines.append(f"   - **Citations:** {'; '.join(cite_bits)}")
        lines.append(f"   - **Recency:** {recency_label(paper.year, newest_year_in_set=newest)}")
        if key in relevance_scores:
            lines.append(f"   - **Relevance to your research question:** {relevance_scores[key]:.0%}")
        if subquestion_analysis and subquestion_analysis.sub_questions:
            stances = subquestion_analysis.stances_for(paper)
            bits = [
                f"{_STANCE_ICONS.get(stances[q].stance, '·')} Q{j}: {stances[q].stance}"
                for j, q in enumerate(subquestion_analysis.sub_questions, start=1)
                if q in stances and stances[q].stance != "unrelated"
            ]
            if bits:
                lines.append(f"   - **Sub-question stances:** {' · '.join(bits)}")
        lines.append("")

    return "\n".join(lines)
