"""Tests for source adapters. All network calls are mocked — these tests
should never make a real HTTP request."""

from unittest.mock import MagicMock, patch

from thesis_tools.sources.arxiv import ArxivClient
from thesis_tools.sources.crossref import CrossrefClient
from thesis_tools.sources.openalex import OpenAlexClient, reconstruct_abstract
from thesis_tools.sources.semantic_scholar import SemanticScholarClient


def _mock_response(json_data=None, content=None):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    if json_data is not None:
        resp.json.return_value = json_data
    if content is not None:
        resp.content = content
    return resp


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_parses_results(mock_get):
    mock_get.return_value = _mock_response(
        json_data={
            "data": [
                {
                    "title": "Sleep and Cognition",
                    "abstract": "An abstract.",
                    "year": 2021,
                    "authors": [{"name": "Jane Doe"}],
                    "venue": "Sleep Journal",
                    "externalIds": {"DOI": "10.1/x"},
                    "url": "https://example.com/paper",
                    "citationCount": 5,
                }
            ]
        }
    )
    results = SemanticScholarClient().search("sleep cognition", limit=5)
    assert len(results) == 1
    p = results[0]
    assert p.title == "Sleep and Cognition"
    assert p.authors == ["Jane Doe"]
    assert p.doi == "10.1/x"
    assert p.sources == ["semanticscholar"]


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_returns_empty_on_error(mock_get):
    mock_get.side_effect = Exception("network down")
    results = SemanticScholarClient().search("sleep cognition")
    assert results == []


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_lookup_doi_returns_paper(mock_get):
    mock_get.return_value = _mock_response(json_data={"title": "Sleep and Cognition", "year": 2021})
    paper = SemanticScholarClient().lookup_doi("10.1/x")
    assert paper is not None
    assert paper.title == "Sleep and Cognition"


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_lookup_doi_404_returns_none(mock_get):
    resp = MagicMock()
    resp.status_code = 404
    mock_get.return_value = resp
    assert SemanticScholarClient().lookup_doi("10.1/does-not-exist") is None


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_lookup_references_unwraps_cited_paper(mock_get):
    mock_get.return_value = _mock_response(
        json_data={"data": [{"citedPaper": {"title": "An Older Foundational Paper", "year": 2005}}, {"citedPaper": {}}]}
    )
    refs = SemanticScholarClient().lookup_references("10.1/x")
    assert len(refs) == 1
    assert refs[0].title == "An Older Foundational Paper"


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_lookup_references_returns_empty_on_error(mock_get):
    mock_get.side_effect = Exception("timeout")
    assert SemanticScholarClient().lookup_references("10.1/x") == []


def test_reconstruct_abstract_from_inverted_index():
    inverted = {"An": [0], "abstract": [1], "about": [2], "sleep": [3]}
    assert reconstruct_abstract(inverted) == "An abstract about sleep"


def test_reconstruct_abstract_handles_none():
    assert reconstruct_abstract(None) is None


@patch("thesis_tools.sources.openalex.requests.get")
def test_openalex_parses_results(mock_get):
    mock_get.return_value = _mock_response(
        json_data={
            "results": [
                {
                    "display_name": "Sleep and Cognition",
                    "authorships": [{"author": {"display_name": "Jane Doe"}}],
                    "publication_year": 2021,
                    "primary_location": {"source": {"display_name": "Sleep Journal"}},
                    "abstract_inverted_index": {"An": [0], "abstract.": [1]},
                    "doi": "https://doi.org/10.1/x",
                    "id": "https://openalex.org/W123",
                    "biblio": {"volume": "5", "issue": "2", "first_page": "1", "last_page": "10"},
                    "cited_by_count": 3,
                }
            ]
        }
    )
    results = OpenAlexClient().search("sleep cognition")
    assert len(results) == 1
    p = results[0]
    assert p.doi == "10.1/x"
    assert p.pages == "1-10"
    assert p.abstract == "An abstract."


@patch("thesis_tools.sources.crossref.requests.get")
def test_crossref_parses_results_and_strips_jats(mock_get):
    mock_get.return_value = _mock_response(
        json_data={
            "message": {
                "items": [
                    {
                        "title": ["Sleep and Cognition"],
                        "author": [{"given": "Jane", "family": "Doe"}],
                        "published": {"date-parts": [[2021, 5]]},
                        "container-title": ["Sleep Journal"],
                        "DOI": "10.1/x",
                        "URL": "https://doi.org/10.1/x",
                        "abstract": "<jats:p>An abstract.</jats:p>",
                        "volume": "5",
                        "issue": "2",
                        "page": "1-10",
                        "is-referenced-by-count": 7,
                    }
                ]
            }
        }
    )
    results = CrossrefClient().search("sleep cognition")
    assert len(results) == 1
    p = results[0]
    assert p.authors == ["Jane Doe"]
    assert p.year == 2021
    assert p.abstract == "An abstract."


@patch("thesis_tools.sources.crossref.requests.get")
def test_crossref_skips_items_without_title(mock_get):
    mock_get.return_value = _mock_response(json_data={"message": {"items": [{"DOI": "10.1/x"}]}})
    results = CrossrefClient().search("sleep cognition")
    assert results == []


_ARXIV_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <title>Sleep and Cognition</title>
    <summary>An abstract about sleep.</summary>
    <published>2021-05-01T00:00:00Z</published>
    <author><name>Jane Doe</name></author>
  </entry>
</feed>
"""


@patch("thesis_tools.sources.arxiv.requests.get")
def test_arxiv_parses_atom_feed(mock_get):
    mock_get.return_value = _mock_response(content=_ARXIV_XML)
    results = ArxivClient().search("sleep cognition")
    assert len(results) == 1
    p = results[0]
    assert p.title == "Sleep and Cognition"
    assert p.year == 2021
    assert p.authors == ["Jane Doe"]
    assert p.url == "http://arxiv.org/abs/1234.5678v1"


@patch("thesis_tools.sources.arxiv.requests.get")
def test_arxiv_returns_empty_on_bad_xml(mock_get):
    mock_get.return_value = _mock_response(content=b"not xml")
    results = ArxivClient().search("sleep cognition")
    assert results == []
