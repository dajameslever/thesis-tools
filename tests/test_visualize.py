from unittest.mock import patch

from thesis_tools.library.index_store import LibraryEntry, LibraryIndex
from thesis_tools.library.visualize import build_visualization_html, compute_stats, render_html
from thesis_tools.sources.base import Paper


def _entry(
    file_path,
    confidence="verified-doi",
    doi=None,
    title="A Paper",
    year=2023,
    abstract=None,
    sources=None,
    references=None,
    file_type="pdf",
):
    return LibraryEntry(
        file_path=file_path,
        file_hash=f"hash-{file_path}",
        file_type=file_type,
        size_bytes=100,
        indexed_at="2026-01-01T00:00:00",
        confidence=confidence,
        doi=doi,
        paper=Paper(title=title, doi=doi, year=year, abstract=abstract, sources=sources or ["crossref"]),
        references=references or [],
    )


def test_compute_stats_empty_index():
    stats = compute_stats(LibraryIndex())
    assert stats["total"] == 0
    assert stats["weaknesses"] == []


def test_compute_stats_counts_by_confidence_and_source():
    index = LibraryIndex(
        [
            _entry("a.pdf", confidence="verified-doi", doi="10.1/a", sources=["crossref"]),
            _entry("b.pdf", confidence="verified-title-match", sources=["semanticscholar"]),
            _entry("c.pdf", confidence="unresolved", sources=["local-heuristic"]),
        ]
    )
    stats = compute_stats(index)

    assert stats["total"] == 3
    assert stats["by_confidence"] == {"verified-doi": 1, "verified-title-match": 1, "unresolved": 1}
    assert stats["by_source"] == {"crossref": 1, "semanticscholar": 1, "local-heuristic": 1}


def test_compute_stats_detects_duplicate_dois():
    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/x", title="Paper X"),
            _entry("a-copy.pdf", doi="10.1/x", title="Paper X (copy)"),
        ]
    )
    stats = compute_stats(index)
    assert len(stats["duplicates"]) == 1
    levels = [w["level"] for w in stats["weaknesses"]]
    assert "serious" in levels


def test_compute_stats_flags_unresolved_weakness():
    index = LibraryIndex([_entry("a.pdf", confidence="unresolved", title="Mystery Paper")])
    stats = compute_stats(index)
    titles = [w["title"] for w in stats["weaknesses"]]
    assert any("unresolved" in t for t in titles)
    unresolved_weakness = next(w for w in stats["weaknesses"] if "unresolved" in w["title"])
    assert "Mystery Paper" in unresolved_weakness["items"]


def test_compute_stats_flags_no_abstract_weakness_over_threshold():
    index = LibraryIndex([_entry("a.pdf", abstract=None), _entry("b.pdf", abstract=None)])
    stats = compute_stats(index)
    assert any("no abstract" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_no_no_abstract_weakness_under_threshold():
    # Only 1 of 4 missing an abstract (25%) — below the 30% warn threshold.
    index = LibraryIndex(
        [
            _entry("a.pdf", abstract="has one"),
            _entry("b.pdf", abstract="has one"),
            _entry("c.pdf", abstract="has one"),
            _entry("d.pdf", abstract=None),
        ]
    )
    stats = compute_stats(index)
    assert not any("no abstract" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_flags_source_concentration():
    index = LibraryIndex([_entry(f"{i}.pdf", doi=f"10.1/{i}", sources=["crossref"]) for i in range(5)])
    stats = compute_stats(index)
    assert any("single source" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_notes_references_not_fetched():
    index = LibraryIndex([_entry("a.pdf", references=[])])
    stats = compute_stats(index)
    assert stats["references_fetched"] is False
    assert any("not analyzed" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_flags_missing_references_over_threshold():
    index = LibraryIndex(
        [
            _entry(
                "a.pdf",
                doi="10.1/a",
                references=[{"doi": "10.1/missing", "title": "Missing Work", "year": 2000}],
            )
        ]
    )
    stats = compute_stats(index)
    assert stats["coverage"]["missing_references"] == 1
    assert any("aren't in your library" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_flags_old_papers_majority():
    old_year = 2000
    index = LibraryIndex([_entry("a.pdf", year=old_year), _entry("b.pdf", year=old_year)])
    stats = compute_stats(index)
    assert any("years old" in w["title"] for w in stats["weaknesses"])


def test_render_html_empty_index_shows_prompt():
    html = render_html(compute_stats(LibraryIndex()))
    assert "Nothing indexed yet" in html
    assert "<html" in html


def test_render_html_escapes_titles():
    index = LibraryIndex([_entry("a.pdf", confidence="unresolved", title="<script>alert(1)</script>")])
    html = render_html(compute_stats(index))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_html_includes_source_and_confidence_charts():
    index = LibraryIndex([_entry("a.pdf", sources=["arxiv"])])
    html = render_html(compute_stats(index))
    assert "arXiv" in html
    assert "Verified via DOI" in html


def test_build_visualization_html_end_to_end():
    index = LibraryIndex([_entry("a.pdf")])
    html = build_visualization_html(index)
    assert "<!doctype html>" in html
    assert "Library Visualization" in html


def test_frequently_missing_table_links_by_doi_when_known():
    index = LibraryIndex(
        [
            _entry(
                "a.pdf",
                doi="10.1/a",
                references=[
                    {"doi": "10.1/missing", "title": "Missing With DOI", "year": 2001},
                ],
            ),
            _entry(
                "b.pdf",
                doi="10.1/b",
                references=[
                    {"doi": "10.1/missing", "title": "Missing With DOI", "year": 2001},
                ],
            ),
        ]
    )
    stats = compute_stats(index)
    html = render_html(stats)
    assert 'href="https://doi.org/10.1/missing"' in html
    assert "scholar.google.com" in html
    assert "sciencedirect.com" in html


def test_frequently_missing_table_falls_back_to_search_links_without_doi():
    from thesis_tools.library.visualize import _frequently_missing_table

    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", references=[{"doi": None, "title": "No DOI Known", "year": 2001}]),
            _entry("b.pdf", doi="10.1/b", references=[{"doi": None, "title": "No DOI Known", "year": 2001}]),
        ]
    )
    stats = compute_stats(index)
    table_html = _frequently_missing_table(stats["coverage"]["frequently_missing"])
    assert "doi.org" not in table_html
    assert "scholar.google.com" in table_html
    assert "sciencedirect.com" in table_html


def test_unresolved_weakness_includes_search_links():
    index = LibraryIndex([_entry("a.pdf", confidence="unresolved", title="Some Unresolved Paper")])
    html = render_html(compute_stats(index))
    assert "scholar.google.com" in html
    assert "sciencedirect.com" in html


def test_citation_network_empty_when_no_indexed_papers():
    html = render_html(compute_stats(LibraryIndex()))
    assert "No citation data yet" not in html  # empty-index short-circuit happens before this section


def test_citation_network_shows_prompt_when_no_references_fetched():
    index = LibraryIndex([_entry("a.pdf")])
    html = render_html(compute_stats(index))
    assert "No citation data yet" not in html
    # A single indexed paper with no references still gets a node in the graph.
    assert "GRAPH_DATA" in html
    assert '"kind": "indexed"' in html


def test_citation_network_embeds_valid_json_payload():
    import json

    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", references=[{"doi": "10.1/b", "title": "B", "year": 2020}]),
            _entry("b.pdf", doi="10.1/b"),
        ]
    )
    html = render_html(compute_stats(index))

    start = html.index("const GRAPH_DATA = ") + len("const GRAPH_DATA = ")
    end = html.index(";\n", start)
    payload = json.loads(html[start:end])

    assert len(payload["nodes"]) == 2
    assert len(payload["edges"]) == 1
    assert all("links_html" in n for n in payload["nodes"])


def test_citation_network_node_gets_doi_link_when_available():
    index = LibraryIndex([_entry("a.pdf", doi="10.1/a")])
    html = render_html(compute_stats(index))
    assert "https://doi.org/10.1/a" in html


def test_citation_network_gap_node_gets_search_links():
    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", references=[{"doi": None, "title": "Missing Work", "year": 2000}]),
            _entry("b.pdf", doi="10.1/b", references=[{"doi": None, "title": "Missing Work", "year": 2000}]),
        ]
    )
    html = render_html(compute_stats(index))
    assert "scholar.google.com/scholar?q=Missing+Work" in html


def test_compute_stats_without_subquestions_has_empty_coverage():
    index = LibraryIndex([_entry("a.pdf")])
    stats = compute_stats(index)
    assert stats["sub_questions"] == []
    assert stats["subquestion_coverage"] == []


def test_compute_stats_classifies_papers_per_subquestion_using_full_text():
    question = "Does digital transformation affect sustainability targets?"
    supporting_paper = _entry(
        "a.pdf",
        title="Paper A",
        abstract=None,
        references=[],
    )
    supporting_paper.paper.full_text_excerpt = (
        "We find a significant effect of digital transformation on sustainability targets, "
        "consistent with prior theory."
    )
    index = LibraryIndex([supporting_paper])

    stats = compute_stats(index, sub_questions=[question], use_llm=False)

    assert stats["sub_questions"] == [question]
    coverage = stats["subquestion_coverage"][0]
    assert coverage["question"] == question
    assert coverage["supports"] == ["Paper A"]


def test_compute_stats_flags_subquestion_with_no_coverage_as_weakness():
    question = "An entirely unrelated sub-question about coffee farming economics?"
    index = LibraryIndex([_entry("a.pdf", title="Paper A")])

    stats = compute_stats(index, sub_questions=[question], use_llm=False)

    levels_and_titles = [(w["level"], w["title"]) for w in stats["weaknesses"]]
    assert any(level == "serious" and "no supporting paper" in title for level, title in levels_and_titles)


def test_render_html_shows_prompt_when_no_subquestions_configured():
    index = LibraryIndex([_entry("a.pdf")])
    html = render_html(compute_stats(index))
    assert "No sub-questions configured for this run" in html


def test_render_html_shows_question_text_and_gap_message():
    question = "An entirely unrelated sub-question about coffee farming economics?"
    index = LibraryIndex([_entry("a.pdf", title="Paper A")])
    html = render_html(compute_stats(index, sub_questions=[question], use_llm=False))
    assert question in html
    assert "No paper in your library speaks directly to this sub-question" in html


def test_build_visualization_html_anchors_on_subquestions_end_to_end():
    question = "Does X affect Y?"
    paper_entry = _entry("a.pdf", title="Relevant Paper", abstract=None)
    paper_entry.paper.full_text_excerpt = "We find a significant effect of X on Y, consistent with prior theory."
    index = LibraryIndex([paper_entry])

    html = build_visualization_html(index, sub_questions=[question])

    assert question in html
    assert "Relevant Paper" in html


def test_compute_stats_flags_papers_not_linked_to_any_subquestion():
    question = "Does digital transformation affect sustainability?"
    unrelated_entry = _entry("a.pdf", title="Coffee Prices in Brazil", abstract=None)
    unrelated_entry.paper.full_text_excerpt = "This paper is about coffee farming economics, nothing else."
    index = LibraryIndex([unrelated_entry])

    stats = compute_stats(index, sub_questions=[question], use_llm=False)

    assert stats["no_subquestion_coverage_titles"] == ["Coffee Prices in Brazil"]
    assert any("don't relate to any of your sub-questions" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_does_not_flag_papers_that_are_linked():
    question = "Does digital transformation affect sustainability?"
    supporting_entry = _entry("a.pdf", title="DT Paper", abstract=None)
    supporting_entry.paper.full_text_excerpt = (
        "We find a significant effect of digital transformation on sustainability, consistent with theory."
    )
    index = LibraryIndex([supporting_entry])

    stats = compute_stats(index, sub_questions=[question], use_llm=False)

    assert stats["no_subquestion_coverage_titles"] == []
    assert not any("don't relate to any" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_flags_low_relevance_papers():
    index = LibraryIndex(
        [
            _entry("a.pdf", title="Digital Transformation and Sustainability Targets"),
            _entry("b.pdf", title="A Completely Unrelated Coffee Farming Study"),
        ]
    )

    stats = compute_stats(index, research_question="digital transformation sustainability targets")

    assert stats["low_relevance_titles"] == ["A Completely Unrelated Coffee Farming Study"]
    assert any("low relevance to your research question" in w["title"] for w in stats["weaknesses"])


def test_compute_stats_no_relevance_flag_without_research_question():
    index = LibraryIndex([_entry("a.pdf", title="Anything At All")])
    stats = compute_stats(index)
    assert stats["low_relevance_titles"] == []
    assert stats["research_question"] is None


@patch("thesis_tools.subquestions.llm.get_client")
@patch("thesis_tools.subquestions.llm.ask")
def test_compute_stats_reuses_cached_stance_classification(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.return_value = "1: supports - confirms it."
    question = "Does X affect Y?"
    entry = _entry("a.pdf", title="Paper A", abstract="Some abstract about X and Y.")
    index = LibraryIndex([entry])
    cache_path = str(tmp_path / "stance_cache.json")

    compute_stats(index, sub_questions=[question], use_llm=True, stance_cache_path=cache_path)
    assert mock_ask.call_count == 1

    # Same index, same sub-questions, second run -> no new Claude calls.
    compute_stats(index, sub_questions=[question], use_llm=True, stance_cache_path=cache_path)
    assert mock_ask.call_count == 1


@patch("thesis_tools.subquestions.llm.get_client")
@patch("thesis_tools.subquestions.llm.ask")
def test_build_visualization_html_threads_stance_cache_path(mock_ask, mock_get_client, tmp_path):
    mock_get_client.return_value = object()
    mock_ask.return_value = "1: supports - confirms it."
    question = "Does X affect Y?"
    entry = _entry("a.pdf", title="Paper A", abstract="Some abstract about X and Y.")
    index = LibraryIndex([entry])
    cache_path = str(tmp_path / "stance_cache.json")

    build_visualization_html(index, sub_questions=[question], use_llm=True, stance_cache_path=cache_path)
    assert mock_ask.call_count == 1
    assert (tmp_path / "stance_cache.json").is_file()

    build_visualization_html(index, sub_questions=[question], use_llm=True, stance_cache_path=cache_path)
    assert mock_ask.call_count == 1


def test_render_html_shows_low_relevance_and_unlinked_weaknesses():
    question = "Does digital transformation affect sustainability?"
    entry = _entry("a.pdf", title="Coffee Prices in Brazil", abstract=None)
    entry.paper.full_text_excerpt = "This paper is about coffee farming economics, nothing else."
    index = LibraryIndex([entry])

    html = render_html(
        compute_stats(
            index,
            sub_questions=[question],
            use_llm=False,
            research_question="digital transformation sustainability",
        )
    )

    assert "Coffee Prices in Brazil" in html
    assert "don&#x27;t relate to any of your sub-questions" in html
    assert "low relevance to your research question" in html
