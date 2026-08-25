from thesis_tools.library.themes import (
    Theme,
    _content_runs,
    documents_from_entries,
    extract_themes,
)


def _doc(key, text, engaged=False):
    return (key, text, engaged)


def test_a_theme_must_recur_across_papers():
    """One paper's phrasing is not a theme, however often it repeats it."""
    themes = extract_themes(
        [
            _doc("a", "Generative AI. Generative AI. Generative AI everywhere."),
            _doc("b", "Consumer trust in hotels."),
        ]
    )
    assert [t.term for t in themes] == []


def test_document_frequency_not_raw_count_decides_reach():
    """A phrase said fifteen times in one paper must not outrank one said
    once each in three."""
    themes = extract_themes(
        [
            _doc("a", " ".join(["dynamic pricing"] * 15) + " travel planning"),
            _doc("b", "travel planning"),
            _doc("c", "travel planning and dynamic pricing"),
        ]
    )
    by_term = {t.term: t.paper_count for t in themes}
    assert by_term["travel planning"] == 3
    assert by_term["dynamic pricing"] == 2


def test_phrases_never_span_a_stopword_or_a_sentence_break():
    """"impact of AI on travel planning" must not yield "ai travel"."""
    runs = [[w for w, _ in run] for run in _content_runs("The impact of AI on travel planning")]
    assert ["ai"] in runs
    assert ["travel", "planning"] in runs
    assert not any("ai" in run and "travel" in run for run in runs)

    themes = extract_themes([_doc("a", "impact of AI on travel planning"), _doc("b", "impact of AI on travel planning")])
    assert "ai travel" not in {t.term for t in themes}


def test_short_acronyms_survive_the_length_floor():
    """A flat minimum word length drops exactly the terms a reader looks for
    first — AI, ML, UX, OTA."""
    themes = extract_themes(
        [_doc("a", "AI and UX in booking"), _doc("b", "AI and UX for travellers")]
    )
    terms = {t.term for t in themes}
    assert "ai" in terms and "ux" in terms


def test_terms_are_shown_as_the_papers_write_them():
    themes = extract_themes(
        [_doc("a", "Generative AI for ChatGPT users"), _doc("b", "generative AI and ChatGPT")]
    )
    labels = {t.label for t in themes}
    # The acronym keeps its capitals rather than being flattened to "ai",
    # and a mixed-case product name survives intact.
    assert any(label.endswith(" AI") for label in labels)
    assert "ChatGPT" in labels
    assert "chatgpt" not in labels


def test_a_bare_word_is_dropped_when_a_phrase_says_the_same_thing():
    """"generative" beside "generative AI" is one theme shown twice."""
    docs = [_doc(str(i), "generative AI in travel") for i in range(4)]
    terms = {t.term for t in extract_themes(docs)}
    assert "generative ai" in terms
    assert "generative" not in terms


def test_a_bare_word_survives_when_it_is_used_beyond_the_phrase():
    docs = [_doc(str(i), "trust in systems") for i in range(6)]
    docs += [_doc(f"p{i}", "consumer trust in systems") for i in range(2)]
    terms = {t.term for t in extract_themes(docs)}
    assert "trust" in terms  # 8 papers, far beyond the 2 that say "consumer trust"


def test_academic_scaffolding_is_not_a_theme():
    """"a systematic review exploring perspectives on X" names no subject."""
    docs = [_doc(str(i), "A systematic review exploring perspectives and implications") for i in range(4)]
    assert extract_themes(docs) == []


def test_engagement_is_counted_per_theme():
    themes = extract_themes(
        [
            _doc("a", "supply chain logistics", engaged=False),
            _doc("b", "supply chain logistics", engaged=False),
            _doc("c", "travel planning", engaged=True),
            _doc("d", "travel planning", engaged=False),
        ]
    )
    by_term = {t.term: t for t in themes}
    assert by_term["supply chain"].engages_questions is False
    assert by_term["travel planning"].engaged_papers == 1


def test_ranking_is_stable_for_the_same_library():
    """Two runs over an unchanged library must render the same cloud rather
    than reshuffling equal-reach themes."""
    docs = [_doc(str(i), "travel planning and consumer trust and dynamic pricing") for i in range(3)]
    assert [t.term for t in extract_themes(docs)] == [t.term for t in extract_themes(docs)]


def test_documents_from_entries_uses_title_and_abstract_only():
    """Deliberately not the full extracted text, whose reference lists and
    running headers would swamp the subject matter."""
    from thesis_tools.library.index_store import LibraryEntry
    from thesis_tools.sources.base import Paper

    entry = LibraryEntry(
        file_path="a.pdf", file_hash="h", file_type="pdf", size_bytes=1,
        indexed_at="2026-01-01T00:00:00", confidence="verified-doi", doi="10.1/a",
        paper=Paper(title="A Title", doi="10.1/a", abstract="An abstract.",
                    full_text_excerpt="REFERENCES Smith 2020 Jones 2019"),
    )
    (key, text, engaged), = documents_from_entries([entry], engaged_keys={entry.paper.key()})
    assert text == "A Title. An abstract."
    assert engaged is True


def test_theme_label_falls_back_to_the_matching_term():
    assert Theme(term="travel planning").label == "travel planning"


def _copy(paper, i):
    from thesis_tools.library.index_store import LibraryEntry

    return LibraryEntry(
        file_path=f"/lib/copy{i}.pdf", file_hash=str(i), file_type="pdf", size_bytes=1,
        indexed_at="2026-01-01T00:00:00", confidence="verified-doi", doi=paper.doi, paper=paper,
    )


def test_the_same_paper_saved_twice_counts_once():
    """The reported bug. A library routinely holds the same paper in two
    files, and counting both does not merely double a number — it lets a
    phrase used by ONE paper clear the "appears in at least two" bar and be
    presented as a recurring theme."""
    from thesis_tools.sources.base import Paper

    paper = Paper(title="Generative AI in travel planning", doi="10.1/a", year=2024,
                  abstract="Generative AI and travel planning.")
    other = Paper(title="Travel planning and trust", doi="10.1/b", year=2025,
                  abstract="Travel planning matters.")
    entries = [_copy(paper, 1), _copy(paper, 2), _copy(other, 3)]

    themes = extract_themes(documents_from_entries(entries))
    terms = {t.term: t for t in themes}

    # One paper's phrase must not survive on the strength of its duplicate.
    assert "generative ai" not in terms
    assert terms["travel planning"].paper_count == 2
    assert terms["travel planning"].paper_keys == list(dict.fromkeys(terms["travel planning"].paper_keys))


def test_every_theme_lists_each_paper_at_most_once():
    from thesis_tools.sources.base import Paper

    papers = [
        Paper(title="Travel planning by algorithms", doi="10.1/a", year=2026, abstract="Travel planning."),
        Paper(title="Agentic travel planning", doi="10.1/b", year=2025, abstract="Travel planning."),
        Paper(title="Trust in travel advice", doi="10.1/c", year=2024, abstract="Travel advice."),
    ]
    entries = [_copy(papers[0], i) for i in range(3)] + [_copy(papers[1], i) for i in range(3, 6)] + [_copy(papers[2], 9)]

    for theme in extract_themes(documents_from_entries(entries)):
        assert len(theme.paper_keys) == len(set(theme.paper_keys)), theme.term
        assert theme.engaged_papers <= theme.paper_count


def test_engagement_is_not_double_counted_across_duplicate_files():
    from thesis_tools.sources.base import Paper

    paper = Paper(title="Travel planning study", doi="10.1/a", year=2024, abstract="Travel planning.")
    other = Paper(title="Travel planning review", doi="10.1/b", year=2025, abstract="Travel planning.")
    entries = [_copy(paper, 1), _copy(paper, 2), _copy(other, 3)]

    themes = extract_themes(documents_from_entries(entries, engaged_keys={paper.key()}))
    theme = {t.term: t for t in themes}["travel planning"]

    assert theme.paper_count == 2
    assert theme.engaged_papers == 1  # not 2, though two files carried it


def test_duplicate_files_merge_their_text_rather_than_one_winning():
    """A copy that happens to carry an abstract should contribute it even if
    the other copy has none."""
    from thesis_tools.sources.base import Paper

    bare = Paper(title="A study", doi="10.1/a", year=2024)
    with_abstract = Paper(title="A study", doi="10.1/a", year=2024, abstract="On dynamic pricing.")
    (key, text, _), = documents_from_entries([_copy(bare, 1), _copy(with_abstract, 2)])

    assert "dynamic pricing" in text.lower()
    assert text.count("A study") == 1  # merged, not concatenated twice


def test_no_phrase_spans_the_title_abstract_join():
    """Joined with a bare space, the last word of the title and the first of
    the abstract read as adjacent, filling the cloud with phrases no paper
    ever wrote."""
    from thesis_tools.sources.base import Paper

    papers = [
        Paper(title=f"Report on travel planning", doi=f"10.1/{i}", year=2024,
              abstract="Generative AI is discussed.")
        for i in range(3)
    ]
    terms = {t.term for t in extract_themes(documents_from_entries([_copy(p, i) for i, p in enumerate(papers)]))}

    assert "travel planning" in terms
    assert "generative ai" in terms
    assert "planning generative" not in terms
