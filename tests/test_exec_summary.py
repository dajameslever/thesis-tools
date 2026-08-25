from unittest.mock import patch

import pytest

from thesis_tools.exec_summary import (
    MAX_SECTION_CHARS,
    _cites,
    _fit_sections,
    _with_references,
    build_summary,
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
    assert target_words_for(4) < target_words_for(12) < target_words_for(30)
    # A large library must not be flattened to the same length as a small one.
    assert target_words_for(40) > 2 * target_words_for(4)


def test_how_much_is_said_scales_too_not_just_how_long_it_is():
    """Length alone is not proportionality: a long summary that still makes
    three points has padded three points."""
    from thesis_tools.exec_summary import structure_for

    small_findings, small_callouts = structure_for(3)
    large_findings, large_callouts = structure_for(60)

    assert small_findings == "two to three" and large_findings == "five to seven"
    assert small_callouts != large_callouts
    # Monotonic across the bands, with no gaps or overlaps in coverage.
    seen = [structure_for(n)[0] for n in (1, 4, 5, 10, 11, 25, 26, 1000)]
    assert seen == sorted(seen, key=lambda v: ["two to three", "three to four", "four to five", "five to seven"].index(v))


@patch("thesis_tools.llm.ask")
def test_prompt_asks_for_the_pyramid_structure_and_the_debate(mock_ask):
    """The whole point of the second output: answer first, themes across the
    sub-questions, and the disagreements stated rather than averaged away."""
    mock_ask.return_value = "## The short version\n\n**Answer:** X."
    build_summary(**_kwargs())

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
    build_summary(**_kwargs(sections=[("Q1", "Body of section one."), ("Q2", "Body of section two.")]))

    user_message = mock_ask.call_args.args[2]
    assert "Body of section one." in user_message and "Body of section two." in user_message
    assert "words" not in user_message  # the varying target lives past the breakpoint
    assert "about" in mock_ask.call_args.kwargs["cache_suffix"]
    assert mock_ask.call_args.kwargs["cache"] is True


@patch("thesis_tools.llm.ask")
def test_contested_and_uncovered_questions_are_handed_to_the_model(mock_ask):
    mock_ask.return_value = "## The short version"
    build_summary(**_kwargs(tensions=["Does AI displace OTAs?"], no_coverage=["What about rail?"]))

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
    text, failure, _ = build_summary(**_kwargs(tensions=["Does AI displace OTAs?"]))

    assert failure == "BadRequestError: prompt is too long"
    assert "Not written" in text
    assert "Does AI displace OTAs?" in text


def test_no_client_produces_the_skeleton_without_claiming_a_failure():
    text, failure, _ = build_summary(**_kwargs(client=None))
    assert failure is None
    assert "## The short version" in text


def test_empty_review_is_not_summarized():
    text, failure, _ = build_summary(**_kwargs(sections=[("Q", "   ")]))
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
    text, _, _ = build_summary(**_kwargs())
    assert "A.\n\n**Complication:**" in text


@patch("thesis_tools.llm.ask")
def test_the_instruction_scales_the_number_of_points_to_the_evidence(mock_ask):
    """More evidence should buy more distinct things said, not more words
    about the same ones."""
    mock_ask.return_value = "## The short version"
    papers = [_paper(f"Author{i}", 2020 + i % 5, f"10.1/{i}", f"Paper {i}") for i in range(40)]
    build_summary(**_kwargs(cited_papers=papers, markers_by_key={p.key(): "" for p in papers}))

    suffix = mock_ask.call_args.kwargs["cache_suffix"]
    assert "five to seven findings" in suffix
    assert "2500 words" in suffix


@patch("thesis_tools.llm.ask")
def test_a_small_evidence_base_is_told_to_stay_small(mock_ask):
    mock_ask.return_value = "## The short version"
    build_summary(**_kwargs())  # two cited papers

    suffix = mock_ask.call_args.kwargs["cache_suffix"]
    assert "two to three findings" in suffix
    assert "400 words" in suffix


def test_every_finding_is_required_to_state_what_follows_from_it():
    """McKinsey-style means actionable: a section that describes what the
    literature contains without saying what to do differently is not done."""
    from thesis_tools.exec_summary import _EXEC_SYSTEM_PROMPT as _SYSTEM_PROMPT

    assert "So:" in _SYSTEM_PROMPT
    assert "not finished" in _SYSTEM_PROMPT
    assert "changing what the reader would do" in _SYSTEM_PROMPT
    assert "read more widely" in _SYSTEM_PROMPT  # named as the thing to reject


@patch("thesis_tools.llm.ask")
def test_detailed_variant_uses_its_own_prompt_and_scale(mock_ask):
    """The detailed summary answers 'what is actually in this literature?',
    not 'what do I need to know?' — a different prompt, and enough room to
    carry each source's specifics rather than only the conclusions."""
    from thesis_tools.exec_summary import _DETAILED_SYSTEM_PROMPT, _EXEC_SYSTEM_PROMPT

    mock_ask.return_value = "## What this evidence base looks like\n\nSmall and recent."
    build_summary(**_kwargs(variant="detailed"))

    assert mock_ask.call_args.args[1] is _DETAILED_SYSTEM_PROMPT
    assert mock_ask.call_args.args[1] is not _EXEC_SYSTEM_PROMPT
    # Two cited papers: 800 (the detailed floor), not 400 (the exec floor).
    assert "about 800 words" in mock_ask.call_args.kwargs["cache_suffix"]


def test_detailed_lengths_scale_above_the_executive_summary():
    from thesis_tools.exec_summary import DETAILED_MAX_WORDS, MAX_WORDS

    for sources in (1, 5, 20, 100):
        assert target_words_for(sources, "detailed") > target_words_for(sources, "summary")
    assert target_words_for(100, "detailed") == DETAILED_MAX_WORDS > MAX_WORDS


def test_the_detailed_prompt_forbids_restating_the_same_evidence():
    """The same sources reach several sub-questions; restating them under
    each turns a detailed summary into a merely long one."""
    from thesis_tools.exec_summary import _DETAILED_SYSTEM_PROMPT as prompt

    assert "REPETITION IS THE FAILURE MODE" in prompt
    assert "ONCE" in prompt                          # each contribution stated once
    assert "only what is ADDITIONAL" in prompt       # later mentions add, never restate
    assert "restating its own sub-question" in prompt
    assert "no closing summary" in prompt.lower() or "no section that recaps" in prompt.lower()
    assert "two different wordings" in prompt


def test_the_executive_summary_prompt_forbids_it_too():
    from thesis_tools.exec_summary import _EXEC_SYSTEM_PROMPT as prompt

    assert "Say each thing once" in prompt
    assert "two different wordings" in prompt


def test_the_detailed_prompt_asks_for_specifics_not_adjectives():
    from thesis_tools.exec_summary import _DETAILED_SYSTEM_PROMPT as prompt

    assert "on whom and where" in prompt
    assert "'significant', 'important' and 'robust' carry no information" in prompt
    assert "Omit any lead-in that would be empty" in prompt  # no "none" filler


def test_empty_sub_question_sections_are_not_padded_out():
    """A sub-question with nothing behind it should cost one sentence, not a
    paragraph explaining that it has nothing behind it."""
    from thesis_tools.exec_summary import _DETAILED_SYSTEM_PROMPT as prompt

    assert "one honest sentence saying so" in prompt


def test_an_unknown_variant_is_refused():
    with pytest.raises(ValueError, match="Unknown summary variant"):
        build_summary(**_kwargs(variant="deck"))


@patch("thesis_tools.llm.ask")
def test_the_detailed_fallback_is_not_shaped_like_an_executive_summary(mock_ask):
    mock_ask.return_value = None
    text, failure, _ = build_summary(**_kwargs(variant="detailed"))

    assert failure is not None
    assert text.startswith("## What this evidence base looks like")
    assert "## The short version" not in text


def _long_detailed(questions, closing=True):
    from thesis_tools.exec_summary import _section_heading

    parts = ["## What this evidence base looks like", "Shape of the evidence."]
    for i, q in enumerate(questions, start=1):
        parts += [_section_heading(i, q), "Prose citing (Doe, 2020)."]
    parts += ["## Across the questions", "A pattern."]
    if closing:
        parts += ["## Where this leaves the thesis", "- Run a targeted search."]
    return "\n\n".join(parts)


@patch("thesis_tools.llm.ask")
def test_a_summary_that_stops_early_is_reported_not_shipped(mock_ask):
    """The reported bug: the model ended its turn after the opening
    paragraph and a bare "## 1." heading, and a two-paragraph file was
    written as though it were the deliverable."""
    mock_ask.return_value = "## What this evidence base looks like\n\nThe review draws on 34 papers.\n\n## 1."

    text, failure, shortfall = build_summary(
        **_kwargs(variant="detailed", sections=[("Q one?", "s"), ("Q two?", "s")])
    )

    assert failure is None  # a real document came back — just not all of it
    assert shortfall and "never written" in shortfall
    assert text.startswith("## What this evidence base looks like")


@patch("thesis_tools.llm.ask")
def test_an_incomplete_summary_is_retried_once(mock_ask):
    """The prompt prefix is cached, so a second attempt re-reads it at a
    tenth of the price — cheap enough to be worth one try, not two."""
    questions = [("Q one?", "s"), ("Q two?", "s")]
    mock_ask.side_effect = [
        "## What this evidence base looks like\n\nShape.\n\n## 1.",
        _long_detailed([q for q, _ in questions]),
    ]

    text, failure, shortfall = build_summary(**_kwargs(variant="detailed", sections=questions))

    assert mock_ask.call_count == 2
    assert (failure, shortfall) == (None, None)
    assert "## Where this leaves the thesis" in text


@patch("thesis_tools.llm.ask")
def test_retrying_stops_at_one_attempt(mock_ask):
    mock_ask.return_value = "## What this evidence base looks like\n\nShape.\n\n## 1."
    build_summary(**_kwargs(variant="detailed", sections=[("Q one?", "s"), ("Q two?", "s")]))
    assert mock_ask.call_count == 2


@patch("thesis_tools.llm.ask")
def test_a_complete_summary_is_not_retried(mock_ask):
    questions = [("Q one?", "s"), ("Q two?", "s")]
    mock_ask.return_value = _long_detailed([q for q, _ in questions])

    text, failure, shortfall = build_summary(**_kwargs(variant="detailed", sections=questions))

    assert mock_ask.call_count == 1
    assert (failure, shortfall) == (None, None)


@patch("thesis_tools.llm.ask")
def test_hitting_the_output_limit_is_reported_as_such(mock_ask):
    """Running out of room and choosing to stop are different problems, and
    trimming the ragged edge off the first makes them look identical."""
    questions = [("Q one?", "s")]

    def _ask(*args, meta=None, **kwargs):
        if meta is not None:
            meta["truncated"] = True
        return _long_detailed([q for q, _ in questions])

    mock_ask.side_effect = _ask
    _, failure, shortfall = build_summary(**_kwargs(variant="detailed", sections=questions))

    assert failure is None
    assert "ran out of room" in shortfall


@patch("thesis_tools.llm.ask")
def test_a_missing_closing_section_counts_as_incomplete(mock_ask):
    questions = [("Q one?", "s")]
    mock_ask.return_value = _long_detailed([q for q, _ in questions], closing=False)

    _, _, shortfall = build_summary(**_kwargs(variant="detailed", sections=questions))
    assert "Where this leaves the thesis" in shortfall


@patch("thesis_tools.llm.ask")
def test_an_executive_summary_missing_a_required_heading_is_incomplete(mock_ask):
    mock_ask.return_value = "## The short version\n\n**Answer:** Something."
    _, _, shortfall = build_summary(**_kwargs())
    assert shortfall and "What the evidence shows" in shortfall


def test_the_headings_asked_for_and_the_headings_checked_are_the_same():
    """Generated in one place so the instruction and the check can never
    disagree about what a section heading looks like."""
    from thesis_tools.exec_summary import _section_heading, _shortfall

    questions = ["How do travellers use AI tools?"]
    doc = f"## What this evidence base looks like\n\nx\n\n{_section_heading(1, questions[0])}\n\nProse.\n\n## Where this leaves the thesis\n\n- Act."
    assert _shortfall(doc, "detailed", questions) is None


def test_the_output_budget_is_set_in_tokens_not_words():
    """A budget of "words x 2.5" reads generous and is not: a word costs more
    than a token, so 4,000 words got room for ~7,400 — and a run overshot it
    and was cut off with its closing section unwritten."""
    from thesis_tools.exec_summary import TOKENS_PER_WORD, max_tokens_for

    for words in (800, 2000, 4000, 6800):
        room_in_words = max_tokens_for(words) / TOKENS_PER_WORD
        assert room_in_words >= words * 2.4, words


def test_the_budget_is_bounded_at_both_ends():
    from thesis_tools.exec_summary import MAX_OUTPUT_TOKENS, max_tokens_for

    assert max_tokens_for(1) == 1500                       # a floor for tiny asks
    assert max_tokens_for(100_000) == MAX_OUTPUT_TOKENS    # and a ceiling


def test_a_detailed_summary_is_not_capped_below_what_its_evidence_needs():
    """34 sources want ~6,800 words at 200 each. Capping that at 4,000 asked
    for a document the evidence did not fit into, and the model wrote past
    the ask rather than dropping the detail."""
    assert target_words_for(34, "detailed") == 6800
    assert target_words_for(100, "detailed") == 8000


@patch("thesis_tools.llm.ask")
def test_a_truncated_draft_is_retried_with_more_room(mock_ask):
    """Retrying a truncation on the same budget truncates again in the same
    place — a wasted request, not a second chance."""
    questions = [("Q one?", "s")]
    budgets = []

    def _ask(*args, meta=None, max_tokens=None, **kwargs):
        budgets.append(max_tokens)
        if len(budgets) == 1:
            if meta is not None:
                meta["truncated"] = True
            return "## What this evidence base looks like\n\nShape.\n\n## 1. Q one?\n\nCut off mid-sen"
        return _long_detailed([q for q, _ in questions])

    mock_ask.side_effect = _ask
    _, failure, shortfall = build_summary(**_kwargs(variant="detailed", sections=questions))

    assert len(budgets) == 2 and budgets[1] > budgets[0]
    assert (failure, shortfall) == (None, None)


@patch("thesis_tools.llm.ask")
def test_a_draft_that_merely_stopped_early_is_retried_on_the_same_budget(mock_ask):
    """Nothing was wrong with the budget, so widening it would only raise the
    ceiling on a model that never reached the old one."""
    questions = [("Q one?", "s")]
    budgets = []

    def _ask(*args, max_tokens=None, **kwargs):
        budgets.append(max_tokens)
        return "## What this evidence base looks like\n\nShape.\n\n## 1."

    mock_ask.side_effect = _ask
    build_summary(**_kwargs(variant="detailed", sections=questions))

    assert len(budgets) == 2 and budgets[0] == budgets[1]
