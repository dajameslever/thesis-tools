import json

from thesis_tools.cli import main
from thesis_tools.project import ProjectState


def test_configure_non_interactive_sets_style_and_field(tmp_path, capsys):
    project_file = tmp_path / "project.json"
    rc = main([
        "configure",
        "--field", "Psychology",
        "--style", "ieee",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0
    assert project_file.is_file()

    state = ProjectState.load(str(project_file))
    assert state.field == "Psychology"
    assert state.style == "ieee"
    assert state.working_title is None  # untouched

    out = capsys.readouterr().out
    assert "IEEE" in out


def test_configure_show_does_not_modify_file(tmp_path, capsys):
    project_file = tmp_path / "project.json"
    ProjectState(field="Psychology", style="apa").save(str(project_file))
    before = project_file.read_text()

    rc = main(["configure", "--show", "--project-file", str(project_file)])
    assert rc == 0
    assert project_file.read_text() == before

    out = capsys.readouterr().out
    assert "Psychology" in out
    assert "APA" in out


def test_configure_non_interactive_preserves_existing_unset_flags(tmp_path):
    project_file = tmp_path / "project.json"
    ProjectState(field="Psychology", working_title="Old Title", style="mla").save(str(project_file))

    rc = main([
        "configure",
        "--style", "ieee",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    state = ProjectState.load(str(project_file))
    assert state.style == "ieee"
    assert state.field == "Psychology"  # untouched
    assert state.working_title == "Old Title"  # untouched


def test_configure_llm_toggle_persists_explicit_false(tmp_path):
    project_file = tmp_path / "project.json"
    ProjectState(use_llm=True).save(str(project_file))

    rc = main([
        "configure",
        "--no-llm-summaries",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    state = ProjectState.load(str(project_file))
    assert state.use_llm is False


def test_configure_sub_questions_are_split_on_semicolons(tmp_path):
    project_file = tmp_path / "project.json"
    rc = main([
        "configure",
        "--sub-questions", "Does A happen?;Does B happen?",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    state = ProjectState.load(str(project_file))
    assert state.sub_questions == ["Does A happen?", "Does B happen?"]


def test_topic_finder_non_interactive_uses_configured_field_and_title(tmp_path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"

    rc = main([
        "configure",
        "--field", "Psychology",
        "--title", "Sleep and Memory",
        "--style", "ieee",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    with patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search", return_value=[]), \
         patch("thesis_tools.sources.openalex.OpenAlexClient.search", return_value=[]), \
         patch("thesis_tools.sources.crossref.CrossrefClient.search", return_value=[]), \
         patch("thesis_tools.sources.arxiv.ArxivClient.search", return_value=[]):
        rc = main(["topic-finder", "--project-file", str(project_file), "--non-interactive"])
    assert rc == 0

    reports = list((tmp_path / "output").glob("*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert "**Field:** Psychology" in text
    assert "**Proposed working title:** Sleep and Memory" in text
    assert "**Citation style:** IEEE" in text
