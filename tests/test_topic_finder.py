from unittest.mock import patch

from thesis_tools.sources.base import Paper
from thesis_tools.topic_finder import TopicFinderInputs, run_topic_finder


def _fake_search_factory(papers_by_source):
    def _search(self, query, limit=15):
        return papers_by_source.get(self.name, [])

    return _search


@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_end_to_end(mock_ss, mock_oa, mock_arxiv, mock_crossref, tmp_path):
    mock_ss.return_value = [
        Paper(
            title="Sleep Deprivation and Adolescent Decision-Making",
            year=2018,
            authors=["Jane Doe"],
            abstract="We study sleep deprivation and decision-making in teenagers and find impairment.",
            doi="10.1/existing",
            sources=["semanticscholar"],
        )
    ]
    mock_oa.return_value = []
    mock_arxiv.return_value = []
    mock_crossref.return_value = []

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Sleep Deprivation and Adolescent Decision-Making",
        research_question="Does sleep deprivation impair decision-making in adolescents?",
        style="apa",
        output_path=str(output_path),
    )

    result_path = run_topic_finder(inputs)
    assert result_path == str(output_path)
    text = output_path.read_text()
    assert "near-identical" in text.lower()
    assert "Doe, J." in text


@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_no_hits(mock_ss, mock_oa, mock_arxiv, mock_crossref, tmp_path):
    for m in (mock_ss, mock_oa, mock_arxiv, mock_crossref):
        m.return_value = []

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Basket Weaving",
        working_title="A Totally Novel Basket Weaving Technique From Rural Patagonia",
        output_path=str(output_path),
    )
    run_topic_finder(inputs)
    text = output_path.read_text()
    assert "good sign for novelty" in text.lower()


def test_run_topic_finder_rejects_unknown_style(tmp_path):
    import pytest

    inputs = TopicFinderInputs(field="X", working_title="Y", style="vancouver", output_path=str(tmp_path / "r.md"))
    with pytest.raises(ValueError):
        run_topic_finder(inputs)


def test_run_topic_finder_rejects_unknown_source(tmp_path):
    import pytest

    inputs = TopicFinderInputs(field="X", working_title="Y", sources=["not-a-real-source"], output_path=str(tmp_path / "r.md"))
    with pytest.raises(ValueError):
        run_topic_finder(inputs)
