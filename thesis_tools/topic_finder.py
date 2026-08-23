"""Part 1: Topic Finder — orchestrates the search/dedupe/score/summarize/report pipeline."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from . import llm
from .citations import STYLES
from .dedupe import dedupe_papers
from .paper_download import download_papers
from .relevance import keywords_from_text, score_relevance, title_similarity
from .report import ScoredPaper, build_report
from .sources import ALL_SOURCES
from .sources.base import Paper
from .subquestions import analyze_subquestions, generate_subquestions
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
    llm_model: str = llm.DEFAULT_MODEL
    # A separate, cheaper model for the bulk per-paper work (summaries,
    # sub-question stance classification) — llm_model itself stays reserved
    # for the one-shot, quality-sensitive sub-question generation call. See
    # llm.py for why these are split.
    extraction_llm_model: str = llm.DEFAULT_EXTRACTION_MODEL
    contact_email: Optional[str] = None
    output_path: Optional[str] = None
    sub_questions: Optional[List[str]] = None
    auto_subquestions: bool = True
    # Path to a previous run's <report>.papers.json cache. When set, skips the
    # search entirely and re-scores/re-summarizes/re-analyzes the same papers
    # against (possibly changed) sub_questions/style/etc — so editing your
    # sub-questions doesn't mean re-hitting the search APIs from scratch.
    reanalyze_from: Optional[str] = None
    # Opt-in: download each shortlisted paper's open-access PDF (where a
    # source API reports one) and extract its text, saving both under
    # download_dir. Never follows a paywalled/scraped link — see
    # paper_download.py. Off by default: it costs bandwidth/time and not
    # every paper has an open-access copy.
    download_papers: bool = False
    download_dir: str = "processed"


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


def cache_path_for(output_path: Path) -> Path:
    """The <report>.papers.json path for a given report path — deterministic,
    so callers (the CLI, Part 3) can find it without being told."""
    return Path(str(output_path) + ".papers.json")


def _load_cache(path: Path) -> tuple:
    if not path.is_file():
        raise ValueError(f"Reanalyze cache not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    papers = [Paper(**p) for p in data.get("papers", [])]
    sources_used = data.get("sources_used", [])
    return papers, sources_used


def load_cache_metadata(path: Path) -> dict:
    """Everything about a run *except* the paper list itself — used by the
    CLI to learn which sub-questions actually ended up being used (including
    any Claude auto-generated ones) without changing run_topic_finder's
    return type."""
    if not Path(path).is_file():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: v for k, v in data.items() if k != "papers"}


def _save_cache(
    path: Path,
    papers: List[Paper],
    sources_used: List[str],
    *,
    field: str,
    working_title: str,
    research_question: Optional[str],
    sub_questions: List[str],
    style: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "field": field,
        "working_title": working_title,
        "research_question": research_question,
        "sub_questions": sub_questions,
        "style": style,
        "sources_used": sources_used,
        "papers": [asdict(p) for p in papers],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_topic_finder(inputs: TopicFinderInputs) -> str:
    """Run the full pipeline and return the path to the written report."""
    if inputs.style.lower() not in STYLES:
        raise ValueError(f"Unknown citation style '{inputs.style}'. Choose from: {', '.join(STYLES)}")

    if inputs.use_llm_summaries:
        issue = llm.availability_issue()
        if issue:
            print(f"Claude requested but unavailable ({issue}) — using heuristics for this run.", file=sys.stderr)

    query_text = _build_query_text(inputs)
    keywords = keywords_from_text(query_text)

    if inputs.reanalyze_from:
        deduped, sources_to_use = _load_cache(Path(inputs.reanalyze_from))
        print(f"Reanalyzing {len(deduped)} cached paper(s) — no new search, sub-questions/style can change freely.", file=sys.stderr)
    else:
        sources_to_use = inputs.sources or DEFAULT_SOURCES
        unknown = [s for s in sources_to_use if s not in ALL_SOURCES]
        if unknown:
            raise ValueError(f"Unknown source(s): {', '.join(unknown)}. Available: {', '.join(ALL_SOURCES)}")

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
        summary = summarize(
            paper.abstract,
            paper.title,
            query_text,
            use_llm=inputs.use_llm_summaries,
            model=inputs.extraction_llm_model,
            full_text_excerpt=paper.full_text_excerpt,
        )
        scored.append(ScoredPaper(paper=paper, relevance=relevance, title_similarity=sim, summary=summary))

    # Sort: title-similarity "danger" first (so novelty-critical hits surface even if
    # relevance scoring underrates them), then by relevance.
    scored.sort(key=lambda sp: (sp.title_similarity, sp.relevance), reverse=True)
    top = scored[: inputs.top_n]

    if inputs.download_papers:
        candidates = [sp.paper for sp in top if sp.paper.pdf_url]
        print(
            f"Downloading {len(candidates)} open-access PDF(s) of {len(top)} shortlisted paper(s) "
            f"into {inputs.download_dir}/...",
            file=sys.stderr,
        )
        saved = download_papers(candidates, dest_dir=inputs.download_dir)
        print(f"  -> saved {saved} PDF(s) + extracted text excerpt(s)", file=sys.stderr)

    sub_questions = list(inputs.sub_questions) if inputs.sub_questions else []
    if not sub_questions and inputs.auto_subquestions and inputs.use_llm_summaries:
        print("Generating sub-questions with Claude...", file=sys.stderr)
        sub_questions = generate_subquestions(query_text, model=inputs.llm_model)
        if sub_questions:
            print("Claude suggested (auto-accepted, non-interactive run):", file=sys.stderr)
            for i, q in enumerate(sub_questions, start=1):
                print(f"  {i}. {q}", file=sys.stderr)
        else:
            print("Claude didn't return any sub-questions for this topic.", file=sys.stderr)

    subquestion_analysis = None
    if sub_questions:
        print(f"Analyzing {len(top)} paper(s) against {len(sub_questions)} sub-question(s)...", file=sys.stderr)
        subquestion_analysis = analyze_subquestions(
            sub_questions,
            [sp.paper for sp in top],
            use_llm=inputs.use_llm_summaries,
            model=inputs.extraction_llm_model,
        )

    report_text = build_report(
        field=inputs.field,
        working_title=inputs.working_title,
        research_question=inputs.research_question,
        keywords=keywords,
        style=inputs.style,
        scored_papers=top,
        sources_used=sources_to_use,
        total_found=len(deduped),
        subquestion_analysis=subquestion_analysis,
    )

    output_path = Path(inputs.output_path) if inputs.output_path else _default_output_path(inputs.working_title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")

    cache_path = cache_path_for(output_path)
    _save_cache(
        cache_path,
        deduped,
        sources_to_use,
        field=inputs.field,
        working_title=inputs.working_title,
        research_question=inputs.research_question,
        sub_questions=sub_questions,
        style=inputs.style,
    )
    print(
        f"Saved {len(deduped)} paper(s) to {cache_path} — change --sub-questions/--style and pass "
        f"--reanalyze {cache_path} to update the report without re-searching.",
        file=sys.stderr,
    )

    return str(output_path)


def _default_output_path(working_title: str) -> Path:
    import datetime as _dt

    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("output") / f"{_slugify(working_title)}-{timestamp}.md"
