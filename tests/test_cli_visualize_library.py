from thesis_tools.cli import main
from thesis_tools.library.index_store import LibraryEntry, LibraryIndex
from thesis_tools.sources.base import Paper


def test_visualize_library_errors_when_no_index(tmp_path, capsys):
    missing = tmp_path / "library" / "index.json"
    rc = main(["visualize-library", "--index-path", str(missing)])
    assert rc == 2
    assert "no index found" in capsys.readouterr().err


def test_visualize_library_writes_html(tmp_path):
    index_path = tmp_path / "library" / "index.json"
    output_path = tmp_path / "library" / "visualization.html"

    index = LibraryIndex(
        [
            LibraryEntry(
                file_path="a.pdf",
                file_hash="hash-a",
                file_type="pdf",
                size_bytes=100,
                indexed_at="2026-01-01T00:00:00",
                confidence="verified-doi",
                doi="10.1/a",
                paper=Paper(title="A Paper", doi="10.1/a", year=2023, sources=["crossref"]),
            )
        ]
    )
    index.save(index_path)

    rc = main(["visualize-library", "--index-path", str(index_path), "--output", str(output_path)])

    assert rc == 0
    assert output_path.is_file()
    html = output_path.read_text(encoding="utf-8")
    assert "Library Visualization" in html
    assert "Crossref" in html


def test_visualize_library_default_output_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    index_path = tmp_path / "library" / "index.json"
    LibraryIndex().save(index_path)

    rc = main(["visualize-library", "--index-path", str(index_path)])

    assert rc == 0
    assert (tmp_path / "library" / "visualization.html").is_file()
