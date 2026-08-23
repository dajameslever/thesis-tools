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
                    "openAccessPdf": {"url": "https://example.org/oa.pdf"},
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
    assert p.pdf_url == "https://example.org/oa.pdf"


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_pdf_url_none_when_not_open_access(mock_get):
    mock_get.return_value = _mock_response(
        json_data={"data": [{"title": "Paywalled Paper", "year": 2021}]}
    )
    results = SemanticScholarClient().search("sleep cognition")
    assert results[0].pdf_url is None


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
                    "best_oa_location": {"pdf_url": "https://example.org/oa.pdf"},
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
    assert p.pdf_url == "https://example.org/oa.pdf"


@patch("thesis_tools.sources.openalex.requests.get")
def test_openalex_falls_back_to_open_access_oa_url(mock_get):
    mock_get.return_value = _mock_response(
        json_data={
            "results": [
                {
                    "display_name": "Sleep and Cognition",
                    "open_access": {"oa_url": "https://example.org/fallback.pdf"},
                }
            ]
        }
    )
    results = OpenAlexClient().search("sleep cognition")
    assert results[0].pdf_url == "https://example.org/fallback.pdf"


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
    assert p.pdf_url == "http://arxiv.org/pdf/1234.5678v1"


@patch("thesis_tools.sources.arxiv.requests.get")
def test_arxiv_returns_empty_on_bad_xml(mock_get):
    mock_get.return_value = _mock_response(content=b"not xml")
    results = ArxivClient().search("sleep cognition")
    assert results == []


def _mock_429_response(retry_after=None):
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": retry_after} if retry_after else {}
    return resp


@patch("thesis_tools.sources.semantic_scholar.time.sleep")
@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_retries_once_on_429_then_succeeds(mock_get, mock_sleep):
    success = _mock_response(json_data={"data": [{"title": "Sleep and Cognition", "year": 2021}]})
    mock_get.side_effect = [_mock_429_response(retry_after="2"), success]

    results = SemanticScholarClient().search("sleep cognition")

    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(2.0)
    assert len(results) == 1
    assert results[0].title == "Sleep and Cognition"


@patch("thesis_tools.sources.semantic_scholar.time.sleep")
@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_gives_up_after_max_retries(mock_get, mock_sleep):
    mock_get.side_effect = [_mock_429_response(), _mock_429_response(), _mock_429_response()]

    results = SemanticScholarClient().search("sleep cognition")

    # 1 initial attempt + MAX_RETRIES retries, then give up gracefully.
    assert mock_get.call_count == 3
    assert results == []


@patch("thesis_tools.sources.semantic_scholar.time.sleep")
@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_retry_falls_back_to_backoff_without_retry_after_header(mock_get, mock_sleep):
    success = _mock_response(json_data={"data": []})
    mock_get.side_effect = [_mock_429_response(retry_after=None), success]

    SemanticScholarClient().search("sleep cognition")

    mock_sleep.assert_called_once_with(1.5)


@patch("thesis_tools.sources.semantic_scholar.time.sleep")
@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_retry_caps_backoff_at_max(mock_get, mock_sleep):
    success = _mock_response(json_data={"data": []})
    mock_get.side_effect = [_mock_429_response(retry_after="9999"), success]

    SemanticScholarClient().search("sleep cognition")

    mock_sleep.assert_called_once_with(10.0)


def _mock_null_body_response():
    """Simulates a 200 response whose body is `null` — resp.json() returns
    None rather than a dict, a real (if rare) shape seen from these APIs."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = None
    return resp


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_search_handles_null_json_body(mock_get):
    mock_get.return_value = _mock_null_body_response()
    assert SemanticScholarClient().search("sleep cognition") == []


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_lookup_references_handles_null_json_body(mock_get):
    mock_get.return_value = _mock_null_body_response()
    assert SemanticScholarClient().lookup_references("10.1/x") == []


@patch("thesis_tools.sources.openalex.requests.get")
def test_openalex_search_handles_null_json_body(mock_get):
    mock_get.return_value = _mock_null_body_response()
    assert OpenAlexClient().search("sleep cognition") == []


@patch("thesis_tools.sources.crossref.requests.get")
def test_crossref_search_handles_null_json_body(mock_get):
    mock_get.return_value = _mock_null_body_response()
    assert CrossrefClient().search("sleep cognition") == []


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_search_handles_explicit_null_data_key(mock_get):
    """{"data": null} — key present, value null — is different from a
    missing key, and `.get("data", [])` doesn't catch it."""
    mock_get.return_value = _mock_response(json_data={"data": None})
    assert SemanticScholarClient().search("sleep cognition") == []


@patch("thesis_tools.sources.semantic_scholar.requests.get")
def test_semantic_scholar_lookup_references_handles_explicit_null_data_key(mock_get):
    mock_get.return_value = _mock_response(json_data={"data": None})
    assert SemanticScholarClient().lookup_references("10.1/x") == []


@patch("thesis_tools.sources.openalex.requests.get")
def test_openalex_search_handles_explicit_null_results_key(mock_get):
    mock_get.return_value = _mock_response(json_data={"results": None})
    assert OpenAlexClient().search("sleep cognition") == []


@patch("thesis_tools.sources.crossref.requests.get")
def test_crossref_search_handles_explicit_null_message_and_items(mock_get):
    mock_get.return_value = _mock_response(json_data={"message": None})
    assert CrossrefClient().search("sleep cognition") == []


@patch("thesis_tools.sources.crossref.requests.get")
def test_crossref_search_handles_explicit_null_items_key(mock_get):
    mock_get.return_value = _mock_response(json_data={"message": {"items": None}})
    assert CrossrefClient().search("sleep cognition") == []
