from thesis_tools.summarize import extractive_summary, summarize


def test_extractive_summary_returns_none_for_empty_abstract():
    assert extractive_summary(None, "query") is None
    assert extractive_summary("", "query") is None


def test_extractive_summary_short_abstract_returned_whole():
    abstract = "This paper studies sleep. It finds an effect."
    result = extractive_summary(abstract, "sleep", max_sentences=2)
    assert result == abstract


def test_extractive_summary_picks_most_relevant_sentences():
    abstract = (
        "Coffee prices rose in 2020. "
        "This paper studies adolescent sleep deprivation and decision-making. "
        "Weather patterns affected crop yields. "
        "We find that sleep deprivation impairs risk-based decisions in teenagers."
    )
    result = extractive_summary(abstract, "sleep deprivation decision-making adolescents", max_sentences=2)
    assert "sleep deprivation" in result.lower()
    assert "coffee prices" not in result.lower()


def test_summarize_falls_back_to_extractive_without_llm_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    abstract = "This paper studies sleep. It finds a strong effect on cognition."
    result = summarize(abstract, "Sleep Paper", "sleep cognition", use_llm=True)
    assert result == abstract


def test_summarize_none_abstract_returns_none():
    assert summarize(None, "Title", "query") is None


def test_summarize_falls_back_to_full_text_excerpt_without_abstract():
    excerpt = "This paper studies sleep. It finds a strong effect on cognition."
    result = summarize(None, "Sleep Paper", "sleep cognition", full_text_excerpt=excerpt)
    assert result == excerpt


def test_summarize_prefers_abstract_over_full_text_excerpt_when_both_present():
    abstract = "Abstract version of the summary."
    excerpt = "Completely different full-text excerpt content."
    result = summarize(abstract, "Title", "query", full_text_excerpt=excerpt)
    assert result == abstract


def test_summarize_none_when_neither_abstract_nor_excerpt():
    assert summarize(None, "Title", "query", full_text_excerpt=None) is None
