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


def _index_with_paper(index_path, title="Relevant Paper", full_text_excerpt=None):
    entry = LibraryEntry(
        file_path="a.pdf",
        file_hash="hash-a",
        file_type="pdf",
        size_bytes=100,
        indexed_at="2026-01-01T00:00:00",
        confidence="verified-doi",
        doi="10.1/a",
        paper=Paper(title=title, doi="10.1/a", year=2023, sources=["crossref"], full_text_excerpt=full_text_excerpt),
    )
    LibraryIndex([entry]).save(index_path)


def test_visualize_library_anchors_on_explicit_subquestions_flag(tmp_path):
    index_path = tmp_path / "library" / "index.json"
    output_path = tmp_path / "library" / "visualization.html"
    project_file = tmp_path / "project.json"
    _index_with_paper(
        index_path,
        title="Relevant Paper",
        full_text_excerpt="This significantly supports the claim that X affects Y, consistent with theory.",
    )

    rc = main(
        [
            "visualize-library",
            "--index-path", str(index_path),
            "--output", str(output_path),
            "--project-file", str(project_file),
            "--sub-questions", "Does X affect Y?",
        ]
    )

    assert rc == 0
    html = output_path.read_text(encoding="utf-8")
    assert "Does X affect Y?" in html
    assert "Relevant Paper" in html


def test_visualize_library_reuses_project_subquestions_when_flag_omitted(tmp_path):
    from thesis_tools.project import ProjectState

    index_path = tmp_path / "library" / "index.json"
    output_path = tmp_path / "library" / "visualization.html"
    project_file = tmp_path / "project.json"
    ProjectState(sub_questions=["Saved question from Part 1?"]).save(str(project_file))
    _index_with_paper(index_path)

    rc = main(
        [
            "visualize-library",
            "--index-path", str(index_path),
            "--output", str(output_path),
            "--project-file", str(project_file),
        ]
    )

    assert rc == 0
    html = output_path.read_text(encoding="utf-8")
    assert "Saved question from Part 1?" in html


def test_visualize_library_no_subquestions_shows_prompt(tmp_path):
    index_path = tmp_path / "library" / "index.json"
    output_path = tmp_path / "library" / "visualization.html"
    project_file = tmp_path / "project.json"
    _index_with_paper(index_path)

    rc = main(
        [
            "visualize-library",
            "--index-path", str(index_path),
            "--output", str(output_path),
            "--project-file", str(project_file),
        ]
    )

    assert rc == 0
    html = output_path.read_text(encoding="utf-8")
    assert "No sub-questions configured for this run" in html
