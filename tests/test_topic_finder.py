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


@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_writes_reusable_cache(mock_ss, mock_oa, mock_arxiv, mock_crossref, tmp_path):
    mock_ss.return_value = [
        Paper(title="Sleep Deprivation and Adolescent Decision-Making", year=2018, abstract="Studies impairment.", doi="10.1/existing")
    ]
    mock_oa.return_value = mock_arxiv.return_value = mock_crossref.return_value = []

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(field="Psychology", working_title="Sleep and Decision-Making", output_path=str(output_path))
    run_topic_finder(inputs)

    cache_path = tmp_path / "report.md.papers.json"
    assert cache_path.is_file()

    # Reanalyzing must not touch the network at all.
    mock_ss.reset_mock()
    reanalyze_output = tmp_path / "report2.md"
    reanalyze_inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Sleep and Decision-Making",
        output_path=str(reanalyze_output),
        reanalyze_from=str(cache_path),
        sub_questions=["Does sleep deprivation impair decision-making?"],
    )
    run_topic_finder(reanalyze_inputs)

    mock_ss.assert_not_called()
    text = reanalyze_output.read_text()
    assert "Sleep Deprivation and Adolescent Decision-Making" in text
    assert "Does sleep deprivation impair decision-making?" in text


def test_run_topic_finder_reanalyze_missing_cache_raises(tmp_path):
    import pytest

    inputs = TopicFinderInputs(
        field="X", working_title="Y", output_path=str(tmp_path / "r.md"), reanalyze_from=str(tmp_path / "missing.json")
    )
    with pytest.raises(ValueError):
        run_topic_finder(inputs)


@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_prints_one_llm_notice_not_one_per_paper(mock_ss, mock_oa, mock_arxiv, mock_crossref, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_ss.return_value = [
        Paper(title=f"Paper {i}", year=2020, abstract="An abstract with content.", doi=f"10.1/{i}")
        for i in range(5)
    ]
    mock_oa.return_value = mock_arxiv.return_value = mock_crossref.return_value = []

    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Sleep and Memory",
        output_path=str(tmp_path / "report.md"),
        use_llm_summaries=True,
        min_relevance=0.0,
    )
    run_topic_finder(inputs)

    stderr = capsys.readouterr().err
    assert stderr.count("ANTHROPIC_API_KEY not set") == 1
    assert "Claude requested but unavailable" in stderr


@patch("thesis_tools.topic_finder.generate_subquestions")
@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_announces_auto_generated_subquestions(
    mock_ss, mock_oa, mock_arxiv, mock_crossref, mock_generate, tmp_path, capsys
):
    for m in (mock_ss, mock_oa, mock_arxiv, mock_crossref):
        m.return_value = []
    mock_generate.return_value = ["Auto Q1?", "Auto Q2?"]

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Some Working Title",
        style="apa",
        output_path=str(output_path),
        use_llm_summaries=True,
        auto_subquestions=True,
    )

    run_topic_finder(inputs)

    err = capsys.readouterr().err
    assert "Claude suggested (auto-accepted, non-interactive run):" in err
    assert "1. Auto Q1?" in err
    assert "2. Auto Q2?" in err


@patch("thesis_tools.topic_finder.generate_subquestions")
@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_reports_no_auto_generated_subquestions(
    mock_ss, mock_oa, mock_arxiv, mock_crossref, mock_generate, tmp_path, capsys
):
    for m in (mock_ss, mock_oa, mock_arxiv, mock_crossref):
        m.return_value = []
    mock_generate.return_value = []

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Some Working Title",
        style="apa",
        output_path=str(output_path),
        use_llm_summaries=True,
        auto_subquestions=True,
    )

    run_topic_finder(inputs)

    err = capsys.readouterr().err
    assert "Claude didn't return any sub-questions for this topic." in err
