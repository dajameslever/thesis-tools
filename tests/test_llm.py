from unittest.mock import MagicMock, patch

from thesis_tools import llm


def test_availability_issue_reports_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.availability_issue() == "ANTHROPIC_API_KEY not set"


def test_availability_issue_none_when_key_and_package_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.availability_issue() is None  # `anthropic` is a core dependency, always installed


def test_get_client_quiet_suppresses_message(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = llm.get_client(quiet=True)
    assert result is None
    assert capsys.readouterr().err == ""


def test_get_client_noisy_prints_message(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = llm.get_client(quiet=False)
    assert result is None
    assert "ANTHROPIC_API_KEY not set" in capsys.readouterr().err


def test_get_client_returns_anthropic_client_when_available(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = llm.get_client()
    assert client is not None
    assert client.api_key == "sk-test"


def test_academic_style_note_mentions_key_constraints():
    note = llm.ACADEMIC_STYLE_NOTE
    assert "third person" in note.lower()
    assert "contraction" in note.lower()


def test_academic_style_note_is_embedded_in_content_prompts():
    from thesis_tools.summarize import _LLM_SYSTEM_PROMPT
    from thesis_tools.literature_review import _INTRO_SYSTEM_PROMPT, _SYNTHESIS_SYSTEM_PROMPT, _GAPS_SYSTEM_PROMPT

    for prompt in (_LLM_SYSTEM_PROMPT, _INTRO_SYSTEM_PROMPT, _SYNTHESIS_SYSTEM_PROMPT, _GAPS_SYSTEM_PROMPT):
        assert llm.ACADEMIC_STYLE_NOTE in prompt


def test_subquestion_prompt_asks_for_formal_phrasing():
    from thesis_tools.subquestions import _SUBQUESTION_SYSTEM_PROMPT

    assert "academic research question" in _SUBQUESTION_SYSTEM_PROMPT.lower()


def test_ask_returns_none_on_exception():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    assert llm.ask(client, "sys", "user") is None


def test_ask_extracts_text_blocks():
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "hello"
    response = MagicMock()
    response.content = [block]
    client.messages.create.return_value = response
    assert llm.ask(client, "sys", "user") == "hello"
