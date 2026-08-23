from unittest.mock import MagicMock

from thesis_tools.library.extract import ExtractedDocument
from thesis_tools.library.identify import (
    clean_title_hint,
    find_dois,
    guess_title_from_text,
    guess_year,
    identify_document,
)
from thesis_tools.sources.base import Paper


def _doc(text="", title_hint=None, author_hint=None, file_type="pdf"):
    return ExtractedDocument(text=text, title_hint=title_hint, author_hint=author_hint, file_type=file_type)


def test_identify_document_resolves_via_doi():
    crossref = MagicMock()
    crossref.lookup_doi.return_value = Paper(title="Canonical Title", doi="10.1234/x", year=2020)
    semantic_scholar = MagicMock()

    doc = _doc(text="See https://doi.org/10.1234/x for details.")
    result = identify_document(doc, "fallback title", crossref_client=crossref, semantic_scholar_client=semantic_scholar)

    assert result.confidence == "verified-doi"
    assert result.paper.title == "Canonical Title"
    assert result.matched_doi == "10.1234/x"
    semantic_scholar.lookup_doi.assert_not_called()  # crossref succeeded first, no need to fall back


def test_identify_document_falls_back_to_semantic_scholar_doi_lookup():
    crossref = MagicMock()
    crossref.lookup_doi.return_value = None
    semantic_scholar = MagicMock()
    semantic_scholar.lookup_doi.return_value = Paper(title="Canonical Title", doi="10.1234/x", year=2020)

    doc = _doc(text="DOI: 10.1234/x")
    result = identify_document(doc, "fallback title", crossref_client=crossref, semantic_scholar_client=semantic_scholar)

    assert result.confidence == "verified-doi"
    assert result.paper.title == "Canonical Title"


def test_identify_document_fetches_references_when_requested():
    crossref = MagicMock()
    crossref.lookup_doi.return_value = Paper(title="Canonical Title", doi="10.1234/x", year=2020)
    semantic_scholar = MagicMock()
    semantic_scholar.lookup_references.return_value = [Paper(title="An Older Work", year=2001, doi="10.1234/old")]

    doc = _doc(text="10.1234/x")
    result = identify_document(
        doc, "fallback", fetch_references=True, crossref_client=crossref, semantic_scholar_client=semantic_scholar
    )

    assert result.references == [{"doi": "10.1234/old", "title": "An Older Work", "year": 2001}]


def test_identify_document_does_not_fetch_references_by_default():
    crossref = MagicMock()
    crossref.lookup_doi.return_value = Paper(title="Canonical Title", doi="10.1234/x", year=2020)
    semantic_scholar = MagicMock()

    doc = _doc(text="10.1234/x")
    result = identify_document(doc, "fallback", crossref_client=crossref, semantic_scholar_client=semantic_scholar)

    assert result.references == []
    semantic_scholar.lookup_references.assert_not_called()


def test_identify_document_confirms_via_title_search_when_no_doi():
    crossref = MagicMock()
    crossref.search.return_value = [Paper(title="Sleep Deprivation and Adolescent Decision-Making", doi="10.1234/y", year=2019)]
    semantic_scholar = MagicMock()
    semantic_scholar.search.return_value = []

    doc = _doc(text="No DOI here, just some body text.", title_hint="Sleep Deprivation and Adolescent Decision-Making")
    result = identify_document(doc, "fallback", crossref_client=crossref, semantic_scholar_client=semantic_scholar)

    assert result.confidence == "verified-title-match"
    assert result.matched_doi == "10.1234/y"


def test_identify_document_unresolved_when_nothing_matches():
    crossref = MagicMock()
    crossref.search.return_value = []
    semantic_scholar = MagicMock()
    semantic_scholar.search.return_value = []

    doc = _doc(text="PDF\nHI\n", author_hint="Jane Doe")
    result = identify_document(doc, "My Local Notes", crossref_client=crossref, semantic_scholar_client=semantic_scholar)

    assert result.confidence == "unresolved"
    assert result.paper.title == "My Local Notes"
    assert result.paper.authors == ["Jane Doe"]


def test_find_dois_extracts_and_strips_trailing_punctuation():
    text = "See (https://doi.org/10.1038/nphys1170) and 10.1000/xyz123, also 10.1000/abc."
    dois = find_dois(text)
    assert dois == ["10.1038/nphys1170", "10.1000/xyz123", "10.1000/abc"]


def test_find_dois_deduplicates_and_caps_results():
    text = " ".join(["10.1000/a"] * 3 + ["10.1000/b", "10.1000/c"])
    assert find_dois(text, max_results=2) == ["10.1000/a", "10.1000/b"]


def test_guess_year_picks_most_common():
    assert guess_year("Published 2019. Cited in 2019 and 2021.") == 2019


def test_guess_year_none_when_no_year():
    assert guess_year("no dates here") is None


def test_clean_title_hint_rejects_generic_titles():
    assert clean_title_hint("Microsoft Word - draft.docx") is None
    assert clean_title_hint("Untitled") is None
    assert clean_title_hint("  ") is None
    assert clean_title_hint("Real Title Here") == "Real Title Here"


def test_guess_title_from_text_skips_short_and_uppercase_lines():
    text = "PDF\nABSTRACT\nThis Is A Reasonably Long Title Line About Sleep\nBody text follows."
    assert guess_title_from_text(text) == "This Is A Reasonably Long Title Line About Sleep"


def test_guess_title_from_text_none_when_nothing_fits():
    assert guess_title_from_text("PDF\nHI\n") is None
