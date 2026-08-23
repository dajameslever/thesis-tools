from thesis_tools.report import ScoredPaper, build_report
from thesis_tools.sources.base import Paper
from thesis_tools.subquestions import SubquestionAnalysis


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


def test_report_includes_compare_and_contrast_table_and_recency():
    old_paper = Paper(title="Foundational Sleep Study", year=2005, authors=["Jane Doe"])
    new_paper = Paper(title="Recent Sleep Study", year=2024, authors=["John Smith"])
    scored = [
        ScoredPaper(paper=old_paper, relevance=0.6, title_similarity=0.2),
        ScoredPaper(paper=new_paper, relevance=0.7, title_similarity=0.3),
    ]
    report = _report_for(scored)
    assert "## Compare and contrast" in report
    assert "| # | Title | Year | Recency | Relevance | Cited by |" in report
    assert "🕰️ Older" in report  # old_paper's per-paper recency tag
    assert "🆕 Recent" in report  # new_paper's per-paper recency tag
    assert "spans 19 years" in report  # 2024 - 2005
    assert "superseded" in report


def test_report_compare_table_includes_stance_column_when_subquestions_present():
    paper = Paper(title="Sleep and Risk-Taking", year=2020, authors=["Jane Doe"], abstract="abstract text")
    scored = [ScoredPaper(paper=paper, relevance=0.5, title_similarity=0.2)]
    analysis = SubquestionAnalysis(sub_questions=["Does X happen?"])
    from thesis_tools.subquestions import StanceResult

    analysis.stances[paper.key()] = {"Does X happen?": StanceResult("supports", "because")}
    analysis.paper_titles[paper.key()] = paper.title

    report = build_report(
        field="Psychology",
        working_title="Sleep and Risk-Taking",
        research_question=None,
        keywords=[],
        style="apa",
        scored_papers=scored,
        sources_used=["semanticscholar"],
        total_found=1,
        subquestion_analysis=analysis,
    )
    assert "Stances" in report
    assert "✅" in report
