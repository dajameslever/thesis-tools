import re
from unittest.mock import patch

from thesis_tools.library.index_store import LibraryEntry, LibraryIndex
from thesis_tools.library.visualize import build_literature_matrix, build_visualization_html, compute_stats, render_html
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


def test_connections_section_prompts_when_no_references_fetched():
    index = LibraryIndex([_entry("a.pdf")])
    html = render_html(compute_stats(index))
    assert "How your papers connect" in html
    assert "No reference lists fetched yet" in html


def test_connections_section_says_so_when_nothing_links():
    """References fetched, but none of them point at another indexed paper —
    a real finding about the library, not an empty chart."""
    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", references=[{"doi": "10.9/elsewhere", "title": "Elsewhere", "year": 2000}]),
            _entry("b.pdf", doi="10.1/b"),
        ]
    )
    html = render_html(compute_stats(index))
    assert "cites\nanother one in this library" in html or "another one in this library" in html


def test_connections_section_draws_an_arc_between_two_linked_papers():
    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", title="Newer Paper", year=2022,
                   references=[{"doi": "10.1/b", "title": "Older Paper", "year": 2010}]),
            _entry("b.pdf", doi="10.1/b", title="Older Paper", year=2010),
        ]
    )
    html = render_html(compute_stats(index))
    assert 'class="viz-arc"' in html
    # One arc path, drawn as an elliptical arc above the baseline.
    assert html.count('class="viz-arc-link"') == 1
    assert "1</strong> of <strong>2</strong>" not in html  # both papers are connected
    assert "<strong>2</strong> of <strong>2</strong>" in html
    assert "<strong>1</strong> citation link(s)" in html


def test_connections_arc_is_deterministic_across_runs():
    """The whole reason this is an arc diagram and not a force layout —
    the same index must render byte-identical geometry every time."""
    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", title="A", year=2022, references=[{"doi": "10.1/b", "title": "B", "year": 2010}]),
            _entry("b.pdf", doi="10.1/b", title="B", year=2010),
            _entry("c.pdf", doi="10.1/c", title="C", year=2015),
        ]
    )
    first = render_html(compute_stats(index))
    second = render_html(compute_stats(index))
    extract = lambda h: h[h.index('<svg id="viz-arc"'): h.index("</svg>", h.index('<svg id="viz-arc"'))]
    assert extract(first) == extract(second)


def test_papers_to_consider_ranks_gaps_by_citing_count():
    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", references=[
                {"doi": None, "title": "Cited By Three", "year": 2000},
                {"doi": None, "title": "Cited By Two", "year": 2001},
            ]),
            _entry("b.pdf", doi="10.1/b", references=[
                {"doi": None, "title": "Cited By Three", "year": 2000},
                {"doi": None, "title": "Cited By Two", "year": 2001},
            ]),
            _entry("c.pdf", doi="10.1/c", references=[{"doi": None, "title": "Cited By Three", "year": 2000}]),
        ]
    )
    html = render_html(compute_stats(index))
    assert "Papers worth adding next" in html
    assert "Cited By Three" in html and "Cited By Two" in html
    # Ranked: the 3-citation work is rendered before the 2-citation one.
    assert html.index("Cited By Three") < html.index("Cited By Two")
    assert "<strong>2</strong> such work(s)" in html


def test_papers_to_consider_prompts_when_no_references_fetched():
    html = render_html(compute_stats(LibraryIndex([_entry("a.pdf")])))
    assert "Not analyzed yet" in html


def test_relevance_grid_renders_a_cell_per_paper_and_subquestion():
    question = "Does digital transformation affect sustainability?"
    entry = _entry("a.pdf", title="DT Paper", abstract=None)
    entry.paper.full_text_excerpt = (
        "We find a significant effect of digital transformation on sustainability, consistent with theory."
    )
    html = render_html(
        compute_stats(
            LibraryIndex([entry]),
            sub_questions=[question],
            use_llm=False,
            research_question="digital transformation sustainability",
        )
    )
    assert "Relevance to your questions" in html
    assert 'class="viz-grid"' in html
    assert "DT Paper" in html
    assert question in html  # full text in the numbered key below the grid
    assert "Supports" in html


def test_relevance_grid_cells_carry_a_written_label_not_colour_alone():
    question = "Does X affect Y?"
    entry = _entry("a.pdf", title="Some Paper", abstract="An unrelated abstract about coffee.")
    html = render_html(compute_stats(LibraryIndex([entry]), sub_questions=[question], use_llm=False))
    assert 'class="viz-sr">Unrelated<' in html


def test_relevance_grid_shows_relevance_bar_only_with_a_research_question():
    entry = _entry("a.pdf", title="Some Paper")
    # Assert on the rendered element, not the class name — the stylesheet
    # carries the rule either way.
    with_rq = render_html(compute_stats(LibraryIndex([entry]), research_question="some paper topic"))
    assert '<div class="viz-relbar-fill"' in with_rq
    assert ">Relevance</th>" in with_rq

    without_rq = render_html(compute_stats(LibraryIndex([entry]), sub_questions=["Does X affect Y?"], use_llm=False))
    assert '<div class="viz-relbar-fill"' not in without_rq
    assert ">Relevance</th>" not in without_rq


def test_relevance_grid_prompts_when_nothing_to_score_against():
    html = render_html(compute_stats(LibraryIndex([_entry("a.pdf")])))
    assert "No research question or sub-questions configured" in html


def test_relevance_rows_sorted_most_relevant_first():
    stats = compute_stats(
        LibraryIndex(
            [
                _entry("a.pdf", title="A Completely Unrelated Coffee Farming Study"),
                _entry("b.pdf", title="Digital Transformation and Sustainability Targets"),
            ]
        ),
        research_question="digital transformation sustainability targets",
    )
    titles = [r["title"] for r in stats["relevance_rows"]]
    assert titles[0] == "Digital Transformation and Sustainability Targets"


def test_relevance_grid_caps_rows_and_points_at_the_excel_matrix():
    from thesis_tools.library.visualize import MAX_HEATMAP_ROWS

    entries = [_entry(f"{i}.pdf", title=f"Paper {i:03d}") for i in range(MAX_HEATMAP_ROWS + 5)]
    html = render_html(compute_stats(LibraryIndex(entries), research_question="paper"))
    assert f"Showing the {MAX_HEATMAP_ROWS} most relevant of {MAX_HEATMAP_ROWS + 5} paper(s)" in html


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


def test_compute_stats_stores_stance_analysis_for_matrix_reuse():
    question = "Does digital transformation affect sustainability?"
    entry = _entry("a.pdf", title="Paper A")
    stats_with = compute_stats(LibraryIndex([entry]), sub_questions=[question], use_llm=False)
    assert stats_with["_stance_analysis"] is not None

    stats_without = compute_stats(LibraryIndex([entry]))
    assert stats_without["_stance_analysis"] is None


def test_build_literature_matrix_reuses_stats_stance_analysis():
    question = "Does digital transformation affect sustainability?"
    entry = _entry("a.pdf", title="Paper A", abstract="About digital transformation and sustainability.")
    stats = compute_stats(LibraryIndex([entry]), sub_questions=[question], use_llm=False)

    wb = build_literature_matrix(LibraryIndex([entry]), stats, style="apa")
    ws = wb.active
    header = next(ws.iter_rows(values_only=True))
    assert header[-1] == f"Q: {question}"


def test_render_html_includes_download_link_when_matrix_filename_given():
    entry = _entry("a.pdf", title="Paper A")
    html = render_html(compute_stats(LibraryIndex([entry])), matrix_filename="literature_matrix.xlsx")
    assert 'href="literature_matrix.xlsx" download' in html
    assert "Download as Excel" in html


def test_render_html_omits_download_link_without_matrix_filename():
    entry = _entry("a.pdf", title="Paper A")
    html = render_html(compute_stats(LibraryIndex([entry])))
    assert "Download as Excel" not in html


def test_render_html_omits_download_link_when_index_empty_even_with_filename():
    html = render_html(compute_stats(LibraryIndex()), matrix_filename="literature_matrix.xlsx")
    assert "Download as Excel" not in html


def test_build_visualization_html_threads_matrix_filename():
    entry = _entry("a.pdf", title="Paper A")
    html = build_visualization_html(LibraryIndex([entry]), matrix_filename="literature_matrix.xlsx")
    assert 'href="literature_matrix.xlsx" download' in html


def test_arc_nodes_have_a_comfortable_hit_target_not_the_bare_dot():
    """Regression: the node dot is 9px across, so hovering it meant landing
    on a pinpoint — and the gap between the dot and its tick number was
    dead. Each node carries an invisible hit column instead."""
    import re

    index = LibraryIndex(
        [
            _entry("a.pdf", doi="10.1/a", title="A", year=2022, references=[{"doi": "10.1/b", "title": "B", "year": 2010}]),
            _entry("b.pdf", doi="10.1/b", title="B", year=2010),
        ]
    )
    html = render_html(compute_stats(index))
    widths = [float(w) for w in re.findall(r'class="viz-arc-hit"[^>]*width="([\d.]+)"', html)]
    assert len(widths) == 2
    assert all(w >= 24 for w in widths)


def test_arc_diagram_handles_a_single_paper():
    """A one-paper library makes the node spacing zero — the hit-column
    width must still come out positive rather than collapsing."""
    index = LibraryIndex([_entry("a.pdf", doi="10.1/a", references=[{"doi": "10.9/x", "title": "X", "year": 1999}])])
    html = render_html(compute_stats(index))
    assert 'class="viz-arc-hit"' not in html  # no links, so the short-circuit message shows instead
    assert "None of your 1 indexed paper(s) cites" in html


def test_bar_labels_are_truncated_to_fit_their_column():
    from thesis_tools.library.visualize import _fit_label

    long_label = "Sleep and Human Performance: A Foundational Review of Everything (1998)"
    fitted = _fit_label(long_label, 330)
    assert fitted.endswith("…")
    assert len(fitted) < len(long_label)
    # A label that already fits is left alone.
    assert _fit_label("Short (2001)", 330) == "Short (2001)"


def test_bars_are_square_against_the_baseline():
    """Rounding all four corners detaches a bar from the axis it is
    measured from — only the data end is rounded."""
    from thesis_tools.library.visualize import _bar_path

    path = _bar_path(100, 10, 200, 22, "var(--viz-accent)")
    assert path.startswith('<path d="M 100.0 10.0 H ')
    assert 'rx="4"' not in path
    assert path.count(" A ") == 2  # one rounded corner at each end of the data end


_Q = "Does sleep deprivation affect adolescent decision-making?"


def _citing(file_path, title, refs):
    return _entry(file_path, doi=f"10.1/{file_path}", title=title, references=refs)


def _section(html, heading):
    """Just this section — slicing to the end of the document would sweep in
    the bar charts of every section below it."""
    start = html.index(f"<h2>{heading}</h2>")
    end = html.find("<h2>", start + 1)
    return html[start:end if end != -1 else len(html)]


def test_exploration_section_lists_unimported_citations_as_branches():
    index = LibraryIndex(
        [
            _citing("a.pdf", "Sleep deprivation in adolescents", [
                {"doi": "10.9/new", "title": "Adolescent sleep and school schedules", "year": 2005},
            ]),
        ]
    )
    html = render_html(compute_stats(index, research_question=_Q))
    assert "Where to explore next" in html
    assert 'class="viz-branch"' in html
    assert "Adolescent sleep and school schedules" in html
    assert "1 to explore" in html
    assert "distinct work(s) are cited but not imported" in html


def test_exploration_section_holds_back_off_topic_citations():
    index = LibraryIndex(
        [
            _citing("a.pdf", "Sleep deprivation in adolescents", [
                {"doi": "10.9/coffee", "title": "Coffee bean price volatility in Brazil", "year": 2018},
                {"doi": "10.9/sleep", "title": "Adolescent sleep and school schedules", "year": 2005},
            ]),
        ]
    )
    html = render_html(compute_stats(index, research_question=_Q))
    assert "Adolescent sleep and school schedules" in html
    assert "Coffee bean price volatility in Brazil" not in html
    assert "scored off-topic" in html


def test_exploration_section_filters_nothing_without_a_question():
    index = LibraryIndex(
        [
            _citing("a.pdf", "Some Paper", [
                {"doi": "10.9/coffee", "title": "Coffee bean price volatility in Brazil", "year": 2018},
            ]),
        ]
    )
    html = render_html(compute_stats(index))
    assert "Coffee bean price volatility in Brazil" in html
    assert "No research question or sub-questions configured, so nothing is filtered" in html


def test_exploration_section_prompts_when_no_references_fetched():
    html = render_html(compute_stats(LibraryIndex([_entry("a.pdf")]), research_question=_Q))
    assert "Where to explore next" in html
    assert "No reference lists fetched yet" in html


def test_min_gap_relevance_zero_keeps_off_topic_citations():
    index = LibraryIndex(
        [
            _citing("a.pdf", "Sleep deprivation in adolescents", [
                {"doi": "10.9/coffee", "title": "Coffee bean price volatility in Brazil", "year": 2018},
            ]),
        ]
    )
    filtered = render_html(compute_stats(index, research_question=_Q))
    assert "Coffee bean price volatility in Brazil" not in filtered

    unfiltered = render_html(compute_stats(index, research_question=_Q, min_gap_relevance=0.0))
    assert "Coffee bean price volatility in Brazil" in unfiltered


def test_papers_to_consider_excludes_off_topic_gaps_but_keeps_them_reachable():
    refs = [
        {"doi": "10.9/coffee", "title": "Coffee bean price volatility in Brazil", "year": 2018},
        {"doi": "10.9/sleep", "title": "Adolescent sleep and school schedules", "year": 2005},
    ]
    index = LibraryIndex([_citing("a.pdf", "Paper A", refs), _citing("b.pdf", "Paper B", refs)])
    html = render_html(compute_stats(index, research_question=_Q))
    section = _section(html, "Papers worth adding next")
    assert "Adolescent sleep and school schedules" in section
    # Held back from the ranked list, but still one click away.
    assert "scored off-topic against your questions and are held back" in section
    assert "Show the 1 held back as off-topic" in section


def test_papers_to_consider_bars_stay_in_citation_count_order():
    """Relevance is the filter, not the ranking — a bar chart out of length
    order is unreadable whatever it was sorted by."""
    import re

    common = {"doi": "10.9/common", "title": "Adolescent sleep and school schedules", "year": 2005}
    rare = {"doi": "10.9/rare", "title": "Sleep loss and adolescent memory", "year": 2009}
    index = LibraryIndex(
        [
            _citing("a.pdf", "Paper A", [common, rare]),
            _citing("b.pdf", "Paper B", [common, rare]),
            _citing("c.pdf", "Paper C", [common]),
        ]
    )
    html = render_html(compute_stats(index, research_question=_Q))
    section = _section(html, "Papers worth adding next")
    counts = [int(c) for c in re.findall(r'class="viz-bar-count">(\d+)<', section)]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 3


def _themed_stats(engaged_titles=()):
    from thesis_tools.library.visualize import compute_stats
    from thesis_tools.library.index_store import LibraryEntry, LibraryIndex
    from thesis_tools.sources.base import Paper

    specs = [
        ("Generative AI in travel planning", "Generative AI reshapes travel planning."),
        ("Travel planning with generative AI assistants", "Generative AI assistants and travel planning."),
        ("Supply chain logistics digitalisation", "Supply chain logistics outside tourism."),
        ("Logistics and supply chain platforms", "Supply chain logistics platforms."),
    ]
    entries = [
        LibraryEntry(
            file_path=f"/library/p{i}.pdf", file_hash=str(i), file_type="pdf", size_bytes=1,
            indexed_at="2026-01-01T00:00:00", confidence="verified-doi", doi=f"10.1/{i}",
            paper=Paper(title=t, doi=f"10.1/{i}", year=2024, abstract=a, sources=["crossref"]),
        )
        for i, (t, a) in enumerate(specs)
    ]
    return compute_stats(LibraryIndex(entries), research_question="How does AI affect travel planning?")


def test_themes_carry_the_papers_that_use_them():
    stats = _themed_stats()
    themes = {t["label"]: t for t in stats["themes"]}

    assert "travel planning" in themes
    titles = {p["title"] for p in themes["travel planning"]["papers"]}
    assert titles == {"Generative AI in travel planning", "Travel planning with generative AI assistants"}


def test_each_theme_paper_offers_a_way_to_open_it():
    stats = _themed_stats()
    paper = stats["themes"][0]["papers"][0]
    assert paper["file_path"].endswith(".pdf")
    assert paper["doi"]


def test_the_rendered_cloud_links_every_chip_to_its_own_panel():
    from thesis_tools.library.visualize import render_html

    html = render_html(_themed_stats())

    assert "Themes across your library" in html
    assert 'class="viz-theme-chip"' in html
    # Every chip points at a panel that exists, so no click can land nowhere.
    controls = set(re.findall(r'aria-controls="(viz-theme-panel-\d+)"', html))
    panels = set(re.findall(r'id="(viz-theme-panel-\d+)"', html))
    assert controls and controls <= panels


def test_a_chip_carries_its_count_so_reach_is_never_size_alone():
    from thesis_tools.library.visualize import render_html

    html = render_html(_themed_stats())
    assert 'class="viz-theme-count"' in html


def test_the_cloud_degrades_to_every_panel_open_without_scripting():
    """A cloud that does nothing when clicked is worse than a list."""
    from thesis_tools.library.visualize import render_html

    html = render_html(_themed_stats())
    assert "viz-section viz-no-js" in html
    assert ".viz-no-js .viz-theme-panel { display: block; }" in html
    assert "section.classList.remove('viz-no-js')" in html


def test_a_library_with_no_recurring_phrase_says_so():
    from thesis_tools.library.visualize import compute_stats, render_html
    from thesis_tools.library.index_store import LibraryEntry, LibraryIndex
    from thesis_tools.sources.base import Paper

    index = LibraryIndex([
        LibraryEntry(file_path="a.pdf", file_hash="h", file_type="pdf", size_bytes=1,
                     indexed_at="2026-01-01T00:00:00", confidence="verified-doi", doi="10.1/a",
                     paper=Paper(title="A singular topic", doi="10.1/a", year=2024))
    ])
    stats = compute_stats(index)
    assert stats["themes"] == []
    assert "No recurring themes found" in render_html(stats)


def test_theme_font_size_maps_reach_onto_the_readable_band():
    from thesis_tools.library.visualize import (
        THEME_MAX_FONT_PX,
        THEME_MIN_FONT_PX,
        _theme_font_size,
    )

    assert _theme_font_size(2, 2, 10) == THEME_MIN_FONT_PX
    assert _theme_font_size(10, 2, 10) == THEME_MAX_FONT_PX
    assert THEME_MIN_FONT_PX < _theme_font_size(6, 2, 10) < THEME_MAX_FONT_PX
    # Every theme having the same reach must not collapse to the floor.
    assert _theme_font_size(3, 3, 3) > THEME_MIN_FONT_PX


def test_theme_panels_never_repeat_a_paper():
    """The reported bug, end to end: a paper saved to two files appeared
    twice in every theme panel it reached, and inflated the chip count."""
    from thesis_tools.library.visualize import compute_stats, render_html
    from thesis_tools.library.index_store import LibraryEntry, LibraryIndex
    from thesis_tools.sources.base import Paper

    paper = Paper(title="Travel planning by algorithms", doi="10.1/a", year=2026,
                  abstract="Travel planning by algorithms.")
    other = Paper(title="Agentic travel planning", doi="10.1/b", year=2025,
                  abstract="Travel planning and agents.")
    entries = [
        LibraryEntry(file_path=f"/lib/{p.doi}-{i}.pdf", file_hash=f"{p.doi}{i}", file_type="pdf",
                     size_bytes=1, indexed_at="2026-01-01T00:00:00", confidence="verified-doi",
                     doi=p.doi, paper=p)
        for p in (paper, other) for i in range(3)
    ]

    stats = compute_stats(LibraryIndex(entries))
    theme = {t["label"]: t for t in stats["themes"]}["Travel planning"]

    titles = [p["title"] for p in theme["papers"]]
    assert sorted(titles) == ["Agentic travel planning", "Travel planning by algorithms"]
    assert len(titles) == len(set(titles))

    # The chip count and the panel must agree — the count is the same list.
    html = render_html(stats)
    assert f'>{len(theme["papers"])}</span>' in html
