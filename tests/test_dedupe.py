from thesis_tools.dedupe import dedupe_papers
from thesis_tools.sources.base import Paper


def test_dedupes_exact_doi_case_insensitive():
    a = Paper(title="Sleep and Cognition", doi="10.1000/ABC", sources=["semanticscholar"])
    b = Paper(title="Sleep and Cognition", doi="10.1000/abc", sources=["openalex"])
    result = dedupe_papers([a, b])
    assert len(result) == 1
    assert set(result[0].sources) == {"semanticscholar", "openalex"}


def test_dedupes_fuzzy_title_same_year_no_doi():
    a = Paper(title="Deep Learning for Sleep Stage Classification", year=2021, sources=["arxiv"])
    b = Paper(title="Deep learning for sleep stage classification.", year=2021, sources=["crossref"])
    result = dedupe_papers([a, b])
    assert len(result) == 1


def test_does_not_merge_different_papers():
    a = Paper(title="Deep Learning for Sleep Stage Classification", year=2021)
    b = Paper(title="A Survey of Reinforcement Learning Methods", year=2021)
    result = dedupe_papers([a, b])
    assert len(result) == 2


def test_does_not_merge_same_title_different_years():
    a = Paper(title="A Review of Machine Learning in Healthcare", year=2015)
    b = Paper(title="A Review of Machine Learning in Healthcare", year=2023)
    result = dedupe_papers([a, b])
    assert len(result) == 2


def test_merge_prefers_richer_abstract():
    a = Paper(title="Sleep and Cognition", doi="10.1/x", abstract=None, sources=["a"])
    b = Paper(title="Sleep and Cognition", doi="10.1/x", abstract="A full abstract here.", sources=["b"])
    result = dedupe_papers([a, b])
    assert result[0].abstract == "A full abstract here."
