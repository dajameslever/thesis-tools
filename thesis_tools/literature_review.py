"""Part 3: draft a literature review structured around your sub-questions,
synthesizing whatever papers Part 1 (topic search) and/or Part 2 (your local
library) have already found — no new searching happens here.

Grounded generation only: every claim the LLM path writes must trace back to
an abstract already on hand. Two tiers, same pattern as the rest of the
toolkit:
  * LLM (recommended, needs ANTHROPIC_API_KEY): Claude writes real synthesis
    paragraphs per sub-question with in-text (Author, Year) citations.
  * heuristic fallback: a structured bullet outline grouped by stance — not
    prose, but still a legitimate starting skeleton with zero API calls.

Treat the output as a strong first draft to rewrite in your own voice and
verify against the actual papers — not a citable final product.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import llm
from .citations import STYLES, format_citation
from .dedupe import dedupe_papers
from .relevance import score_relevance
from .sources.base import Paper
from .subquestions import SubquestionAnalysis, analyze_subquestions

DISCLAIMER = (
    "> ⚠️ **This is an AI-assisted DRAFT**, synthesized only from paper *abstracts* already "
    "gathered by Part 1/Part 2 — not full texts. Verify every claim against the actual paper "
    "before relying on it, and rewrite this in your own voice. Treat it as a structured "
    "starting point, not a citable final draft."
)


@dataclass
class LiteratureReviewInputs:
    field: str
    working_title: str
    research_question: Optional[str]
    sub_questions: List[str]
    paper_sources: List[str]  # paths to Part 1 <report>.papers.json and/or Part 2 library/index.json
    style: str = "apa"
    use_llm: bool = True
    llm_model: str = "claude-sonnet-5"
    min_relevance: float = 0.1
    output_path: Optional[str] = None


def _load_papers_from_source(path: str) -> List[Paper]:
    p = Path(path)
    if not p.is_file():
        print(f"  [literature-review] source not found, skipping: {p}", file=sys.stderr)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  [literature-review] couldn't read {p} ({exc})", file=sys.stderr)
        return []

    if "entries" in data:  # Part 2 library/index.json format
        return [Paper(**e["paper"]) for e in data["entries"] if e.get("paper")]
    if "papers" in data:  # Part 1 <report>.papers.json format
        return [Paper(**paper) for paper in data["papers"]]
    print(f"  [literature-review] unrecognized format in {p}, skipping", file=sys.stderr)
    return []


def _load_all_papers(paths: List[str]) -> List[Paper]:
    all_papers: List[Paper] = []
    for path in paths:
        all_papers.extend(_load_papers_from_source(path))
    return dedupe_papers(all_papers)


_INTRO_SYSTEM_PROMPT = (
    "Write a short academic-style introduction (3-5 sentences) for a literature review, framing "
    "why the student's research question matters and what the review covers. Do not invent any "
    "facts, findings, statistics, or citations here — this paragraph only frames motivation and "
    "scope. No citations in this paragraph."
)


def _draft_intro(inputs: LiteratureReviewInputs, num_papers: int, client) -> str:
    if client is not None:
        user_message = (
            f"Field: {inputs.field}\n"
            f"Working title: {inputs.working_title}\n"
            f"Research question: {inputs.research_question or 'n/a'}\n"
            f"Number of sub-questions this review covers: {len(inputs.sub_questions)}"
        )
        result = llm.ask(client, _INTRO_SYSTEM_PROMPT, user_message, model=inputs.llm_model, max_tokens=200)
        if result:
            return result

    topic = inputs.research_question or inputs.working_title
    return (
        f"This review synthesizes {num_papers} source(s) relevant to the question: \"{topic}\". "
        f"It is organized around the sub-questions below, noting where the literature agrees, "
        f"disagrees, or has not yet been explored."
    )


_SYNTHESIS_SYSTEM_PROMPT = (
    "You write ONE literature-review paragraph (150-250 words) addressing the given sub-question, "
    "using ONLY the paper abstracts provided below. Rules:\n"
    "- Ground every claim in the abstracts given. Never invent findings, numbers, or papers not listed.\n"
    "- Cite in-text as (LastName, Year) right after each claim you attribute to a paper.\n"
    "- If the papers disagree with each other, say so explicitly and name which side each is on.\n"
    "- Write in formal academic prose — full sentences and paragraphs, not bullet points.\n"
    "- If the abstracts given don't really address the sub-question, say that plainly instead of stretching."
)


def _paper_block(paper: Paper, stance_label: str) -> str:
    author = paper.authors[0].split()[-1] if paper.authors and paper.authors[0].split() else "Unknown"
    return (
        f"- {author} ({paper.year or 'n.d.'}), stance: {stance_label}. "
        f"Title: {paper.title}. Abstract: {paper.abstract or '(no abstract available)'}"
    )


def _draft_synthesis_paragraph(
    question: str,
    grouped: Dict[str, List[Paper]],
    inputs: LiteratureReviewInputs,
    client,
) -> Tuple[str, List[Paper]]:
    cited_papers = grouped["supports"] + grouped["challenges"] + grouped["mixed"]
    if not cited_papers:
        return (
            "_No paper in the current sources speaks directly to this sub-question — "
            "a potential gap worth targeting with a follow-up search._",
            [],
        )

    if client is not None:
        blocks = [
            _paper_block(p, label)
            for label, papers in (("supports", grouped["supports"]), ("challenges", grouped["challenges"]), ("mixed/ambiguous", grouped["mixed"]))
            for p in papers
        ]
        user_message = f"Sub-question: {question}\n\nPapers:\n" + "\n".join(blocks)
        result = llm.ask(client, _SYNTHESIS_SYSTEM_PROMPT, user_message, model=inputs.llm_model, max_tokens=400)
        if result:
            return result, cited_papers

    # Heuristic fallback: an honest structured outline, not prose.
    lines = []
    for label, papers in (("Supports", grouped["supports"]), ("Challenges", grouped["challenges"]), ("Mixed evidence", grouped["mixed"])):
        for p in papers:
            author = p.authors[0].split()[-1] if p.authors and p.authors[0].split() else "Unknown"
            snippet = (p.abstract or "")[:220].strip()
            lines.append(f"- **{label}** — ({author}, {p.year or 'n.d.'}): {snippet}")
    return "\n".join(lines), cited_papers


_GAPS_SYSTEM_PROMPT = (
    "Write a short 'gaps and tensions' paragraph (100-180 words) for the closing synthesis section "
    "of a literature review, given (1) sub-questions where the papers found disagree with each "
    "other, and (2) sub-questions with no supporting literature at all. Frame these as opportunities "
    "for the student's own thesis contribution. Invent nothing beyond what is given."
)


def _draft_gaps_section(analysis: SubquestionAnalysis, no_coverage: List[str], inputs: LiteratureReviewInputs, client) -> str:
    tensions = analysis.tensions()
    if not tensions and not no_coverage:
        return "No major tensions or coverage gaps were identified among the sub-questions checked."

    if client is not None:
        parts = []
        if tensions:
            parts.append("Sub-questions where the papers found disagree with each other:\n" + "\n".join(f"- {q}" for q in tensions))
        if no_coverage:
            parts.append("Sub-questions with no supporting literature found at all:\n" + "\n".join(f"- {q}" for q in no_coverage))
        result = llm.ask(client, _GAPS_SYSTEM_PROMPT, "\n\n".join(parts), model=inputs.llm_model, max_tokens=300)
        if result:
            return result

    lines = []
    if tensions:
        lines.append("**Disagreements in the literature:**")
        for q in tensions:
            lines.append(f"- {q}")
        lines.append("")
    if no_coverage:
        lines.append("**No literature found for:**")
        for q in no_coverage:
            lines.append(f"- {q}")
    return "\n".join(lines).strip()


def run_literature_review(inputs: LiteratureReviewInputs) -> str:
    """Run the full pipeline and return the path to the written draft."""
    if inputs.style.lower() not in STYLES:
        raise ValueError(f"Unknown citation style '{inputs.style}'. Choose from: {', '.join(STYLES)}")
    if not inputs.sub_questions:
        raise ValueError("No sub-questions to draft around. Run topic-finder first, or pass --sub-questions.")

    papers = _load_all_papers(inputs.paper_sources)
    if not papers:
        raise ValueError(
            "No papers found in the given sources. Run topic-finder and/or index-library first, "
            "or pass --topic-cache/--library-index explicitly."
        )

    query_text = inputs.research_question or inputs.working_title
    scored = [(p, score_relevance(query_text, p)) for p in papers]
    relevant = [p for p, r in scored if r >= inputs.min_relevance]
    if not relevant:
        # Better an unfiltered draft than an empty one — the relevance
        # threshold is a quality filter, not a hard requirement.
        relevant = [p for p, _ in scored]

    client = llm.get_client(quiet=True) if inputs.use_llm else None
    analysis = analyze_subquestions(inputs.sub_questions, relevant, use_llm=inputs.use_llm, model=inputs.llm_model)

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: List[str] = []
    lines.append("# Literature Review — Draft")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")
    lines.append(f"*Generated {now}*")
    lines.append("")
    lines.append(f"- **Field:** {inputs.field}")
    lines.append(f"- **Working title:** {inputs.working_title}")
    if inputs.research_question:
        lines.append(f"- **Research question:** {inputs.research_question}")
    lines.append(f"- **Drawing on:** {len(papers)} paper(s) from {len(inputs.paper_sources)} source file(s)")
    lines.append(f"- **Drafting mode:** {'Claude-written prose' if client else 'heuristic structured outline (no ANTHROPIC_API_KEY, or --no-llm)'}")
    lines.append("")

    lines.append("## Introduction")
    lines.append("")
    lines.append(_draft_intro(inputs, len(relevant), client))
    lines.append("")

    cited_papers_by_key: Dict[str, Paper] = {}
    no_coverage: List[str] = []

    for i, question in enumerate(inputs.sub_questions, start=1):
        grouped = analysis.grouped_papers(question, relevant)
        lines.append(f"## {i}. {question}")
        lines.append("")
        paragraph, cited = _draft_synthesis_paragraph(question, grouped, inputs, client)
        lines.append(paragraph)
        lines.append("")
        if not cited:
            no_coverage.append(question)
        for paper in cited:
            cited_papers_by_key[paper.key()] = paper

    lines.append("## Synthesis: gaps and tensions")
    lines.append("")
    lines.append(_draft_gaps_section(analysis, no_coverage, inputs, client))
    lines.append("")

    lines.append("## References")
    lines.append("")
    lines.append(f"*(Only papers actually cited above, in {inputs.style.upper()} style — verify before submitting.)*")
    lines.append("")
    cited_list = sorted(cited_papers_by_key.values(), key=lambda p: (p.authors[0] if p.authors else p.title))
    if not cited_list:
        lines.append("_No papers were cited in the drafted sections above._")
    for i, paper in enumerate(cited_list, start=1):
        lines.append(format_citation(paper, inputs.style, ref_number=i))
        lines.append("")

    report_text = "\n".join(lines)

    output_path = Path(inputs.output_path) if inputs.output_path else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")

    return str(output_path)


def _default_output_path() -> Path:
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("output") / f"literature-review-{timestamp}.md"
