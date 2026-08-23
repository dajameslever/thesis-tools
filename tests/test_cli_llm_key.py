from unittest.mock import patch

from thesis_tools.cli import _ensure_anthropic_key_interactive, _prompt
from thesis_tools.project import ProjectState


def test_prompt_prints_blank_line_after_answer(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "hello")
    _prompt("Question")
    out = capsys.readouterr().out
    assert out.endswith("\n\n") or out == "\n"  # blank line printed after the answer


def test_ensure_key_returns_true_when_already_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-existing")
    with patch("getpass.getpass") as mock_getpass:
        result = _ensure_anthropic_key_interactive()
    assert result is True
    mock_getpass.assert_not_called()


def test_ensure_key_prompts_and_skips_on_blank(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with patch("getpass.getpass", return_value=""):
        result = _ensure_anthropic_key_interactive()
    assert result is False
    assert "ANTHROPIC_API_KEY" not in __import__("os").environ or __import__("os").environ.get("ANTHROPIC_API_KEY") == ""
    out = capsys.readouterr().out
    assert "Skipping" in out
    assert not (tmp_path / ".env").exists()


def test_ensure_key_saves_when_provided_and_confirmed(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with patch("getpass.getpass", return_value="sk-new-key"), \
         patch("builtins.input", return_value="y"):
        result = _ensure_anthropic_key_interactive()
    assert result is True
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-new-key"
    assert (tmp_path / ".env").read_text() == "ANTHROPIC_API_KEY=sk-new-key\n"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_ensure_key_provided_but_not_saved_when_declined(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with patch("getpass.getpass", return_value="sk-new-key"), \
         patch("builtins.input", return_value="n"):
        result = _ensure_anthropic_key_interactive()
    assert result is True
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-new-key"
    assert not (tmp_path / ".env").exists()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_configure_offers_key_prompt_when_opting_into_llm(monkeypatch, tmp_path):
    from thesis_tools.cli import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "project.json"

    answers = iter([
        "Psychology",  # field
        "Title",  # working_title
        "",  # research_question
        "",  # sub_questions
        "apa",  # style
        "",  # contact_email
        "y",  # use_llm
        "n",  # save-to-.env prompt (reached via input(), after getpass)
    ])

    with patch("builtins.input", lambda *_: next(answers)), \
         patch("getpass.getpass", return_value="sk-configure-test"):
        rc = main(["configure", "--project-file", str(project_file)])

    assert rc == 0
    state = ProjectState.load(str(project_file))
    assert state.use_llm is True
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-configure-test"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
