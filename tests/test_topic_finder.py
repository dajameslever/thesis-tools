import json
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


@patch("thesis_tools.topic_finder.download_papers")
@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_downloads_papers_when_opted_in(
    mock_ss, mock_oa, mock_arxiv, mock_crossref, mock_download, tmp_path
):
    mock_ss.return_value = [
        Paper(
            title="Open Access Paper On Sleep",
            year=2021,
            abstract="An open access paper about sleep and decision-making.",
            pdf_url="https://example.org/oa.pdf",
            sources=["semanticscholar"],
        )
    ]
    mock_oa.return_value = []
    mock_arxiv.return_value = []
    mock_crossref.return_value = []
    mock_download.return_value = 1

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Sleep and Decision-Making",
        style="apa",
        output_path=str(output_path),
        download_papers=True,
        download_dir=str(tmp_path / "processed"),
    )

    run_topic_finder(inputs)

    mock_download.assert_called_once()
    args, kwargs = mock_download.call_args
    downloaded_papers = args[0]
    assert len(downloaded_papers) == 1
    assert downloaded_papers[0].pdf_url == "https://example.org/oa.pdf"
    assert kwargs["dest_dir"] == str(tmp_path / "processed")


@patch("thesis_tools.topic_finder.download_papers")
@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_skips_download_when_not_opted_in(
    mock_ss, mock_oa, mock_arxiv, mock_crossref, mock_download, tmp_path
):
    mock_ss.return_value = [
        Paper(
            title="Open Access Paper On Sleep",
            year=2021,
            abstract="An open access paper about sleep and decision-making.",
            pdf_url="https://example.org/oa.pdf",
            sources=["semanticscholar"],
        )
    ]
    mock_oa.return_value = []
    mock_arxiv.return_value = []
    mock_crossref.return_value = []

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Sleep and Decision-Making",
        style="apa",
        output_path=str(output_path),
    )

    run_topic_finder(inputs)

    mock_download.assert_not_called()


@patch("thesis_tools.topic_finder.index_known_papers")
@patch("thesis_tools.topic_finder.download_papers")
@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_indexes_downloaded_papers_into_library(
    mock_ss, mock_oa, mock_arxiv, mock_crossref, mock_download, mock_index_known, tmp_path
):
    mock_ss.return_value = [
        Paper(
            title="Open Access Paper On Sleep",
            year=2021,
            abstract="An open access paper about sleep and decision-making.",
            pdf_url="https://example.org/oa.pdf",
            sources=["semanticscholar"],
        )
    ]
    mock_oa.return_value = []
    mock_arxiv.return_value = []
    mock_crossref.return_value = []
    mock_download.return_value = 1
    mock_index_known.return_value = 1

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Sleep and Decision-Making",
        style="apa",
        output_path=str(output_path),
        download_papers=True,
        download_dir=str(tmp_path / "processed"),
        library_index_path=str(tmp_path / "library" / "index.json"),
    )

    run_topic_finder(inputs)

    mock_index_known.assert_called_once()
    args, kwargs = mock_index_known.call_args
    indexed_papers = args[0]
    assert len(indexed_papers) == 1
    assert indexed_papers[0].pdf_url == "https://example.org/oa.pdf"
    assert kwargs["dest_dir"] == str(tmp_path / "processed")
    assert kwargs["index_path"] == str(tmp_path / "library" / "index.json")


@patch("thesis_tools.topic_finder.index_known_papers")
@patch("thesis_tools.topic_finder.download_papers")
@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_skips_library_indexing_when_download_not_opted_in(
    mock_ss, mock_oa, mock_arxiv, mock_crossref, mock_download, mock_index_known, tmp_path
):
    mock_ss.return_value = [
        Paper(
            title="Some Paper",
            year=2021,
            abstract="An abstract.",
            pdf_url="https://example.org/oa.pdf",
            sources=["semanticscholar"],
        )
    ]
    mock_oa.return_value = []
    mock_arxiv.return_value = []
    mock_crossref.return_value = []

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Some Paper",
        style="apa",
        output_path=str(output_path),
    )

    run_topic_finder(inputs)

    mock_download.assert_not_called()
    mock_index_known.assert_not_called()


def test_topic_finder_inputs_default_library_index_path():
    inputs = TopicFinderInputs(field="Psychology", working_title="Some Title")
    assert inputs.library_index_path == "library/index.json"


def test_topic_finder_inputs_default_model_tiers():
    inputs = TopicFinderInputs(field="Psychology", working_title="Some Title")
    assert inputs.llm_model == "claude-sonnet-5"
    assert inputs.extraction_llm_model == "claude-haiku-4-5"


@patch("thesis_tools.topic_finder.summarize")
@patch("thesis_tools.sources.crossref.CrossrefClient.search")
@patch("thesis_tools.sources.arxiv.ArxivClient.search")
@patch("thesis_tools.sources.openalex.OpenAlexClient.search")
@patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search")
def test_run_topic_finder_summarizes_with_extraction_model_not_llm_model(
    mock_ss, mock_oa, mock_arxiv, mock_crossref, mock_summarize, tmp_path
):
    mock_ss.return_value = [Paper(title="Some Title", year=2023, abstract="An abstract.", sources=["crossref"])]
    mock_oa.return_value = []
    mock_arxiv.return_value = []
    mock_crossref.return_value = []
    mock_summarize.return_value = "a summary"

    output_path = tmp_path / "report.md"
    inputs = TopicFinderInputs(
        field="Psychology",
        working_title="Some Title",
        style="apa",
        output_path=str(output_path),
        min_relevance=0.0,
        llm_model="claude-sonnet-5",
        extraction_llm_model="claude-haiku-4-5",
    )

    run_topic_finder(inputs)

    mock_summarize.assert_called_once()
    _, kwargs = mock_summarize.call_args
    assert kwargs["model"] == "claude-haiku-4-5"


def test_every_source_queried_is_recorded_in_the_search_log(tmp_path, monkeypatch):
    """One row per source, so the log shows where a term was tried, not just
    that it was."""
    monkeypatch.chdir(tmp_path)
    from thesis_tools.search_log import read_log

    log_path = tmp_path / "search-log.csv"
    inputs = TopicFinderInputs(
        field="tourism", working_title="AI in travel planning",
        research_question="How does AI affect travel planning?",
        sources=["semanticscholar", "arxiv"], use_llm_summaries=False,
        output_path=str(tmp_path / "report.md"), search_log_path=str(log_path),
    )
    with patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search",
               return_value=[Paper(title="AI travel planning study", year=2024, doi="10.1/a")]), \
         patch("thesis_tools.sources.arxiv.ArxivClient.search", return_value=[]):
        run_topic_finder(inputs)

    rows = read_log(str(log_path))
    assert [r["Location searched"] for r in rows] == ["semanticscholar", "arxiv"]
    assert [r["Results"] for r in rows] == ["1", "0"]
    assert all(r["Run output"] == str(tmp_path / "report.md") for r in rows)
    assert all(r["Search term"] for r in rows)


def test_a_reanalyze_run_logs_nothing_because_it_searched_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from thesis_tools.search_log import read_log

    log_path = tmp_path / "search-log.csv"
    cache = tmp_path / "prior.papers.json"
    cache.write_text(json.dumps({
        "sources_used": ["semanticscholar"],
        "papers": [Paper(title="A cached paper", year=2024, doi="10.1/a").__dict__],
    }), encoding="utf-8")

    run_topic_finder(TopicFinderInputs(
        field="tourism", working_title="AI in travel planning",
        research_question="How does AI affect travel planning?",
        use_llm_summaries=False, reanalyze_from=str(cache),
        output_path=str(tmp_path / "report.md"), search_log_path=str(log_path),
    ))

    assert read_log(str(log_path)) == []


def test_the_search_log_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    log_path = tmp_path / "search-log.csv"
    with patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search",
               return_value=[Paper(title="AI travel planning study", year=2024, doi="10.1/a")]):
        run_topic_finder(TopicFinderInputs(
            field="tourism", working_title="AI in travel planning",
            research_question="How does AI affect travel planning?",
            sources=["semanticscholar"], use_llm_summaries=False,
            output_path=str(tmp_path / "report.md"), search_log_path=str(log_path),
            write_search_log=False,
        ))
    assert not log_path.exists()
