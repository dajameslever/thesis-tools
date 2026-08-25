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
    assert text == "A Title An abstract."
    assert engaged is True


def test_theme_label_falls_back_to_the_matching_term():
    assert Theme(term="travel planning").label == "travel planning"
