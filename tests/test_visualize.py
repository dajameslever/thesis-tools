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
