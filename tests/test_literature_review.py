import json
from pathlib import Path
from unittest.mock import patch

import pytest

from thesis_tools.literature_review import (
    MAX_PAPERS_PER_SYNTHESIS_CALL,
    LiteratureReviewInputs,
    _paper_block,
    run_literature_review,
)
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
    assert "## Conclusion and Areas for Further Research" in text
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
    assert "No literature found at all" in text


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


def test_paper_block_includes_verbatim_abstract_and_excerpt():
    paper = Paper(
        title="Sleep Study",
        year=2020,
        authors=["Jane Doe"],
        abstract="We find X.",
        full_text_excerpt="[Page 1]\nIntroduction text.\n\n[Page 2]\nWe find X in more detail here.",
    )
    block = _paper_block(paper, "supports")
    assert '"We find X."' in block
    assert "[Page 2]" in block
    assert "We find X in more detail here." in block
    assert "Doe (2020)" in block


def test_paper_block_flags_when_nothing_available():
    paper = Paper(title="Mystery Paper", authors=["Jane Doe"])
    block = _paper_block(paper, "supports")
    assert "no abstract or text available" in block


def test_paper_block_includes_citation_marker_when_given():
    paper = Paper(title="Sleep Study", year=2020, authors=["Jane Doe"], abstract="We find X.")
    block = _paper_block(paper, "supports", "(Doe, 2020)")
    assert "Cite this paper in-text using exactly: (Doe, 2020)." in block


def test_paper_block_omits_marker_note_when_not_given():
    paper = Paper(title="Sleep Study", year=2020, authors=["Jane Doe"], abstract="We find X.")
    block = _paper_block(paper, "supports")
    assert "Cite this paper in-text" not in block


def test_paper_block_does_not_truncate_full_text_excerpt():
    long_excerpt = "[Page 1]\n" + ("word " * 2000)
    paper = Paper(title="Sleep Study", year=2020, authors=["Jane Doe"], full_text_excerpt=long_excerpt)
    block = _paper_block(paper, "supports")
    assert long_excerpt in block


def test_run_literature_review_reports_full_text_availability(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with_text = Paper(
        title="Indexed Paper",
        year=2021,
        authors=["Jane Doe"],
        doi="10.1/a",
        abstract="We find a significant effect, consistent with theory.",
        full_text_excerpt="[Page 1]\nWe find a significant effect, consistent with theory, in our sample.",
    )
    abstract_only = Paper(
        title="Searched Paper",
        year=2019,
        authors=["Bob Smith"],
        doi="10.1/b",
        abstract="Contrary to expectations, we found no significant effect.",
    )
    index_path = tmp_path / "library" / "index.json"
    index_path.parent.mkdir()
    _write_library_index(index_path, [with_text])
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [abstract_only])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="Psychology",
        working_title="Sleep Study",
        research_question="Does sleep have a significant effect?",
        sub_questions=["Does sleep have a significant effect?"],
        paper_sources=[str(cache_path), str(index_path)],
        output_path=str(output_path),
        use_llm=False,
    )
    run_literature_review(inputs)
    text = output_path.read_text()
    assert "Real text available for quoting:** 1 of 2" in text


@patch("thesis_tools.literature_review.llm.get_client")
@patch("thesis_tools.literature_review.llm.ask")
def test_synthesis_caps_papers_per_call(mock_ask, mock_get_client, tmp_path, monkeypatch):
    mock_get_client.return_value = object()
    mock_ask.return_value = "A synthesis paragraph."

    papers = [
        Paper(
            title=f"Paper {i}",
            year=2020,
            authors=[f"Author{i}"],
            doi=f"10.1/{i}",
            abstract="We find a significant effect, consistent with theory of sleep.",
        )
        for i in range(MAX_PAPERS_PER_SYNTHESIS_CALL + 4)
    ]
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, papers)

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="Sleep",
        research_question="Does sleep have an effect?",
        sub_questions=["Does sleep have an effect?"],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=True,
        min_relevance=0.0,
    )
    run_literature_review(inputs)

    # Only one call per sub-question (plus intro/gaps), and the reference
    # list should be capped, not one entry per paper found.
    call_args = mock_ask.call_args_list
    synthesis_calls = [c for c in call_args if "You write ONE SECTION of a literature review" in c.args[1]]
    assert len(synthesis_calls) == 1
    papers_in_prompt = synthesis_calls[0].args[2].count("- Author")
    assert papers_in_prompt <= MAX_PAPERS_PER_SYNTHESIS_CALL

    text = output_path.read_text()
    cited_count = sum(1 for p in papers if f"10.1/{papers.index(p)}" in text)
    assert cited_count <= MAX_PAPERS_PER_SYNTHESIS_CALL


@patch("thesis_tools.literature_review.llm.get_client")
@patch("thesis_tools.literature_review.llm.ask")
def test_synthesis_prompt_uses_configured_style_citation_marker(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.return_value = "A synthesis paragraph."

    paper = Paper(
        title="Sleep Study",
        year=2020,
        authors=["Jane Doe"],
        doi="10.1/a",
        abstract="We find a significant effect of sleep on decision-making, consistent with theory.",
    )
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [paper])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="Sleep",
        research_question="Does sleep affect decision-making?",
        sub_questions=["Does sleep affect decision-making?"],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=True,
        style="mla",  # no year in-text, unlike the previously-hardcoded (LastName, Year)
        min_relevance=0.0,
    )
    run_literature_review(inputs)

    call_args = mock_ask.call_args_list
    synthesis_calls = [c for c in call_args if "You write ONE SECTION of a literature review" in c.args[1]]
    assert len(synthesis_calls) == 1
    prompt = synthesis_calls[0].args[2]
    assert "Cite this paper in-text using exactly: (Doe)." in prompt


@patch("thesis_tools.literature_review.llm.get_client")
@patch("thesis_tools.literature_review.llm.ask")
def test_ieee_style_numbers_references_by_order_of_first_citation(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.return_value = "A synthesis paragraph."

    first = Paper(
        title="First Paper",
        year=2020,
        authors=["Alice Alpha"],
        doi="10.1/first",
        abstract="We find a significant effect, consistent with theory of sleep.",
    )
    second = Paper(
        title="Second Paper",
        year=2021,
        authors=["Bob Beta"],
        doi="10.1/second",
        abstract="We find a significant effect, consistent with theory of sleep.",
    )
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [first, second])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="Sleep",
        research_question="Does sleep have an effect?",
        sub_questions=["Does sleep have an effect?"],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=True,
        style="ieee",
        min_relevance=0.0,
    )
    run_literature_review(inputs)

    text = output_path.read_text()
    references_section = text.split("## References", 1)[1]
    numbered_lines = [line for line in references_section.splitlines() if line.startswith("[")]
    assert len(numbered_lines) == 2
    assert numbered_lines[0].startswith("[1]") and "First Paper" in numbered_lines[0]
    assert numbered_lines[1].startswith("[2]") and "Second Paper" in numbered_lines[1]


def test_synthesis_selects_papers_from_both_supports_and_challenges_within_cap(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    question = "Does sleep deprivation affect adolescent decision-making?"
    # More supporting papers than the per-call cap, and only one challenger —
    # a straight truncation of supports-then-challenges would drop it entirely.
    supports = [
        Paper(
            title=f"Supporting Paper {i}",
            year=2020,
            authors=[f"Alice Support{i}"],
            doi=f"10.1/s{i}",
            abstract=(
                "We find a significant effect of sleep deprivation on adolescent decision-making, "
                "consistent with prior theory."
            ),
        )
        for i in range(8)
    ]
    challenger = Paper(
        title="Challenging Paper",
        year=2021,
        authors=["Bob Challenger"],
        doi="10.1/c",
        abstract=(
            "Contrary to expectations, we found no significant effect of sleep deprivation on "
            "adolescent decision-making."
        ),
    )
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, supports + [challenger])

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="X",
        working_title="Y",
        research_question=question,
        sub_questions=[question],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=False,
        min_relevance=0.0,
    )
    run_literature_review(inputs)

    text = output_path.read_text()
    assert "(Challenger, 2021)" in text
    support_citations = sum(1 for i in range(8) if f"(Support{i}, 2020)" in text)
    assert 0 < support_citations < 8  # some supporters were left out to make room


def test_run_literature_review_prints_one_llm_notice(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    papers = [
        Paper(title=f"Paper {i}", year=2020, authors=[f"Author{i}"], doi=f"10.1/{i}", abstract="An abstract about sleep and cognition.")
        for i in range(5)
    ]
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, papers)

    output_path = tmp_path / "review.md"
    inputs = LiteratureReviewInputs(
        field="Psychology",
        working_title="Sleep and Cognition",
        research_question="Does sleep affect cognition?",
        sub_questions=["Does sleep affect cognition?"],
        paper_sources=[str(cache_path)],
        output_path=str(output_path),
        use_llm=True,
        min_relevance=0.0,
    )
    run_literature_review(inputs)

    stderr = capsys.readouterr().err
    assert stderr.count("ANTHROPIC_API_KEY not set") == 1
    assert "Claude requested but unavailable" in stderr


def test_papers_matching_only_a_subquestion_are_kept(tmp_path, monkeypatch):
    """The regression: relevance was scored against the research question
    alone, so a paper that was a direct hit on a sub-question — and nothing
    else — got dropped before it was ever classified."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sub_question_match = Paper(
        title="School start times and academic outcomes",
        year=2017,
        authors=["Ada Early"],
        doi="10.1/start",
        abstract="Later start times were significantly associated with better outcomes, consistent with theory.",
    )
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [sub_question_match])

    output_path = tmp_path / "review.md"
    run_literature_review(
        LiteratureReviewInputs(
            field="Psychology",
            working_title="Sleep and decision-making",
            research_question="Does sleep deprivation affect adolescent decision-making?",
            sub_questions=["Do later school start times improve outcomes?"],
            paper_sources=[str(cache_path)],
            output_path=str(output_path),
            use_llm=False,
        )
    )
    text = output_path.read_text()
    assert "Early" in text  # cited, not filtered out
    assert "Drawing on:** 1 of 1 paper(s)" in text


def test_papers_matching_no_question_are_ignored(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    on_topic = Paper(
        title="Sleep deprivation and adolescent decision-making",
        year=2020, authors=["Jane Doe"], doi="10.1/on",
        abstract="We find a significant effect of sleep deprivation on adolescent decision-making, consistent with theory.",
    )
    off_topic = Paper(
        title="Coffee bean price volatility in Brazil",
        year=2018, authors=["Bob Bean"], doi="10.1/off",
        abstract="Coffee prices in Brazil rose sharply following drought conditions.",
    )
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [on_topic, off_topic])

    output_path = tmp_path / "review.md"
    run_literature_review(
        LiteratureReviewInputs(
            field="Psychology",
            working_title="Sleep and decision-making",
            research_question="Does sleep deprivation affect adolescent decision-making?",
            sub_questions=["Does sleep loss increase risk-taking in adolescents?"],
            paper_sources=[str(cache_path)],
            output_path=str(output_path),
            use_llm=False,
        )
    )
    text = output_path.read_text()
    assert "Drawing on:** 1 of 2 paper(s) from 1 source file(s) (1 ignored" in text
    assert "Bean" not in text
    assert "Ignoring 1 of 2 paper(s) that do not match" in capsys.readouterr().err


def test_no_matching_papers_falls_back_loudly(tmp_path, monkeypatch, capsys):
    """An empty draft helps nobody, but silently reviewing the wrong
    literature is worse — the fallback has to be visible in the draft."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    off_topic = Paper(
        title="Coffee bean price volatility in Brazil",
        year=2018, authors=["Bob Bean"], doi="10.1/off",
        abstract="Coffee prices in Brazil rose sharply.",
    )
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [off_topic])

    output_path = tmp_path / "review.md"
    run_literature_review(
        LiteratureReviewInputs(
            field="Psychology",
            working_title="Sleep and decision-making",
            research_question="Does sleep deprivation affect adolescent decision-making?",
            sub_questions=["Does sleep loss increase risk-taking in adolescents?"],
            paper_sources=[str(cache_path)],
            output_path=str(output_path),
            use_llm=False,
        )
    )
    text = output_path.read_text()
    assert "No paper matched your questions" in text
    assert "review of the wrong literature" in text
    assert "drafting from all of them anyway" in capsys.readouterr().err


def test_literature_review_inputs_default_to_the_cheap_classification_tier():
    inputs = LiteratureReviewInputs(
        field="X", working_title="Y", research_question=None, sub_questions=["Q?"], paper_sources=[]
    )
    assert inputs.llm_model == "claude-sonnet-5"          # drafting
    assert inputs.extraction_llm_model == "claude-haiku-4-5"  # classification


# thesis_tools.literature_review.llm and thesis_tools.subquestions.llm are the
# same module object, so patching "llm.ask" through both paths leaves only one
# mock in place. Patch it once and tell the calls apart by their system prompt.
_STANCE_MARKER = "You assess how a paper"
_SYNTHESIS_MARKER = "You write ONE SECTION of a literature review"


_EXEC_MARKER = "You write the EXECUTIVE SUMMARY"
_DETAILED_MARKER = "You write a DETAILED SUMMARY"


def _is_summary_prompt(system):
    """Either summary variant — they are two prompts, and a helper that knows
    only one silently routes the other into the section branch."""
    return _EXEC_MARKER in system or _DETAILED_MARKER in system


def _calls_matching(mock, marker):
    return [c for c in mock.call_args_list if marker in c.args[1]]


def _summary_calls(mock):
    return [c for c in mock.call_args_list if _is_summary_prompt(c.args[1])]


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_classification_uses_the_extraction_model_not_the_drafting_model(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.return_value = "1: supports - confirms it."

    paper = Paper(title="Sleep and decision-making", year=2020, authors=["Jane Doe"], doi="10.1/a",
                  abstract="We find a significant effect of sleep on decision-making.")
    cache_path = tmp_path / "report.md.papers.json"
    _write_topic_cache(cache_path, [paper])

    run_literature_review(
        LiteratureReviewInputs(
            field="X", working_title="Sleep",
            research_question="Does sleep affect decision-making?",
            sub_questions=["Does sleep affect decision-making?"],
            paper_sources=[str(cache_path)],
            output_path=str(tmp_path / "review.md"),
            use_llm=True, min_relevance=0.0,
        )
    )

    stance_calls = _calls_matching(mock_ask, _STANCE_MARKER)
    synthesis_calls = _calls_matching(mock_ask, _SYNTHESIS_MARKER)
    assert stance_calls and synthesis_calls
    assert all(c.kwargs["model"] == "claude-haiku-4-5" for c in stance_calls)
    assert all(c.kwargs["model"] == "claude-sonnet-5" for c in synthesis_calls)


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_classification_reuses_the_stance_cache_across_runs(mock_ask, mock_get_client, tmp_path):
    """Part 3 must not re-pay for a classification visualize-library already
    made against the same paper and the same questions."""
    mock_get_client.return_value = object()
    mock_ask.return_value = "1: supports - confirms it."

    paper = Paper(title="Sleep and decision-making", year=2020, authors=["Jane Doe"], doi="10.1/a",
                  abstract="We find a significant effect of sleep on decision-making.")
    source = tmp_path / "report.md.papers.json"
    _write_topic_cache(source, [paper])
    stance_cache = str(tmp_path / "stance_cache.json")

    def _run():
        run_literature_review(
            LiteratureReviewInputs(
                field="X", working_title="Sleep",
                research_question="Does sleep affect decision-making?",
                sub_questions=["Does sleep affect decision-making?"],
                paper_sources=[str(source)],
                output_path=str(tmp_path / "review.md"),
                use_llm=True, min_relevance=0.0,
                stance_cache_path=stance_cache,
            )
        )

    _run()
    assert len(_calls_matching(mock_ask, _STANCE_MARKER)) == 1
    _run()
    assert len(_calls_matching(mock_ask, _STANCE_MARKER)) == 1  # reused, not re-classified


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_without_a_cache_path_every_run_reclassifies(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.return_value = "1: supports - confirms it."

    paper = Paper(title="Sleep and decision-making", year=2020, authors=["Jane Doe"], doi="10.1/a",
                  abstract="We find a significant effect of sleep on decision-making.")
    source = tmp_path / "report.md.papers.json"
    _write_topic_cache(source, [paper])

    def _run():
        run_literature_review(
            LiteratureReviewInputs(
                field="X", working_title="Sleep",
                research_question="Does sleep affect decision-making?",
                sub_questions=["Does sleep affect decision-making?"],
                paper_sources=[str(source)],
                output_path=str(tmp_path / "review.md"),
                use_llm=True, min_relevance=0.0,
            )
        )

    _run()
    _run()
    assert len(_calls_matching(mock_ask, _STANCE_MARKER)) == 2


# --- prompt budgeting -----------------------------------------------------


def test_fit_paper_texts_leaves_everything_alone_when_it_fits():
    from thesis_tools.literature_review import _fit_paper_texts

    texts = ["a" * 10, "b" * 20]
    fitted, trimmed = _fit_paper_texts(texts, budget=1000)
    assert fitted == texts
    assert trimmed == 0


def test_fit_paper_texts_lets_short_papers_donate_their_unused_share():
    from thesis_tools.literature_review import _fit_paper_texts

    fitted, trimmed = _fit_paper_texts(["a" * 10, "b" * 5000], budget=100)
    assert fitted[0] == "a" * 10  # short paper untouched
    assert len(fitted[1]) == 90  # gets the leftover, not a flat 50
    assert trimmed == 1


def test_fit_paper_texts_never_drops_a_paper_entirely():
    from thesis_tools.literature_review import _fit_paper_texts

    fitted, trimmed = _fit_paper_texts(["x" * 5000] * 4, budget=400)
    assert len(fitted) == 4
    assert all(len(t) > 0 for t in fitted)
    assert sum(len(t) for t in fitted) <= 400
    assert trimmed == 4


# --- a failed section must not masquerade as a written one ----------------


def _two_sided_source(tmp_path):
    supports = Paper(title="Digital transformation reduces environmental impact", year=2023,
                     authors=["Ada Lovelace"], doi="10.1/a",
                     abstract="We find a significant effect of digital transformation on environmental impact, consistent with theory.")
    challenges = Paper(title="No effect of digital transformation on environmental impact", year=2024,
                       authors=["Bob Nul"], doi="10.1/b",
                       abstract="Contrary to expectations, we found no significant effect of digital transformation on environmental impact.")
    path = tmp_path / "src.json"
    _write_topic_cache(path, [supports, challenges])
    return path


def _review_inputs(tmp_path, source, **overrides):
    kwargs = dict(
        field="Digital Transformation",
        working_title="DT and sustainability",
        research_question="Does digital transformation reduce environmental impact?",
        sub_questions=["Does digital transformation reduce environmental impact?"],
        paper_sources=[str(source)],
        output_path=str(tmp_path / "review.md"),
        use_llm=True,
        min_relevance=0.0,
    )
    kwargs.update(overrides)
    return LiteratureReviewInputs(**kwargs)


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_failed_section_is_flagged_in_the_section_and_the_header(mock_ask, mock_get_client, tmp_path):
    """The reported bug: every synthesis call failed, each section silently
    became a bullet dump, and the header still said "Claude-written prose"."""
    mock_get_client.return_value = object()

    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _SYNTHESIS_MARKER in system:
            if errors is not None:
                errors.append("BadRequestError: prompt is too long")
            return None
        if _STANCE_MARKER in system:
            return "1: supports - confirms it."
        return "Some prose."

    mock_ask.side_effect = _ask
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))

    text = (tmp_path / "review.md").read_text()
    assert "Claude-written prose, targeting" not in text
    assert "partially failed" in text
    assert "This section is a fallback outline, not a written review" in text
    assert "BadRequestError: prompt is too long" in text


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_successful_sections_report_the_target_length(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), words_per_question=1500))

    text = (tmp_path / "review.md").read_text()
    assert "Claude-written prose, targeting ~1500 words per sub-question" in text
    assert "partially failed" not in text
    assert "fallback outline" not in text


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_explicit_words_per_question_overrides_the_scaling(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), words_per_question=1600))

    call = _calls_matching(mock_ask, _SYNTHESIS_MARKER)[0]
    assert "about 1600 words" in call.kwargs["cache_suffix"]
    # Room to run long: a word count is a target, not a cap, and being cut
    # off mid-section is worse than an unused allowance (which costs nothing,
    # since output is billed on what comes back).
    from thesis_tools.exec_summary import max_tokens_for

    assert call.kwargs["max_tokens"] == max_tokens_for(1600)
    assert call.kwargs["max_tokens"] > 1600 * 1.4  # comfortably past the ask
    assert "targeting ~1600 words" in (tmp_path / "review.md").read_text()


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_section_length_scales_to_the_evidence_behind_the_question(mock_ask, mock_get_client, tmp_path):
    """Limited sources, limited summary — two papers must not be asked to
    carry the same word count as a dozen."""
    from thesis_tools.literature_review import target_words_for

    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))

    call = _calls_matching(mock_ask, _SYNTHESIS_MARKER)[0]
    assert f"about {target_words_for(2)} words" in call.kwargs["cache_suffix"]
    assert "scaled to its evidence" in (tmp_path / "review.md").read_text()


def test_target_words_scales_with_sources_within_bounds():
    from thesis_tools.literature_review import (
        MAX_WORDS_PER_QUESTION,
        MIN_WORDS_PER_QUESTION,
        target_words_for,
    )

    assert target_words_for(1) == MIN_WORDS_PER_QUESTION       # floored
    assert target_words_for(100) == MAX_WORDS_PER_QUESTION     # capped
    assert target_words_for(3) < target_words_for(8)           # monotonic
    # "A lot of papers" should land in the range the user asked for.
    assert 1000 <= target_words_for(8) <= 2000
    assert 1000 <= target_words_for(14) <= 2000


def test_enough_sources_are_available_to_reach_the_upper_range():
    from thesis_tools.literature_review import (
        MAX_PAPERS_PER_SYNTHESIS_CALL,
        MAX_WORDS_PER_QUESTION,
        target_words_for,
    )

    assert target_words_for(MAX_PAPERS_PER_SYNTHESIS_CALL) == MAX_WORDS_PER_QUESTION


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_sections_paraphrase_rather_than_quote_by_default(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))

    system_prompt = _calls_matching(mock_ask, _SYNTHESIS_MARKER)[0].args[1]
    assert "PARAPHRASE THROUGHOUT" in system_prompt
    assert "QUOTE VERBATIM" not in system_prompt
    assert "CONDENSE" in system_prompt


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_allow_quotes_restores_the_verbatim_quoting_rules(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), allow_quotes=True))

    calls = _calls_matching(mock_ask, _SYNTHESIS_MARKER)
    system_prompt, user_message = calls[0].args[1], calls[0].args[2]
    assert "QUOTE ACCURATELY" in system_prompt
    assert "PARAPHRASE THROUGHOUT" not in system_prompt
    assert "Abstract (verbatim)" in user_message


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_paper_blocks_ask_for_understanding_not_quotation_by_default(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )
    paper = Paper(
        title="Digital transformation reduces environmental impact", year=2023, authors=["Ada Lovelace"],
        doi="10.1/a", full_text_excerpt="[Page 1]\nWe find a significant effect on environmental impact.",
    )
    source = tmp_path / "src.json"
    _write_topic_cache(source, [paper])
    run_literature_review(_review_inputs(tmp_path, source))

    user_message = _calls_matching(mock_ask, _SYNTHESIS_MARKER)[0].args[2]
    assert "put it in your own words" in user_message
    assert "quote this exact wording only" not in user_message


def test_heuristic_fallback_summarises_rather_than_dumping_the_title_page(tmp_path, monkeypatch):
    """A locally indexed PDF's first 220 characters are the title page and
    author affiliations, which is what the reported draft was full of."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    paper = Paper(
        title="Sustainable accounting in the digital age", year=2026, authors=["Hamood Al-Hattami"], doi="10.1/a",
        full_text_excerpt=(
            "[Page 1]\nSustainable accounting in the digital age: Integrating technology for a greener future\n"
            "Hamood Mohammed Al-Hattami a,b,*\na College of Business Administration, A'Sharqiyah University, Ibra, Oman\n"
            "This study finds a significant effect of digital transformation on environmental impact, consistent with theory."
        ),
    )
    source = tmp_path / "src.json"
    _write_topic_cache(source, [paper])
    run_literature_review(
        _review_inputs(tmp_path, source, use_llm=False,
                       sub_questions=["Does digital transformation reduce environmental impact?"])
    )
    text = (tmp_path / "review.md").read_text()
    assert "College of Business Administration" not in text
    assert "significant effect of digital transformation" in text


# --- HTML companion -------------------------------------------------------


def test_html_version_is_written_alongside_the_markdown(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), use_llm=False))

    html_path = tmp_path / "review.html"
    assert html_path.is_file()
    html = html_path.read_text()
    assert "<!doctype html>" in html
    assert "Literature Review" in html
    assert "Contents" in html  # navigation for a long draft


def test_no_html_writes_only_markdown(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), use_llm=False, write_html=False))
    assert (tmp_path / "review.md").is_file()
    assert not (tmp_path / "review.html").exists()


def test_html_output_path_can_be_redirected(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    target = tmp_path / "elsewhere" / "review.html"
    run_literature_review(
        _review_inputs(tmp_path, _two_sided_source(tmp_path), use_llm=False, html_output_path=str(target))
    )
    assert target.is_file()
    assert not (tmp_path / "review.html").exists()


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_synthesis_system_prompt_is_identical_across_sections(mock_ask, mock_get_client, tmp_path):
    """Caching is a prefix match, so anything that varies per section is a
    silent invalidator. The target word count used to be interpolated into
    this prompt; it belongs in the suffix, past the breakpoint."""
    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it.\n2: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )
    inputs = _review_inputs(tmp_path, _two_sided_source(tmp_path))
    inputs.sub_questions = [
        "Does digital transformation reduce environmental impact?",
        "What limits the effect of digital transformation?",
    ]
    run_literature_review(inputs)

    calls = _calls_matching(mock_ask, _SYNTHESIS_MARKER)
    assert len(calls) == 2
    assert calls[0].args[1] == calls[1].args[1]
    # ...and the per-section bits really are past the breakpoint.
    assert "words" not in calls[0].args[1].split("A target length is given")[0]
    assert calls[0].kwargs["cache_suffix"] != calls[1].kwargs["cache_suffix"]


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_synthesis_requests_caching_by_default_and_not_when_disabled(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = lambda c, system, u, model=None, max_tokens=300, errors=None, **kwargs: (
        "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."
    )

    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))
    assert _calls_matching(mock_ask, _SYNTHESIS_MARKER)[0].kwargs["cache"] is True

    mock_ask.reset_mock()
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), use_prompt_cache=False))
    assert _calls_matching(mock_ask, _SYNTHESIS_MARKER)[0].kwargs["cache"] is False


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_run_reports_what_the_drafting_calls_actually_cost(mock_ask, mock_get_client, tmp_path, capsys):
    """A cache that never reads is overhead paid for nothing — the run has to
    surface the counters, not just hope."""
    mock_get_client.return_value = object()

    def _ask(client, system, user, model=None, max_tokens=300, errors=None, usage_totals=None, **kwargs):
        if usage_totals is not None:
            usage_totals["input_tokens"] = usage_totals.get("input_tokens", 0) + 1000
            usage_totals["cache_read_input_tokens"] = usage_totals.get("cache_read_input_tokens", 0) + 40000
        return "1: supports - confirms it." if _STANCE_MARKER in system else "A written section."

    mock_ask.side_effect = _ask
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))

    err = capsys.readouterr().err
    assert "cache-read" in err
    assert "nothing was read from the prompt cache" not in err


def _ask_for_review(exec_text="## The short version\n\n**Answer:** Trust gates adoption (Doe, 2020)."):
    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _STANCE_MARKER in system:
            return "1: supports - confirms it.\n2: challenges - contradicts it."
        if _is_summary_prompt(system):
            return exec_text
        if _SYNTHESIS_MARKER in system:
            return "A written section citing (Doe, 2020)."
        return "Some prose."

    return _ask


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_a_run_produces_the_review_and_nothing_else_by_default(mock_ask, mock_get_client, tmp_path):
    """One run, one deliverable — the review and the summary are two
    presentations of the same evidence, and writing both just leaves the
    reader deciding which to open."""
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    path = run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))

    assert Path(path) == tmp_path / "review.md"
    assert (tmp_path / "review.html").exists()
    assert not _summary_calls(mock_ask)  # not even drafted
    assert not list(tmp_path.glob("*exec-summary*"))


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_summary_output_type_writes_the_summary_and_not_the_review(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    path = run_literature_review(
        _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="summary")
    )

    text = Path(path).read_text()
    assert text.startswith("# Executive Summary —")
    assert "## The short version" in text
    # The review's own shape must not leak into it.
    assert "## References" not in text
    assert "## Conclusion and Areas for Further Research" not in text
    assert (tmp_path / "review.html").exists()  # the chosen output, as HTML


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_the_summary_says_what_it_was_drafted_from(mock_ask, mock_get_client, tmp_path):
    """Standalone, it cannot point at a review sitting next to it — the
    reader still needs to know how much evidence is behind it."""
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    path = run_literature_review(
        _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="summary")
    )
    text = Path(path).read_text()

    assert "source(s) cited across" in text
    assert "AI-assisted DRAFT" in text  # same caution the review carries


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_summary_is_built_from_the_drafted_sections(mock_ask, mock_get_client, tmp_path):
    """It must summarize what the review would have said, so it can never
    claim something the sources do not support."""
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    inputs = _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="summary")
    inputs.sub_questions = ["Does digital transformation reduce environmental impact?", "What limits the effect?"]
    run_literature_review(inputs)

    user_message = _summary_calls(mock_ask)[0].args[2]
    assert user_message.count("A written section citing (Doe, 2020).") == 2
    assert "What limits the effect?" in user_message


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_a_failed_summary_is_labelled_a_skeleton(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()

    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _is_summary_prompt(system):
            if errors is not None:
                errors.append("BadRequestError: prompt is too long")
            return None
        if _STANCE_MARKER in system:
            return "1: supports - confirms it."
        return "A written section."

    mock_ask.side_effect = _ask
    path = run_literature_review(
        _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="summary")
    )

    text = Path(path).read_text()
    assert "skeleton, not a written summary" in text
    assert "BadRequestError: prompt is too long" in text


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_a_summary_over_failed_sections_says_so(mock_ask, mock_get_client, tmp_path):
    """A section that fell back to a bullet outline is upstream of the whole
    summary. The review flags it on the section itself; a standalone summary
    has no section to flag it on, so the header is the only place a reader
    could ever learn it."""
    mock_get_client.return_value = object()

    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _SYNTHESIS_MARKER in system:
            if errors is not None:
                errors.append("BadRequestError: prompt is too long")
            return None
        if _STANCE_MARKER in system:
            return "1: supports - confirms it."
        if _is_summary_prompt(system):
            return "## The short version\n\n**Answer:** Something."
        return "Some prose."

    mock_ask.side_effect = _ask
    path = run_literature_review(
        _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="summary")
    )

    text = Path(path).read_text()
    assert "Written from a partly failed review" in text
    assert "BadRequestError: prompt is too long" in text


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_summary_length_can_be_forced(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    run_literature_review(
        _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="summary", summary_words=650)
    )

    assert "about 650 words" in _summary_calls(mock_ask)[0].kwargs["cache_suffix"]


def test_an_unknown_output_type_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Unknown output type"):
        run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="deck"))


def test_default_output_paths_are_named_for_what_they_are():
    from thesis_tools.literature_review import _default_output_path

    assert _default_output_path("review").name.startswith("literature-review-")
    assert _default_output_path("summary").name.startswith("executive-summary-")


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_detailed_output_type_writes_a_detailed_summary(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review(
        exec_text="## What this evidence base looks like\n\nSmall and recent (Doe, 2020)."
    )

    path = run_literature_review(
        _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="detailed")
    )

    text = Path(path).read_text()
    assert text.startswith("# Detailed Summary —")
    assert "# Executive Summary" not in text
    assert "## References" not in text  # not the review's shape either


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_the_three_output_types_produce_three_different_documents(mock_ask, mock_get_client, tmp_path):
    """Same evidence, same pipeline underneath — the only difference is what
    the last call is asked for."""
    mock_get_client.return_value = object()
    written = {}
    for output_type in ("review", "summary", "detailed"):
        mock_ask.side_effect = _ask_for_review()
        path = run_literature_review(
            _review_inputs(
                tmp_path,
                _two_sided_source(tmp_path),
                output_type=output_type,
                output_path=str(tmp_path / f"{output_type}.md"),
            )
        )
        written[output_type] = Path(path).read_text()

    assert len({v[:40] for v in written.values()}) == 3
    assert written["review"].startswith("# Literature Review")
    assert written["summary"].startswith("# Executive Summary")
    assert written["detailed"].startswith("# Detailed Summary")


def test_detailed_summaries_get_their_own_default_filename():
    from thesis_tools.literature_review import _default_output_path

    assert _default_output_path("detailed").name.startswith("detailed-summary-")


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_reusing_the_same_output_path_keeps_the_earlier_draft(mock_ask, mock_get_client, tmp_path):
    """Everything under output/ is a document produced at a moment in time —
    you will want today's against last week's. Default names carry a
    timestamp and accumulate on their own; an explicit -o names one fixed
    file, and that is the case that needs help."""
    mock_get_client.return_value = object()

    for run in range(3):
        mock_ask.side_effect = _ask_for_review()
        run_literature_review(
            _review_inputs(tmp_path, _two_sided_source(tmp_path), output_path=str(tmp_path / "draft.md"))
        )

    kept = sorted(p.name for p in (tmp_path / "previous").iterdir())
    assert len(kept) == 4  # two earlier runs, each as .md and .html
    assert all(name.startswith("draft-") for name in kept)
    assert sum(name.endswith(".html") for name in kept) == 2
    assert (tmp_path / "draft.md").is_file()  # the path you named still points at the newest


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_default_timestamped_names_never_collide_in_the_first_place(mock_ask, mock_get_client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    inputs = _review_inputs(tmp_path, _two_sided_source(tmp_path))
    inputs.output_path = None
    path = Path(run_literature_review(inputs))

    assert path.parent.name == "output"
    assert not (path.parent / "previous").exists()


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_an_incomplete_summary_says_so_in_the_document(mock_ask, mock_get_client, tmp_path):
    """The reported bug, end to end: a two-paragraph file was written as
    though it were the finished deliverable."""
    mock_get_client.return_value = object()

    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _STANCE_MARKER in system:
            return "1: supports - confirms it."
        if _is_summary_prompt(system):
            return "## What this evidence base looks like\n\nThe review draws on 34 papers.\n\n## 1."
        return "A written section citing (Doe, 2020)."

    mock_ask.side_effect = _ask
    inputs = _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="detailed")
    inputs.sub_questions = ["Does digital transformation reduce impact?", "What limits the effect?"]
    path = run_literature_review(inputs)

    text = Path(path).read_text()
    assert "This summary is incomplete" in text
    assert "never written" in text
    # It is not the skeleton — a real, partial document came back.
    assert "skeleton, not a written summary" not in text


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_a_complete_summary_carries_no_warning(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    questions = ["Does digital transformation reduce impact?", "What limits the effect?"]
    complete = (
        "## What this evidence base looks like\n\nShape.\n\n"
        f"## 1. {questions[0]}\n\nProse (Doe, 2020).\n\n"
        f"## 2. {questions[1]}\n\nProse (Doe, 2020).\n\n"
        "## Across the questions\n\nPattern.\n\n"
        "## Where this leaves the thesis\n\n- Act on it."
    )

    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _STANCE_MARKER in system:
            return "1: supports - confirms it."
        if _is_summary_prompt(system):
            return complete
        return "A written section citing (Doe, 2020)."

    mock_ask.side_effect = _ask
    inputs = _review_inputs(tmp_path, _two_sided_source(tmp_path), output_type="detailed")
    inputs.sub_questions = questions
    text = Path(run_literature_review(inputs)).read_text()

    assert "incomplete" not in text
    assert "Where this leaves the thesis" in text


# --- alignment with the taught marking criteria ---------------------------
# Each of these pins one requirement from the university's dissertation
# bootcamp material. They are deliberately about the PROMPT rather than the
# output: the prompt is the only place the toolkit can enforce them, and an
# edit that quietly drops one would otherwise pass every other test.


def test_the_review_is_organised_by_theme_not_by_source():
    """"Not a descriptive list of the material available, or a set of
    summaries" — the difference between a review and an annotated
    bibliography."""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "SYNTHESIZE, don't summarize source-by-source" in prompt
    assert "laundry list" in prompt
    assert "never one paper after another" in prompt


def test_sections_must_appraise_the_evidence_not_just_report_it():
    """"Critically appraise strengths and weaknesses" — the Evaluate step of
    Describe / Interpret / Evaluate / Synthesise, which is the one most
    drafts skip."""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "APPRAISE THE EVIDENCE" in prompt
    for critical_lens_question in ("sample", "bias", "assumption", "dated", "outruns the evidence"):
        assert critical_lens_question in prompt, critical_lens_question
    # And balance: "Keep a balanced perspective ... the strengths that you can
    # build on as well as any problems or gaps."
    assert "strength as readily as a weakness" in prompt


def test_disagreements_must_be_explained_not_merely_noted():
    """"Contradictory findings — do not simply note differences; you need to
    explain them.\""""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "EXPLAIN THE DISAGREEMENT" in prompt
    assert "do not merely note that it exists" in prompt
    assert "ACCOUNT for the difference" in prompt


def test_sections_must_draw_out_implications():
    """"So what? — Draw out implications of your discussions.\""""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "SO WHAT" in prompt
    assert "the student's own research" in prompt


def test_definitions_and_theoretical_framing_are_expected():
    """Expected content includes "definitions and discussion of terminology"
    and theoretical underpinnings, in summary at MA/MSc level."""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "DEFINITIONS AND FRAMEWORKS" in prompt
    assert "theoretical" in prompt
    assert "not an exposition of them" in prompt  # summary depth, not PhD depth


def test_the_introduction_states_the_guiding_concept_and_signposts():
    """A review "must be defined by a guiding concept", and the reader needs
    "adequate signposting" of how it is organised."""
    from thesis_tools.literature_review import _INTRO_SYSTEM_PROMPT as prompt

    assert "GUIDING CONCEPT" in prompt
    assert "SIGNPOST" in prompt
    assert "no citations" in prompt.lower()


def test_the_conclusion_uses_the_gap_to_justify_the_students_own_work():
    """"Signalling a gap in previous research and using this to justify your
    own" — the gap is the warrant for the contribution, not a remark about
    other people's work."""
    from thesis_tools.literature_review import _CONCLUSION_SYSTEM_PROMPT as prompt

    assert "JUSTIFY THE STUDENT'S OWN RESEARCH" in prompt
    assert "warrant for their contribution" in prompt
    assert "reiterate concisely" in prompt  # "a summary where the key arguments are reiterated"


def test_the_executive_summary_is_left_out_of_this():
    """The taught criteria are for the review chapter. The summaries answer a
    different question for a different reader and must not inherit rules
    written for a marked dissertation chapter."""
    from thesis_tools.exec_summary import _DETAILED_SYSTEM_PROMPT, _EXEC_SYSTEM_PROMPT

    for prompt in (_EXEC_SYSTEM_PROMPT, _DETAILED_SYSTEM_PROMPT):
        assert "APPRAISE THE EVIDENCE" not in prompt
        assert "GUIDING CONCEPT" not in prompt


def test_paraphrase_means_restructuring_not_swapping_synonyms():
    """The taught guidance's worked example of a failed paraphrase keeps the
    source's sentence intact and substitutes synonyms into it — which is also
    what a language model does by default when told to use its own words."""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "SWAPPING WORDS IS NOT PARAPHRASING" in prompt
    assert "Change the STRUCTURE, not just the vocabulary" in prompt
    assert "a different order" in prompt
    assert "could be found in the source unchanged, rewrite it" in prompt


def test_a_paraphrase_is_attributed_as_firmly_as_a_quotation():
    """"Make it clear where a paraphrase begins and ends, and which parts of
    the material are not your own ideas.\""""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "MAKE THE BOUNDARY VISIBLE" in prompt
    assert "a paraphrase needs its reference exactly as much as a quotation does" in prompt


def test_paraphrasing_may_not_shift_the_meaning():
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt()
    assert "KEEP THE MEANING" in prompt
    assert "A hedge in the original stays a hedge" in prompt


def test_a_quotation_must_have_one_of_the_four_named_reasons():
    """"When you do quote, the important thing to consider is why you are
    using a quote" — authorial voice, definition, clarity of position, or
    opening/closing a passage."""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt(allow_quotes=True)
    for reason in ("AUTHORIAL VOICE", "DEFINITION", "POSITION", "opening or closing"):
        assert reason in prompt, reason
    assert "'It saves me summarising it' is not one of them" in prompt


def test_quotations_may_be_fitted_with_ellipses_and_brackets():
    """The two accepted devices for integrating a quotation — and the Oxford
    exemplar uses both. Forbidding them would push the model toward dropping
    in whole sentences instead."""
    from thesis_tools.literature_review import _synthesis_system_prompt

    prompt = _synthesis_system_prompt(allow_quotes=True)
    assert "ellipsis" in prompt and "square brackets" in prompt
    assert "Neither may change what the author meant" in prompt
    assert "never a passage dropped in whole" in prompt


def test_paraphrase_rules_are_absent_when_quoting_is_allowed_and_vice_versa():
    from thesis_tools.literature_review import _synthesis_system_prompt

    assert "QUOTE ACCURATELY" not in _synthesis_system_prompt()
    assert "SWAPPING WORDS IS NOT PARAPHRASING" not in _synthesis_system_prompt(allow_quotes=True)
