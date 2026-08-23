"""Part 1: Topic Finder — orchestrates the search/dedupe/score/summarize/report pipeline."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .citations import STYLES
from .dedupe import dedupe_papers
from .relevance import keywords_from_text, score_relevance, title_similarity
from .report import ScoredPaper, build_report
from .sources import ALL_SOURCES
from .summarize import summarize

DEFAULT_SOURCES = list(ALL_SOURCES.keys())


@dataclass
class TopicFinderInputs:
    field: str
    working_title: str
    research_question: Optional[str] = None
    extra_keywords: Optional[str] = None
    style: str = "apa"
    sources: Optional[List[str]] = None
    limit_per_source: int = 15
    top_n: int = 20
    min_relevance: float = 0.12
    use_llm_summaries: bool = False
    llm_model: str = "claude-sonnet-5"
    contact_email: Optional[str] = None
    output_path: Optional[str] = None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "thesis-topic"


def _build_query_text(inputs: TopicFinderInputs) -> str:
    parts = [inputs.working_title]
    if inputs.research_question:
        parts.append(inputs.research_question)
    if inputs.extra_keywords:
        parts.append(inputs.extra_keywords)
    return ". ".join(p for p in parts if p)


def run_topic_finder(inputs: TopicFinderInputs) -> str:
    """Run the full pipeline and return the path to the written report."""
    if inputs.style.lower() not in STYLES:
        raise ValueError(f"Unknown citation style '{inputs.style}'. Choose from: {', '.join(STYLES)}")

    sources_to_use = inputs.sources or DEFAULT_SOURCES
    unknown = [s for s in sources_to_use if s not in ALL_SOURCES]
    if unknown:
        raise ValueError(f"Unknown source(s): {', '.join(unknown)}. Available: {', '.join(ALL_SOURCES)}")

    query_text = _build_query_text(inputs)
    keywords = keywords_from_text(query_text)
    search_query = " ".join(keywords) if keywords else query_text

    print(f"Searching {len(sources_to_use)} source(s) for: {search_query!r}", file=sys.stderr)

    all_papers = []
    for source_name in sources_to_use:
        client_cls = ALL_SOURCES[source_name]
        if source_name in ("openalex", "crossref"):
            client = client_cls(mailto=inputs.contact_email) if inputs.contact_email else client_cls()
        else:
            client = client_cls()
        print(f"  querying {source_name}...", file=sys.stderr)
        found = client.search(search_query, limit=inputs.limit_per_source)
        print(f"    -> {len(found)} result(s)", file=sys.stderr)
        all_papers.extend(found)

    deduped = dedupe_papers(all_papers)
    print(f"{len(all_papers)} raw results -> {len(deduped)} after de-duplication", file=sys.stderr)

    scored: List[ScoredPaper] = []
    for paper in deduped:
        relevance = score_relevance(query_text, paper)
        if relevance < inputs.min_relevance:
            continue
        sim = title_similarity(inputs.working_title, paper.title)
        summary = summarize(paper.abstract, paper.title, query_text, use_llm=inputs.use_llm_summaries, model=inputs.llm_model)
        scored.append(ScoredPaper(paper=paper, relevance=relevance, title_similarity=sim, summary=summary))

    # Sort: title-similarity "danger" first (so novelty-critical hits surface even if
    # relevance scoring underrates them), then by relevance.
    scored.sort(key=lambda sp: (sp.title_similarity, sp.relevance), reverse=True)
    top = scored[: inputs.top_n]

    report_text = build_report(
        field=inputs.field,
        working_title=inputs.working_title,
        research_question=inputs.research_question,
        keywords=keywords,
        style=inputs.style,
        scored_papers=top,
        sources_used=sources_to_use,
        total_found=len(deduped),
    )

    output_path = Path(inputs.output_path) if inputs.output_path else _default_output_path(inputs.working_title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")

    return str(output_path)


def _default_output_path(working_title: str) -> Path:
    import datetime as _dt

    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("output") / f"{_slugify(working_title)}-{timestamp}.md"
