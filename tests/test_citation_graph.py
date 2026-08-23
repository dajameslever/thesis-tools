from thesis_tools.library.citation_graph import build_citation_network, build_coverage, build_mermaid_mindmap
from thesis_tools.library.index_store import LibraryEntry
from thesis_tools.sources.base import Paper


def _entry(title, doi, references=None):
    return LibraryEntry(
        file_path=f"/downloads/{title}.pdf",
        file_hash=f"hash-{title}",
        file_type="pdf",
        size_bytes=100,
        indexed_at="2026-01-01T00:00:00",
        confidence="verified-doi",
        doi=doi,
        paper=Paper(title=title, doi=doi, year=2022),
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
