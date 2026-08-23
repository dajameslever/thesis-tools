from thesis_tools.report import ScoredPaper, build_report
from thesis_tools.sources.base import Paper


def _report_for(scored_papers):
    return build_report(
        field="Psychology",
        working_title="Sleep Deprivation and Adolescent Decision-Making",
        research_question="Does sleep deprivation impair decision-making in teens?",
        keywords=["sleep", "deprivation", "adolescent", "decision-making"],
        style="apa",
        scored_papers=scored_papers,
        sources_used=["semanticscholar", "openalex"],
        total_found=len(scored_papers),
    )


def test_report_flags_critical_overlap():
    near_duplicate = Paper(title="Sleep Deprivation and Adolescent Decision-Making", year=2019, authors=["Jane Doe"])
    scored = [ScoredPaper(paper=near_duplicate, relevance=0.9, title_similarity=0.95)]
    report = _report_for(scored)
    assert "near-identical" in report.lower()
    assert "Sleep Deprivation and Adolescent Decision-Making" in report


def test_report_no_overlap_reads_as_good_sign():
    unrelated = Paper(title="Economics of Coffee Farming in Brazil", year=2019, authors=["Jane Doe"])
    scored = [ScoredPaper(paper=unrelated, relevance=0.2, title_similarity=0.1)]
    report = _report_for(scored)
    assert "good sign for novelty" in report.lower()


def test_report_includes_summary_and_citation():
    paper = Paper(
        title="Adolescent Sleep Patterns",
        year=2020,
        authors=["Jane Doe"],
        venue="Sleep Journal",
        doi="10.1/x",
    )
    scored = [ScoredPaper(paper=paper, relevance=0.5, title_similarity=0.3, summary="This paper finds X.")]
    report = _report_for(scored)
    assert "This paper finds X." in report
    assert "Doe, J." in report  # APA-formatted citation present
    assert "https://doi.org/10.1/x" in report


def test_report_handles_no_papers_found():
    report = _report_for([])
    assert "no related papers were found" in report.lower()


def test_report_mentions_sciencedirect_and_google_scholar_limitation():
    report = _report_for([])
    assert "ScienceDirect" in report
    assert "Google Scholar" in report
