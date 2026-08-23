from thesis_tools.relevance import (
    keywords_from_text,
    overlap_flag,
    score_relevance,
    title_similarity,
)
from thesis_tools.sources.base import Paper


def test_title_similarity_identical_is_one():
    assert title_similarity("Sleep and Cognition", "Sleep and Cognition") == 1.0


def test_title_similarity_case_insensitive():
    assert title_similarity("Sleep and Cognition", "sleep and cognition") == 1.0


def test_title_similarity_different_strings_is_low():
    assert title_similarity("Sleep and Cognition", "The Economics of Coffee Farming") < 0.4


def test_overlap_flag_thresholds():
    assert overlap_flag(0.95) == "critical"
    assert overlap_flag(0.7) == "high"
    assert overlap_flag(0.5) == "related"
    assert overlap_flag(0.1) == "low"


def test_score_relevance_ranks_matching_title_higher():
    query = "sleep deprivation and adolescent decision making"
    relevant = Paper(title="Sleep Deprivation Impairs Adolescent Decision Making", abstract="")
    irrelevant = Paper(title="The Economics of Coffee Farming in Brazil", abstract="")
    assert score_relevance(query, relevant) > score_relevance(query, irrelevant)


def test_score_relevance_empty_query_is_zero():
    paper = Paper(title="Some Paper")
    assert score_relevance("", paper) == 0.0


def test_keywords_from_text_drops_stopwords_and_dedupes():
    kws = keywords_from_text("The Effect of the Effect on Sleep and Sleep Quality")
    assert "the" not in kws
    assert "of" not in kws
    assert kws.count("sleep") == 1
