from unittest.mock import patch

from thesis_tools.exec_summary import (
    MAX_SECTION_CHARS,
    _cites,
    _fit_sections,
    _with_references,
    build_exec_summary,
    target_words_for,
)
from thesis_tools.sources.base import Paper

_MARKER = "You write the EXECUTIVE SUMMARY"


def _paper(surname="Lovelace", year=2024, doi="10.1/a", title="Trust in AI travel tools"):
    return Paper(title=title, authors=[f"Ada {surname}"], year=year, doi=doi)


def _kwargs(**overrides):
    papers = [_paper(), _paper("Hopper", 2025, "10.1/b", "Disintermediation of OTAs")]
    kwargs = dict(
        research_question="How does AI adoption affect travel intermediaries?",
        field="tourism management",
        sections=[("How do travellers use AI?", "Lovelace (2024) reports X.")],
        tensions=[],
        no_coverage=[],
        cited_papers=papers,
        markers_by_key={p.key(): f"({p.authors[0].split()[-1]}, {p.year})" for p in papers},
        style="apa",
        client=object(),
        model="claude-sonnet-5",
        relevant_paper_count=2,
    )
    kwargs.update(overrides)
    return kwargs


def test_target_length_scales_with_the_sources_cited():
    from thesis_tools.exec_summary import MAX_WORDS, MIN_WORDS

    assert target_words_for(1) == MIN_WORDS
    assert target_words_for(100) == MAX_WORDS
    assert target_words_for(4) < target_words_for(12)


@patch("thesis_tools.llm.ask")
def test_prompt_asks_for_the_pyramid_structure_and_the_debate(mock_ask):
    """The whole point of the second output: answer first, themes across the
    sub-questions, and the disagreements stated rather than averaged away."""
    mock_ask.return_value = "## The short version\n\n**Answer:** X."
    build_exec_summary(**_kwargs())

    system = mock_ask.call_args.args[1]
    for required in (
        "## The short version",
        "**Situation:**",
        "**Answer:**",
        "## What the evidence shows",
        "## Where the literature disagrees",
        "## Worth calling out",
        "## What this means for the thesis",
        "[Evidence]",
        "[Contested]",
        "[Gap]",
    ):
        assert required in system, required


@patch("thesis_tools.llm.ask")
def test_sections_are_sent_and_the_word_target_stays_out_of_the_cached_prefix(mock_ask):
    mock_ask.return_value = "## The short version"
    build_exec_summary(**_kwargs(sections=[("Q1", "Body of section one."), ("Q2", "Body of section two.")]))

    user_message = mock_ask.call_args.args[2]
    assert "Body of section one." in user_message and "Body of section two." in user_message
    assert "words" not in user_message  # the varying target lives past the breakpoint
    assert "about" in mock_ask.call_args.kwargs["cache_suffix"]
    assert mock_ask.call_args.kwargs["cache"] is True


@patch("thesis_tools.llm.ask")
def test_contested_and_uncovered_questions_are_handed_to_the_model(mock_ask):
    mock_ask.return_value = "## The short version"
    build_exec_summary(**_kwargs(tensions=["Does AI displace OTAs?"], no_coverage=["What about rail?"]))

    user_message = mock_ask.call_args.args[2]
    assert "Does AI displace OTAs?" in user_message
    assert "What about rail?" in user_message


@patch("thesis_tools.llm.ask")
def test_failure_is_reported_and_falls_back_to_a_labelled_skeleton(mock_ask):
    """Same rule as the review itself: a skeleton nobody wrote must never be
    shipped silently under the same title as a written summary."""
    def _fail(client, system, user, errors=None, **kwargs):
        errors.append("BadRequestError: prompt is too long")
        return None

    mock_ask.side_effect = _fail
    text, failure = build_exec_summary(**_kwargs(tensions=["Does AI displace OTAs?"]))

    assert failure == "BadRequestError: prompt is too long"
    assert "Not written" in text
    assert "Does AI displace OTAs?" in text


def test_no_client_produces_the_skeleton_without_claiming_a_failure():
    text, failure = build_exec_summary(**_kwargs(client=None))
    assert failure is None
    assert "## The short version" in text


def test_empty_review_is_not_summarized():
    text, failure = build_exec_summary(**_kwargs(sections=[("Q", "   ")]))
    assert failure == "the review produced no sections"
    assert "nothing to summarize" in text


def test_reference_list_covers_only_what_the_summary_cites():
    papers = [_paper(), _paper("Hopper", 2025, "10.1/b", "Disintermediation of OTAs")]
    markers = {p.key(): f"({p.authors[0].split()[-1]}, {p.year})" for p in papers}
    text = "Only one of these is mentioned: (Lovelace, 2024)."

    out = _with_references(text, papers, markers, "apa")
    assert "Trust in AI travel tools" in out
    assert "Disintermediation of OTAs" not in out


def test_merged_citations_still_resolve_to_their_papers():
    """Prose merges citations — '(Hopper, 2025; Turing, 2025)' contains
    neither marker as a substring, and dropping both from the reference list
    would leave the summary citing works it does not list."""
    text = "The displacement claim is contested (Hopper, 2025; Turing, 2025)."
    assert _cites(text, _paper("Hopper", 2025), "(Hopper, 2025)", "apa")
    assert _cites(text, _paper("Turing", 2025), "(Turing, 2025)", "apa")
    assert not _cites(text, _paper("Babbage", 2025), "(Babbage, 2025)", "apa")


def test_ieee_runs_still_resolve_to_their_papers():
    text = "as several report [3], [4]."
    assert _cites(text, _paper(), "[3]", "ieee")
    assert _cites(text, _paper(), "[4]", "ieee")
    assert not _cites(text, _paper(), "[9]", "ieee")


def test_references_are_ordered_by_surname_not_given_name():
    papers = [_paper("Lovelace", 2024, "10.1/a", "A"), _paper("Hopper", 2025, "10.1/b", "B")]
    markers = {p.key(): f"({p.authors[0].split()[-1]}, {p.year})" for p in papers}
    out = _with_references("(Lovelace, 2024) and (Hopper, 2025).", papers, markers, "apa")

    body = out.split("## Sources cited in this summary")[1]
    assert body.index("Hopper") < body.index("Lovelace")


def test_long_reviews_are_trimmed_rather_than_dropped():
    sections = [("Q1", "a" * MAX_SECTION_CHARS), ("Q2", "b" * MAX_SECTION_CHARS), ("Q3", "c" * 10)]
    fitted, trimmed = _fit_sections(sections)

    assert [q for q, _ in fitted] == ["Q1", "Q2", "Q3"]  # nothing dropped
    assert sum(len(t) for _, t in fitted) <= MAX_SECTION_CHARS
    assert trimmed == 2
    assert fitted[2][1] == "c" * 10  # a short section is left alone


def test_short_reviews_are_sent_untouched():
    sections = [("Q1", "short"), ("Q2", "also short")]
    assert _fit_sections(sections) == (sections, 0)


def test_scqa_lands_as_four_paragraphs_however_the_model_lays_it_out():
    """Markdown joins consecutive lines, so an SCQA written as four lines
    renders as one wall of text — the exact thing the opening exists to
    spare the reader."""
    from thesis_tools.exec_summary import _space_out_scqa

    for laid_out in (
        "**Situation:** A. **Complication:** B. **Question:** C? **Answer:** D.",
        "**Situation:** A.\n**Complication:** B.\n**Question:** C?\n**Answer:** D.",
        "**Situation:** A.\n\n**Complication:** B.\n\n**Question:** C?\n\n**Answer:** D.",
    ):
        spaced = _space_out_scqa(laid_out)
        assert spaced.count("\n\n") == 3
        assert _space_out_scqa(spaced) == spaced  # idempotent


@patch("thesis_tools.llm.ask")
def test_the_written_summary_is_spaced_before_it_is_returned(mock_ask):
    mock_ask.return_value = "## The short version\n\n**Situation:** A.\n**Complication:** B.\n**Answer:** C."
    text, _ = build_exec_summary(**_kwargs())
    assert "A.\n\n**Complication:**" in text
