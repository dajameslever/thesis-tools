import json
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


def _calls_matching(mock, marker):
    return [c for c in mock.call_args_list if marker in c.args[1]]


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
    assert call.kwargs["max_tokens"] == 4000  # 1600 * 2.5, room to run long
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
    assert "QUOTE VERBATIM" in system_prompt
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


_EXEC_MARKER = "You write the EXECUTIVE SUMMARY"


def _ask_for_review(exec_text="## The short version\n\n**Answer:** Trust gates adoption (Doe, 2020)."):
    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _STANCE_MARKER in system:
            return "1: supports - confirms it.\n2: challenges - contradicts it."
        if _EXEC_MARKER in system:
            return exec_text
        if _SYNTHESIS_MARKER in system:
            return "A written section citing (Doe, 2020)."
        return "Some prose."

    return _ask


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_executive_summary_is_written_alongside_the_review(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))

    summary = tmp_path / "review.exec-summary.md"
    assert summary.exists()
    text = summary.read_text()
    assert text.startswith("# Executive Summary —")
    assert "Companion to `review.md`" in text
    assert "## The short version" in text
    assert (tmp_path / "review.exec-summary.html").exists()


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_executive_summary_is_built_from_the_drafted_sections(mock_ask, mock_get_client, tmp_path):
    """It must summarize what the review actually says, so it can never claim
    something the review does not."""
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    inputs = _review_inputs(tmp_path, _two_sided_source(tmp_path))
    inputs.sub_questions = ["Does digital transformation reduce environmental impact?", "What limits the effect?"]
    run_literature_review(inputs)

    user_message = _calls_matching(mock_ask, _EXEC_MARKER)[0].args[2]
    assert user_message.count("A written section citing (Doe, 2020).") == 2
    assert "What limits the effect?" in user_message


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_a_failed_summary_is_labelled_a_skeleton(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()

    def _ask(client, system, user, model=None, max_tokens=300, errors=None, **kwargs):
        if _EXEC_MARKER in system:
            if errors is not None:
                errors.append("BadRequestError: prompt is too long")
            return None
        if _STANCE_MARKER in system:
            return "1: supports - confirms it."
        return "A written section."

    mock_ask.side_effect = _ask
    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path)))

    text = (tmp_path / "review.exec-summary.md").read_text()
    assert "skeleton, not a written summary" in text
    assert "BadRequestError: prompt is too long" in text


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_no_exec_summary_skips_it_entirely(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), write_exec_summary=False))

    assert not (tmp_path / "review.exec-summary.md").exists()
    assert not _calls_matching(mock_ask, _EXEC_MARKER)
    assert (tmp_path / "review.md").exists()


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_exec_summary_path_and_length_can_be_forced(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    run_literature_review(
        _review_inputs(
            tmp_path,
            _two_sided_source(tmp_path),
            exec_summary_path=str(tmp_path / "summary" / "brief.md"),
            exec_summary_words=650,
        )
    )

    assert (tmp_path / "summary" / "brief.md").exists()
    assert (tmp_path / "summary" / "brief.html").exists()
    assert "about 650 words" in _calls_matching(mock_ask, _EXEC_MARKER)[0].kwargs["cache_suffix"]


@patch("thesis_tools.llm.get_client")
@patch("thesis_tools.llm.ask")
def test_exec_summary_reuses_the_reviews_citation_markers(mock_ask, mock_get_client, tmp_path):
    """Both documents must cite the same paper the same way, or a reader
    moving between them cannot line them up."""
    mock_get_client.return_value = object()
    mock_ask.side_effect = _ask_for_review()

    run_literature_review(_review_inputs(tmp_path, _two_sided_source(tmp_path), style="ieee"))

    markers = _calls_matching(mock_ask, _SYNTHESIS_MARKER)[0].args[2]
    assert "Cite this paper in-text using exactly: [1]." in markers
    summary_input = _calls_matching(mock_ask, _EXEC_MARKER)[0].args[2]
    assert "A written section citing (Doe, 2020)." in summary_input
