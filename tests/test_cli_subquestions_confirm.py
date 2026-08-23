from unittest.mock import patch

from thesis_tools.cli import _generate_and_confirm_subquestions
from thesis_tools.project import ProjectState


def _project(**overrides):
    state = ProjectState()
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_confirm_accepts_suggested_questions(capsys):
    suggested = ["Q1?", "Q2?", "Q3?"]
    with patch("thesis_tools.cli.generate_subquestions", return_value=suggested), \
         patch("builtins.input", return_value="y"):
        result = _generate_and_confirm_subquestions("Working Title", "RQ", _project())

    assert result == suggested
    out = capsys.readouterr().out
    assert "Claude suggests:" in out
    assert "1. Q1?" in out
    assert "2. Q2?" in out


def test_confirm_declines_and_provides_own_questions():
    suggested = ["Q1?", "Q2?"]
    answers = iter(["n", "My own Q1?; My own Q2?"])
    with patch("thesis_tools.cli.generate_subquestions", return_value=suggested), \
         patch("builtins.input", lambda *_: next(answers)):
        result = _generate_and_confirm_subquestions("Working Title", None, _project())

    assert result == ["My own Q1?", "My own Q2?"]


def test_confirm_declines_and_skips_with_blank_answer():
    suggested = ["Q1?", "Q2?"]
    answers = iter(["n", ""])
    with patch("thesis_tools.cli.generate_subquestions", return_value=suggested), \
         patch("builtins.input", lambda *_: next(answers)):
        result = _generate_and_confirm_subquestions("Working Title", None, _project())

    assert result is None or result == []


def test_confirm_handles_no_suggestions_from_claude(capsys):
    with patch("thesis_tools.cli.generate_subquestions", return_value=[]), \
         patch("builtins.input", return_value="My own Q?"):
        result = _generate_and_confirm_subquestions("Working Title", None, _project())

    assert result == ["My own Q?"]
    out = capsys.readouterr().out
    assert "didn't return any sub-questions" in out


def test_confirm_uses_project_llm_model():
    with patch("thesis_tools.cli.generate_subquestions", return_value=["Q?"]) as mock_gen, \
         patch("builtins.input", return_value="y"):
        _generate_and_confirm_subquestions("Title", None, _project(llm_model="claude-opus-5"))

    mock_gen.assert_called_once()
    _, kwargs = mock_gen.call_args
    assert kwargs["model"] == "claude-opus-5"


def test_interactive_topic_finder_calls_confirm_flow_when_llm_on(monkeypatch, tmp_path):
    from thesis_tools.cli import _interactive_topic_finder_inputs

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    answers = iter([
        "Psychology",  # field
        "My Working Title",  # working_title
        "",  # research_question
        "",  # extra_keywords
        "apa",  # style
        "y",  # use_llm
        "",  # sub_questions_raw -> blank triggers auto-generate-and-confirm
        "y",  # confirm suggested sub-questions
        "n",  # download-papers prompt
    ])

    with patch("builtins.input", lambda *_: next(answers)), \
         patch("thesis_tools.cli.generate_subquestions", return_value=["Auto Q1?", "Auto Q2?"]):
        inputs = _interactive_topic_finder_inputs(ProjectState())

    assert inputs.sub_questions == ["Auto Q1?", "Auto Q2?"]
    # Already confirmed here — the pipeline must not silently regenerate a
    # fresh, unconfirmed batch later.
    assert inputs.auto_subquestions is False


def test_bare_topic_finder_goes_interactive_even_with_saved_project_state(tmp_path, monkeypatch):
    """Regression test: once `configure` (or a prior run) has saved field/
    working_title to the project file, a bare `topic-finder` with no flags
    must still walk through the interactive prompts (and therefore the
    sub-question confirmation step) rather than silently taking the
    flags/non-interactive shortcut just because project defaults exist."""
    from thesis_tools.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    project_file = tmp_path / "project.json"
    ProjectState(field="Psychology", working_title="Sleep and Memory", style="apa").save(str(project_file))

    answers = [
        "",  # field -> keep saved default
        "",  # working_title -> keep saved default
        "",  # research_question
        "",  # extra_keywords
        "",  # style -> keep saved default
        "n",  # use_llm
        "",  # sub_questions_raw
        "n",  # download_papers
    ]

    with patch("builtins.input", side_effect=answers) as mock_input, \
         patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search", return_value=[]), \
         patch("thesis_tools.sources.openalex.OpenAlexClient.search", return_value=[]), \
         patch("thesis_tools.sources.crossref.CrossrefClient.search", return_value=[]), \
         patch("thesis_tools.sources.arxiv.ArxivClient.search", return_value=[]):
        rc = main(["topic-finder", "--project-file", str(project_file)])

    assert rc == 0
    # The old bug took the flags/non-interactive shortcut whenever project
    # state already had field+working_title, calling input() zero times.
    assert mock_input.call_count == len(answers)


def test_interactive_topic_finder_reconfirms_saved_subquestions(monkeypatch, tmp_path, capsys):
    """A project file already carrying sub-questions from a previous run must
    still show them and ask before reusing them silently — otherwise a batch
    that was never actually reviewed keeps getting reused forever."""
    from thesis_tools.cli import _interactive_topic_finder_inputs

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    project = ProjectState(
        field="Psychology",
        working_title="My Working Title",
        style="apa",
        sub_questions=["Saved Q1?", "Saved Q2?"],
    )

    answers = iter([
        "",  # field -> keep saved
        "",  # working_title -> keep saved
        "",  # research_question
        "",  # extra_keywords
        "",  # style -> keep saved
        "n",  # use_llm
        "y",  # keep saved sub-questions
        "n",  # download_papers
    ])

    with patch("builtins.input", lambda *_: next(answers)):
        inputs = _interactive_topic_finder_inputs(project)

    assert inputs.sub_questions == ["Saved Q1?", "Saved Q2?"]
    out = capsys.readouterr().out
    assert "Sub-questions saved from a previous run:" in out
    assert "1. Saved Q1?" in out


def test_interactive_topic_finder_lets_user_decline_saved_subquestions(monkeypatch, tmp_path):
    from thesis_tools.cli import _interactive_topic_finder_inputs

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    project = ProjectState(
        field="Psychology",
        working_title="My Working Title",
        style="apa",
        sub_questions=["Stale Q1?", "Stale Q2?"],
    )

    answers = iter([
        "",  # field
        "",  # working_title
        "",  # research_question
        "",  # extra_keywords
        "",  # style
        "n",  # use_llm
        "n",  # decline saved sub-questions
        "Fresh Q1?; Fresh Q2?",  # type new ones instead
        "n",  # download_papers
    ])

    with patch("builtins.input", lambda *_: next(answers)):
        inputs = _interactive_topic_finder_inputs(project)

    assert inputs.sub_questions == ["Fresh Q1?", "Fresh Q2?"]
