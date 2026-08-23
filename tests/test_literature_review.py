import json
from unittest.mock import patch

import pytest

from thesis_tools.literature_review import LiteratureReviewInputs, run_literature_review
from thesis_tools.sources.base import Paper


def _write_topic_cache(path, papers, sources_used=None):
    payload = {"sources_used": sources_used or ["semanticscholar"], "papers": [p.__dict__ for p in papers]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_library_index(path, papers):
    payload = {"version": 1, "entries": [{"paper": p.__dict__, "doi": p.doi, "confidence": "verified-doi",
                                            "file_path": f"/x/{i}.pdf", "file_hash": f"h{i}", "file_type": "pdf",
                                            "size_bytes": 1, "indexed_at": "2026-01-01T00:00:00", "references": []}
                                           for i, p in enumerate(papers)]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_run_literature_review_heuristic_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    supports = Paper(
        title="Sleep Loss Increases Risk-Taking",
        year=2020,
        authors=["Jane Doe"],
        doi="10.1/a",
        abstract="We find a significant effect of sleep loss on risk-taking, consistent with theory.",
    )
    challenges = Paper(
        title="Revisiting Sleep and Risk",
        year=2023,
        authors=["Bob Smith"],
        doi="10.1/b",
        abstract="Contrary to expectations, we found no significant effect of sleep loss on risk-taking.",
    )
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [supports, challenges])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="Psychology",
        working_title="Sleep and Risk-Taking",
        research_question="Does sleep loss increase risk-taking?",
        sub_questions=["Does sleep loss increase risk-taking in adolescents?"],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=True,  # but no API key present -> heuristic fallback exercised
    )
    result_path = run_literature_review(inputs)
    assert result_path == str(output_path)

    text = output_path.read_text()
    assert "AI-assisted DRAFT" in text
    assert "heuristic structured outline" in text
    assert "Sleep Loss Increases Risk-Taking" not in text or "Doe" in text  # cited via author in outline
    assert "## Synthesis: gaps and tensions" in text
    assert "## References" in text


def test_run_literature_review_loads_from_library_index(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    paper = Paper(
        title="Sleep and Adolescent Decision-Making",
        year=2021,
        authors=["Jane Doe"],
        doi="10.1/a",
        abstract="We find a significant effect of sleep on decision-making, consistent with theory.",
    )
    index_path = tmp_path / "library" / "index.json"
    index_path.parent.mkdir()
    _write_library_index(index_path, [paper])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="Psychology",
        working_title="Sleep and Decision-Making",
        research_question="Does sleep affect decision-making?",
        sub_questions=["Does sleep affect decision-making?"],
        paper_sources=[str(index_path)],
        output_path=str(output_path),
        use_llm=False,
    )
    run_literature_review(inputs)
    text = output_path.read_text()
    assert "Doe" in text


def test_run_literature_review_merges_and_dedupes_multiple_sources(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    paper = Paper(title="Same Paper", year=2020, authors=["Jane Doe"], doi="10.1/dup", abstract="An abstract with significant effect, consistent with theory.")

    cache_path = tmp_path / "report.md.papers.json"
    index_path = tmp_path / "index.json"
    _write_topic_cache(cache_path, [paper])
    _write_library_index(index_path, [paper])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="X",
        research_question=None,
        sub_questions=["Does X happen?"],
        paper_sources=[str(cache_path), str(index_path)],
        output_path=str(output_path),
        use_llm=False,
    )
    run_literature_review(inputs)
    text = output_path.read_text()
    # Deduped: should only cite the paper once in the reference list.
    assert text.count("Same Paper") <= 1 or text.count("Doe, J.") == 1


def test_run_literature_review_raises_without_sub_questions(tmp_path):
    inputs = LiteratureReviewInputs(
        field="X", working_title="Y", research_question=None, sub_questions=[], paper_sources=[], output_path=str(tmp_path / "r.md")
    )
    with pytest.raises(ValueError, match="sub-question"):
        run_literature_review(inputs)


def test_run_literature_review_raises_when_no_papers_found(tmp_path):
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="Y",
        research_question=None,
        sub_questions=["Does X happen?"],
        paper_sources=[str(tmp_path / "missing.json")],
        output_path=str(tmp_path / "r.md"),
    )
    with pytest.raises(ValueError, match="No papers found"):
        run_literature_review(inputs)


def test_run_literature_review_raises_for_unknown_style(tmp_path):
    inputs = LiteratureReviewInputs(
        field="X", working_title="Y", research_question=None, sub_questions=["Q?"], paper_sources=[], style="vancouver",
        output_path=str(tmp_path / "r.md"),
    )
    with pytest.raises(ValueError):
        run_literature_review(inputs)


def test_run_literature_review_notes_gap_when_no_paper_covers_a_subquestion(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    paper = Paper(title="Unrelated Paper", year=2020, authors=["Jane Doe"], doi="10.1/x", abstract="Coffee prices in Brazil rose sharply.")
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [paper])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="Y",
        research_question=None,
        sub_questions=["Does sleep deprivation affect decision-making?"],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=False,
    )
    run_literature_review(inputs)
    text = output_path.read_text()
    assert "potential gap" in text.lower()
    assert "No literature found for" in text


@patch("thesis_tools.literature_review.llm.get_client")
@patch("thesis_tools.literature_review.llm.ask")
def test_run_literature_review_uses_llm_when_available(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.return_value = "Claude-written synthesis paragraph citing (Doe, 2020)."

    paper = Paper(title="Sleep Study", year=2020, authors=["Jane Doe"], doi="10.1/x", abstract="Some abstract.")
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [paper])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="Y",
        research_question="Does sleep affect things?",
        sub_questions=["Does sleep affect things?"],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=True,
    )
    run_literature_review(inputs)
    text = output_path.read_text()
    assert "Claude-written prose" in text
    assert "Claude-written synthesis paragraph" in text
