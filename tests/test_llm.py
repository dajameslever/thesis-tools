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
    from thesis_tools.literature_review import (
        _CONCLUSION_SYSTEM_PROMPT,
        _INTRO_SYSTEM_PROMPT,
        _synthesis_system_prompt,
    )

    for prompt in (_LLM_SYSTEM_PROMPT, _INTRO_SYSTEM_PROMPT, _synthesis_system_prompt(), _CONCLUSION_SYSTEM_PROMPT):
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


def test_ask_trims_to_last_sentence_when_truncated_by_max_tokens():
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "The literature broadly agrees on X. However, this apparent gap should"
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "max_tokens"
    client.messages.create.return_value = response

    result = llm.ask(client, "sys", "user")

    assert result == "The literature broadly agrees on X."
    assert not result.endswith("should")


def test_ask_leaves_complete_response_untouched_when_not_truncated():
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "A complete sentence. And another one."
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    client.messages.create.return_value = response

    result = llm.ask(client, "sys", "user")

    assert result == "A complete sentence. And another one."


def test_ask_returns_untrimmed_when_no_sentence_boundary_found():
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "a fragment with no punctuation at all"
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "max_tokens"
    client.messages.create.return_value = response

    result = llm.ask(client, "sys", "user")

    assert result == "a fragment with no punctuation at all"


def test_default_model_constants_are_the_intended_tiers():
    # Regression: much of the API usage was Opus when it should have been
    # Sonnet, and the bulk per-paper work (summaries, stance classification)
    # is a better fit for the cheaper/faster Haiku than for Sonnet or Opus.
    assert llm.DEFAULT_MODEL == "claude-sonnet-5"
    assert llm.DEFAULT_EXTRACTION_MODEL == "claude-haiku-4-5"


def test_ask_streams_when_max_tokens_is_large():
    """A long generation on a non-streaming request risks an HTTP timeout
    before the first byte arrives."""
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "A long section."
    message = MagicMock()
    message.content = [block]
    message.stop_reason = "end_turn"
    client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value = message

    result = llm.ask(client, "sys", "user", max_tokens=llm.STREAMING_MAX_TOKENS_THRESHOLD)

    assert result == "A long section."
    client.messages.stream.assert_called_once()
    client.messages.create.assert_not_called()


def test_ask_does_not_stream_for_small_requests():
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "short"
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    client.messages.create.return_value = response

    assert llm.ask(client, "sys", "user", max_tokens=300) == "short"
    client.messages.create.assert_called_once()
    client.messages.stream.assert_not_called()


def test_ask_reports_the_failure_reason_when_asked():
    """Callers whose fallback is markedly worse than the real answer need to
    be able to say what went wrong instead of shipping it silently."""
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("prompt is too long")
    errors = []

    assert llm.ask(client, "sys", "user", errors=errors) is None
    assert len(errors) == 1
    assert "prompt is too long" in errors[0]
    assert "RuntimeError" in errors[0]


def test_ask_reports_an_empty_response_as_a_failure():
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "   "
    response = MagicMock()
    response.content = [block]
    client.messages.create.return_value = response
    errors = []

    assert llm.ask(client, "sys", "user", errors=errors) is None
    assert "empty response" in errors[0]


def _text_client(text="ok"):
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    response.usage.input_tokens = 100
    response.usage.output_tokens = 20
    response.usage.cache_creation_input_tokens = 0
    response.usage.cache_read_input_tokens = 0
    client.messages.create.return_value = response
    return client, response


def test_ask_sends_no_cache_control_by_default():
    """Caching a prompt costs 1.25x to write and only pays back on a read —
    it has to be asked for, never assumed."""
    client, _ = _text_client()
    llm.ask(client, "sys", "user")
    assert "cache_control" not in client.messages.create.call_args.kwargs


def test_ask_caches_the_whole_prompt_when_asked():
    client, _ = _text_client()
    llm.ask(client, "sys", "user", cache=True)
    assert client.messages.create.call_args.kwargs["cache_control"] == {"type": "ephemeral"}


def test_cache_suffix_is_sent_after_the_breakpoint():
    """The point of the suffix: the varying tail (a word target, a tweaked
    instruction) must sit OUTSIDE the cached prefix, or it invalidates the
    entry every time it changes."""
    client, _ = _text_client()
    llm.ask(client, "sys", "the papers", cache=True, cache_suffix="write 900 words")

    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert [b["text"] for b in content] == ["the papers", "write 900 words"]
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in content[1]
    # A block-level breakpoint replaces the top-level one, never doubles it.
    assert "cache_control" not in client.messages.create.call_args.kwargs


def test_cache_suffix_is_appended_inline_when_caching_is_off():
    client, _ = _text_client()
    llm.ask(client, "sys", "the papers", cache=False, cache_suffix="write 900 words")

    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert content == "the papers\n\nwrite 900 words"


def test_usage_totals_accumulate_across_calls():
    """A cache that only ever writes is pure overhead; the counters are the
    only way to tell that apart from one that is being read back."""
    client, response = _text_client()
    response.usage.cache_creation_input_tokens = 5000
    totals = {}

    llm.ask(client, "sys", "user", usage_totals=totals)
    response.usage.cache_creation_input_tokens = 0
    response.usage.cache_read_input_tokens = 5000
    llm.ask(client, "sys", "user", usage_totals=totals)

    assert totals["input_tokens"] == 200
    assert totals["output_tokens"] == 40
    assert totals["cache_creation_input_tokens"] == 5000
    assert totals["cache_read_input_tokens"] == 5000


def test_format_usage_is_none_when_nothing_was_sent():
    assert llm.format_usage({}) is None
    assert llm.format_usage({"input_tokens": 0, "output_tokens": 0}) is None


def test_format_usage_reports_cache_reads():
    line = llm.format_usage(
        {"input_tokens": 1000, "output_tokens": 200, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 40000}
    )
    assert "40,000 cache-read" in line
