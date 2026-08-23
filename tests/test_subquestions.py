from unittest.mock import patch

from thesis_tools.sources.base import Paper
from thesis_tools.subquestions import (
    StanceResult,
    _heuristic_stance,
    analyze_subquestions,
    generate_subquestions,
)


def test_heuristic_stance_detects_support():
    abstract = "We find a significant effect of sleep deprivation on adolescent decision-making, consistent with prior theory."
    result = _heuristic_stance(abstract, "Does sleep deprivation affect adolescent decision-making?")
    assert result.stance == "supports"


def test_heuristic_stance_detects_challenge():
    abstract = "Contrary to expectations, we found no significant effect of sleep deprivation on adolescent decision-making."
    result = _heuristic_stance(abstract, "Does sleep deprivation affect adolescent decision-making?")
    assert result.stance == "challenges"


def test_heuristic_stance_unrelated_when_no_topical_overlap():
    abstract = "This paper studies coffee bean prices in Brazil over the last decade."
    result = _heuristic_stance(abstract, "Does sleep deprivation affect adolescent decision-making?")
    assert result.stance == "unrelated"


def test_heuristic_stance_none_abstract():
    assert _heuristic_stance(None, "Does X affect Y?").stance == "unrelated"


def test_heuristic_stance_mixed_when_both_cues_present():
    abstract = (
        "Sleep deprivation and adolescent decision-making: results were consistent with theory in the "
        "risk-taking task, but contrary to expectations, no significant effect was found on the reward task."
    )
    result = _heuristic_stance(abstract, "Does sleep deprivation affect adolescent decision-making?")
    assert result.stance == "mixed"


def test_heuristic_stance_negated_support_phrase_reads_as_challenge():
    # "no significant effect" must not also register as the "significant effect" support cue.
    abstract = "We found no significant effect of sleep deprivation on adolescent decision-making."
    result = _heuristic_stance(abstract, "Does sleep deprivation affect adolescent decision-making?")
    assert result.stance == "challenges"


def test_generate_subquestions_returns_empty_without_llm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert generate_subquestions("Sleep deprivation and adolescent decision-making") == []


def test_analyze_subquestions_empty_when_no_subquestions():
    papers = [Paper(title="A Paper", abstract="Some abstract.")]
    analysis = analyze_subquestions([], papers)
    assert analysis.sub_questions == []
    assert analysis.stances == {}


def test_analyze_subquestions_heuristic_path_and_tensions():
    supports_paper = Paper(
        title="Study A",
        doi="10.1/a",
        abstract="We find a significant effect of sleep deprivation on adolescent decision-making, consistent with theory.",
    )
    challenges_paper = Paper(
        title="Study B",
        doi="10.1/b",
        abstract="Contrary to expectations, we found no significant effect of sleep deprivation on adolescent decision-making.",
    )
    unrelated_paper = Paper(title="Study C", doi="10.1/c", abstract="Coffee prices rose sharply in 2020.")

    question = "Does sleep deprivation affect adolescent decision-making?"
    analysis = analyze_subquestions([question], [supports_paper, challenges_paper, unrelated_paper], use_llm=False)

    grouped = analysis.titles_by_stance(question)
    assert "Study A" in grouped["supports"]
    assert "Study B" in grouped["challenges"]
    assert "Study C" not in grouped["supports"] and "Study C" not in grouped["challenges"]

    tensions = analysis.tensions()
    assert question in tensions
    assert "Study A" in tensions[question]["supports"]
    assert "Study B" in tensions[question]["challenges"]


def test_analysis_keys_by_doi_not_title_to_avoid_collisions():
    # Two distinct papers that happen to share a title but have different DOIs.
    paper_a = Paper(title="Same Title", doi="10.1/a", abstract="Significant effect found, consistent with theory of X.")
    paper_b = Paper(title="Same Title", doi="10.1/b", abstract="Coffee prices in Brazil.")
    question = "Does X happen?"
    analysis = analyze_subquestions([question], [paper_a, paper_b], use_llm=False)
    assert len(analysis.stances) == 2


@patch("thesis_tools.subquestions.llm.get_client")
@patch("thesis_tools.subquestions.llm.ask")
def test_analyze_subquestions_uses_llm_when_available(mock_ask, mock_get_client):
    mock_get_client.return_value = object()  # any non-None sentinel
    mock_ask.return_value = "1: supports - the abstract directly confirms this."
    paper = Paper(title="Study A", doi="10.1/a", abstract="Some abstract text.")
    question = "Does sleep deprivation affect adolescent decision-making?"

    analysis = analyze_subquestions([question], [paper], use_llm=True)
    stance = analysis.stances_for(paper)[question]
    assert stance.stance == "supports"
    assert "confirms" in stance.rationale


@patch("thesis_tools.subquestions.llm.get_client")
def test_analyze_subquestions_falls_back_to_heuristic_if_llm_unavailable(mock_get_client):
    mock_get_client.return_value = None
    paper = Paper(
        title="Study A",
        doi="10.1/a",
        abstract="We find a significant effect of sleep deprivation on adolescent decision-making, consistent with theory.",
    )
    question = "Does sleep deprivation affect adolescent decision-making?"
    analysis = analyze_subquestions([question], [paper], use_llm=True)
    assert analysis.stances_for(paper)[question].stance == "supports"


def test_analyze_subquestions_uses_full_text_excerpt_when_no_abstract():
    """The reported bug: a paper with real extracted text but no abstract
    (the normal case for Part 2's locally-indexed PDFs) was being silently
    treated as unrelated to every sub-question, because both the heuristic
    and LLM stance paths only ever looked at paper.abstract."""
    question = "Does sleep deprivation affect adolescent decision-making?"
    paper = Paper(
        title="A Paper",
        abstract=None,
        full_text_excerpt=(
            "[Page 1]\nWe find a significant effect of sleep deprivation on adolescent "
            "decision-making, consistent with prior theory."
        ),
    )
    analysis = analyze_subquestions([question], [paper], use_llm=False)
    assert analysis.stances_for(paper)[question].stance == "supports"


def test_heuristic_stance_unrelated_with_neither_abstract_nor_excerpt():
    assert _heuristic_stance(None, "Does X affect Y?").stance == "unrelated"


@patch("thesis_tools.subquestions.llm.get_client")
@patch("thesis_tools.subquestions.llm.ask")
def test_analyze_subquestions_prints_progress_with_llm(mock_ask, mock_get_client, capsys):
    mock_get_client.return_value = object()
    mock_ask.return_value = "1: supports - confirms it."
    paper = Paper(title="Study A", doi="10.1/a", abstract="Some abstract text.")
    question = "Does sleep deprivation affect adolescent decision-making?"

    analyze_subquestions([question], [paper], use_llm=True)

    err = capsys.readouterr().err
    assert "Classifying 1 paper(s) against 1 sub-question(s) with Claude" in err
    assert "[1/1] Study A" in err


def test_analyze_subquestions_silent_without_llm(capsys):
    paper = Paper(title="Study A", doi="10.1/a", abstract="Some abstract text.")
    question = "Does sleep deprivation affect adolescent decision-making?"

    analyze_subquestions([question], [paper], use_llm=False)

    assert capsys.readouterr().err == ""
