from thesis_tools.library.citation_graph import (
    build_citation_network,
    build_coverage,
    build_exploration_tree,
    build_internal_links,
    build_mermaid_mindmap,
    gap_relevance,
    split_by_relevance,
)
from thesis_tools.library.index_store import LibraryEntry
from thesis_tools.sources.base import Paper


def _entry(title, doi, references=None, year=2022):
    return LibraryEntry(
        file_path=f"/downloads/{title}.pdf",
        file_hash=f"hash-{title}",
        file_type="pdf",
        size_bytes=100,
        indexed_at="2026-01-01T00:00:00",
        confidence="verified-doi",
        doi=doi,
        paper=Paper(title=title, doi=doi, year=year),
        references=references or [],
    )


def test_build_coverage_counts_included_vs_missing():
    entries = [
        _entry("Paper A", "10.1/a", references=[{"doi": "10.1/b", "title": "Paper B", "year": 2020}]),
        _entry("Paper B", "10.1/b"),
    ]
    coverage = build_coverage(entries)
    assert coverage["total_references"] == 1
    assert coverage["included_references"] == 1
    assert coverage["missing_references"] == 0
    assert coverage["frequently_missing"] == []


def test_build_coverage_surfaces_frequent_gaps():
    entries = [
        _entry("Paper A", "10.1/a", references=[{"doi": "10.1/x", "title": "Foundational Work", "year": 1998}]),
        _entry("Paper B", "10.1/b", references=[{"doi": "10.1/x", "title": "Foundational Work", "year": 1998}]),
    ]
    coverage = build_coverage(entries)
    assert coverage["missing_references"] == 2
    assert len(coverage["frequently_missing"]) == 1
    gap = coverage["frequently_missing"][0]
    assert gap["title"] == "Foundational Work"
    assert set(gap["cited_by"]) == {"Paper A", "Paper B"}


def test_build_coverage_excludes_singly_cited_gaps():
    entries = [_entry("Paper A", "10.1/a", references=[{"doi": "10.1/x", "title": "Rarely Needed", "year": 2001}])]
    coverage = build_coverage(entries)
    assert coverage["frequently_missing"] == []  # cited by only 1 paper, below the threshold


def test_build_mermaid_mindmap_includes_nodes_and_edges():
    entries = [
        _entry("Paper A", "10.1/a", references=[{"doi": "10.1/x", "title": "Foundational Work", "year": 1998}]),
        _entry("Paper B", "10.1/b", references=[{"doi": "10.1/x", "title": "Foundational Work", "year": 1998}]),
    ]
    coverage = build_coverage(entries)
    diagram = build_mermaid_mindmap(entries, coverage)
    assert diagram.startswith("flowchart LR")
    assert "✅" in diagram and "❌" in diagram
    assert "-->" in diagram


def _find_node(network, node_id):
    return next(n for n in network["nodes"] if n["id"] == node_id)


def test_build_citation_network_edge_between_two_indexed_papers():
    entries = [
        _entry("Paper A", "10.1/a", references=[{"doi": "10.1/b", "title": "Paper B", "year": 2020}]),
        _entry("Paper B", "10.1/b"),
    ]
    coverage = build_coverage(entries)
    network = build_citation_network(entries, coverage)

    node_ids = {n["id"] for n in network["nodes"]}
    assert node_ids == {"doi:10.1/a", "doi:10.1/b"}
    assert {"source": "doi:10.1/a", "target": "doi:10.1/b"} in network["edges"]
    a = _find_node(network, "doi:10.1/a")
    assert a["kind"] == "indexed"
    assert a["confidence"] == "verified-doi"


def test_build_citation_network_includes_frequently_missing_gap_nodes():
    entries = [
        _entry("Paper A", "10.1/a", references=[{"doi": "10.1/x", "title": "Foundational Work", "year": 1998}]),
        _entry("Paper B", "10.1/b", references=[{"doi": "10.1/x", "title": "Foundational Work", "year": 1998}]),
    ]
    coverage = build_coverage(entries)
    network = build_citation_network(entries, coverage)

    gap_nodes = [n for n in network["nodes"] if n["kind"] == "gap"]
    assert len(gap_nodes) == 1
    assert gap_nodes[0]["title"] == "Foundational Work"
    assert gap_nodes[0]["cited_by_count"] == 2

    gap_id = gap_nodes[0]["id"]
    assert {"source": "doi:10.1/a", "target": gap_id} in network["edges"]
    assert {"source": "doi:10.1/b", "target": gap_id} in network["edges"]


def test_build_citation_network_excludes_singly_cited_references():
    entries = [_entry("Paper A", "10.1/a", references=[{"doi": "10.1/x", "title": "Rarely Needed", "year": 2001}])]
    coverage = build_coverage(entries)
    network = build_citation_network(entries, coverage)

    assert len(network["nodes"]) == 1  # just Paper A — the one-off reference isn't surfaced as a node
    assert network["edges"] == []


def test_build_citation_network_no_self_loops_or_duplicate_edges():
    entries = [
        _entry("Paper A", "10.1/a", references=[{"doi": "10.1/a", "title": "Paper A", "year": 2022}]),
    ]
    coverage = build_coverage(entries)
    network = build_citation_network(entries, coverage)
    assert network["edges"] == []


def test_build_citation_network_empty_when_no_references_fetched():
    entries = [_entry("Paper A", "10.1/a"), _entry("Paper B", "10.1/b")]
    coverage = build_coverage(entries)
    network = build_citation_network(entries, coverage)
    assert len(network["nodes"]) == 2
    assert network["edges"] == []


def test_build_internal_links_orders_papers_oldest_first():
    entries = [
        _entry("Newest", "10.1/c", year=2022),
        _entry("Oldest", "10.1/a", year=2001),
        _entry("Middle", "10.1/b", year=2010),
    ]
    result = build_internal_links(entries)
    assert [p["title"] for p in result["papers"]] == ["Oldest", "Middle", "Newest"]
    assert [p["index"] for p in result["papers"]] == [0, 1, 2]


def test_build_internal_links_puts_undated_papers_last():
    entries = [_entry("Undated", "10.1/u", year=None), _entry("Dated", "10.1/a", year=2001)]
    result = build_internal_links(entries)
    assert [p["title"] for p in result["papers"]] == ["Dated", "Undated"]


def test_build_internal_links_records_link_and_counts():
    entries = [
        _entry("Old", "10.1/old", year=2000),
        _entry("New", "10.1/new", year=2020, references=[{"doi": "10.1/old", "title": "Old", "year": 2000}]),
    ]
    result = build_internal_links(entries)
    assert result["links"] == [{"source": 1, "target": 0}]  # New (index 1) cites Old (index 0)
    assert result["papers"][1]["cites"] == 1
    assert result["papers"][0]["cited_by"] == 1
    assert result["connected_count"] == 2
    assert result["isolated_count"] == 0


def test_build_internal_links_keeps_isolated_papers():
    entries = [_entry("Alone", "10.1/a", year=2000), _entry("Also Alone", "10.1/b", year=2001)]
    result = build_internal_links(entries)
    assert len(result["papers"]) == 2
    assert result["links"] == []
    assert result["connected_count"] == 0
    assert result["isolated_count"] == 2


def test_build_internal_links_ignores_references_outside_the_library():
    entries = [_entry("A", "10.1/a", references=[{"doi": "10.9/elsewhere", "title": "Elsewhere", "year": 1999}])]
    assert build_internal_links(entries)["links"] == []


def test_build_internal_links_no_self_loops_or_duplicates():
    entries = [
        _entry("Old", "10.1/old", year=2000),
        _entry(
            "New",
            "10.1/new",
            year=2020,
            references=[
                {"doi": "10.1/old", "title": "Old", "year": 2000},
                {"doi": "10.1/old", "title": "Old (again)", "year": 2000},
                {"doi": "10.1/new", "title": "New", "year": 2020},  # cites itself
            ],
        ),
    ]
    assert build_internal_links(entries)["links"] == [{"source": 1, "target": 0}]


def test_build_internal_links_dedupes_the_same_paper_indexed_twice():
    entries = [_entry("Dup", "10.1/dup", year=2000), _entry("Dup (copy)", "10.1/dup", year=2000)]
    assert len(build_internal_links(entries)["papers"]) == 1


QUESTIONS = [
    "Does sleep deprivation affect adolescent decision-making?",
    "Does sleep loss increase risk-taking in adolescents?",
    "Does sleep loss impair working memory?",
    "Do later school start times improve outcomes?",
]


def test_gap_relevance_scores_on_topic_titles_above_off_topic_ones():
    on_topic = gap_relevance("Adolescent sleep and school schedules", QUESTIONS)
    off_topic = gap_relevance("Coffee bean price volatility in Brazil", QUESTIONS)
    assert on_topic > off_topic
    assert off_topic == 0.0


def test_gap_relevance_separates_a_real_match_from_an_incidental_word():
    """The regression that drove the term-weighting: both titles match
    exactly one word in four, but "sleep" is central to the question set and
    "times" is incidental to it, so the scores must differ."""
    real = gap_relevance("Measuring Sleepiness: The Stanford Scale", QUESTIONS)
    incidental = gap_relevance("Urban planning and commute times", QUESTIONS)
    assert real > incidental


def test_gap_relevance_matches_across_word_endings():
    # "sleepiness"/"sleep" and "adolescents"/"adolescent" must not miss.
    assert gap_relevance("Sleepiness in adolescents", QUESTIONS) > 0


def test_gap_relevance_is_zero_without_questions():
    assert gap_relevance("Anything At All", []) == 0.0
    assert gap_relevance("Anything At All", ["", "   "]) == 0.0


def test_gap_relevance_is_stable_as_the_question_set_grows():
    """Normalising by the title, not the question set: adding a sub-question
    that says nothing about a title must not make that title look less
    relevant than it was."""
    one = gap_relevance("Sleep and memory", ["Does sleep loss impair working memory?"])
    plus_unrelated = gap_relevance(
        "Sleep and memory",
        ["Does sleep loss impair working memory?", "Do coffee prices track rainfall in Brazil?"],
    )
    assert plus_unrelated == one


def test_split_by_relevance_partitions_and_sorts_best_first():
    works = [
        {"title": "Coffee bean price volatility in Brazil", "cited_by": ["a", "b"]},
        {"title": "Adolescent sleep and school schedules", "cited_by": ["a"]},
    ]
    on_topic, off_topic = split_by_relevance(works, QUESTIONS)
    assert [w["title"] for w in on_topic] == ["Adolescent sleep and school schedules"]
    assert [w["title"] for w in off_topic] == ["Coffee bean price volatility in Brazil"]
    assert all("relevance" in w for w in on_topic + off_topic)


def test_split_by_relevance_keeps_everything_when_no_questions_configured():
    works = [{"title": "Anything", "cited_by": ["a"]}, {"title": "Anything Else", "cited_by": ["b"]}]
    on_topic, off_topic = split_by_relevance(works, [])
    assert len(on_topic) == 2
    assert off_topic == []


def test_split_by_relevance_threshold_of_zero_keeps_everything():
    works = [{"title": "Coffee bean price volatility in Brazil", "cited_by": ["a"]}]
    on_topic, off_topic = split_by_relevance(works, QUESTIONS, min_relevance=0.0)
    assert len(on_topic) == 1
    assert off_topic == []


def test_build_exploration_tree_splits_held_from_unimported():
    entries = [
        _entry("Held Paper", "10.1/held", year=2010),
        _entry(
            "Citing Paper",
            "10.1/citing",
            year=2020,
            references=[
                {"doi": "10.1/held", "title": "Held Paper", "year": 2010},
                {"doi": "10.9/new", "title": "Adolescent sleep and school schedules", "year": 2005},
            ],
        ),
    ]
    tree = build_exploration_tree(entries, QUESTIONS)
    citing = next(p for p in tree["papers"] if p["title"] == "Citing Paper")
    assert [w["title"] for w in citing["in_library"]] == ["Held Paper"]
    assert [w["title"] for w in citing["to_explore"]] == ["Adolescent sleep and school schedules"]
    assert tree["distinct_to_explore"] == 1


def test_build_exploration_tree_holds_back_off_topic_citations():
    entries = [
        _entry(
            "Citing Paper",
            "10.1/citing",
            year=2020,
            references=[
                {"doi": "10.9/coffee", "title": "Coffee bean price volatility in Brazil", "year": 2018},
                {"doi": "10.9/sleep", "title": "Adolescent sleep and school schedules", "year": 2005},
            ],
        ),
    ]
    tree = build_exploration_tree(entries, QUESTIONS)
    citing = tree["papers"][0]
    assert [w["title"] for w in citing["to_explore"]] == ["Adolescent sleep and school schedules"]
    assert citing["off_topic_count"] == 1
    assert tree["distinct_off_topic"] == 1


def test_build_exploration_tree_filters_nothing_without_questions():
    entries = [
        _entry(
            "Citing Paper",
            "10.1/citing",
            references=[{"doi": "10.9/coffee", "title": "Coffee bean price volatility in Brazil", "year": 2018}],
        ),
    ]
    tree = build_exploration_tree(entries, [])
    assert tree["questions_configured"] is False
    assert tree["papers"][0]["to_explore_total"] == 1
    assert tree["papers"][0]["off_topic_count"] == 0


def test_build_exploration_tree_orders_by_how_much_it_opens_up():
    entries = [
        _entry("Few Leads", "10.1/few", year=2020,
               references=[{"doi": "10.9/a", "title": "Adolescent sleep patterns", "year": 2000}]),
        _entry("Many Leads", "10.1/many", year=2021, references=[
            {"doi": "10.9/b", "title": "Adolescent sleep and school schedules", "year": 2001},
            {"doi": "10.9/c", "title": "Sleep loss and memory in adolescents", "year": 2002},
            {"doi": "10.9/d", "title": "Risk-taking after sleep deprivation", "year": 2003},
        ]),
    ]
    tree = build_exploration_tree(entries, QUESTIONS)
    assert tree["papers"][0]["title"] == "Many Leads"


def test_build_exploration_tree_caps_the_list_per_paper_but_reports_the_total():
    from thesis_tools.library.citation_graph import MAX_EXPLORE_PER_PAPER

    refs = [
        {"doi": f"10.9/{i}", "title": f"Adolescent sleep study number {i}", "year": 2000 + i}
        for i in range(MAX_EXPLORE_PER_PAPER + 6)
    ]
    tree = build_exploration_tree([_entry("Citing", "10.1/citing", references=refs)], QUESTIONS)
    paper = tree["papers"][0]
    assert len(paper["to_explore"]) == MAX_EXPLORE_PER_PAPER
    assert paper["to_explore_total"] == MAX_EXPLORE_PER_PAPER + 6


def test_build_exploration_tree_dedupes_a_reference_listed_twice():
    entries = [
        _entry("Citing", "10.1/citing", references=[
            {"doi": "10.9/x", "title": "Adolescent sleep patterns", "year": 2000},
            {"doi": "10.9/x", "title": "Adolescent sleep patterns (dup)", "year": 2000},
        ])
    ]
    assert tree_total(build_exploration_tree(entries, QUESTIONS)) == 1


def tree_total(tree):
    return tree["papers"][0]["to_explore_total"]


def test_gap_relevance_matches_across_a_hyphenated_compound():
    """"risk-taking" in a question has to match "Risk" in a title — without
    splitting the compound it never does."""
    assert gap_relevance("Development and Risk", ["Does sleep loss increase risk-taking?"]) > 0
