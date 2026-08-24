from thesis_tools.library.citation_graph import (
    build_citation_network,
    build_coverage,
    build_internal_links,
    build_mermaid_mindmap,
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
