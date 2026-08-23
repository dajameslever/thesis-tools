import importlib
import os

import thesis_tools.env as env_module


def _reset_loaded_flag():
    env_module._loaded = False


def test_load_dotenv_once_sets_unset_vars(tmp_path, monkeypatch):
    _reset_loaded_flag()
    monkeypatch.delenv("THESIS_TOOLS_TEST_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("THESIS_TOOLS_TEST_KEY=abc123\n# a comment\n\nOTHER=1\n", encoding="utf-8")

    env_module.load_dotenv_once(str(env_file))

    assert os.environ["THESIS_TOOLS_TEST_KEY"] == "abc123"
    assert os.environ["OTHER"] == "1"
    monkeypatch.delenv("THESIS_TOOLS_TEST_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)


def test_load_dotenv_once_does_not_override_existing_env(tmp_path, monkeypatch):
    _reset_loaded_flag()
    monkeypatch.setenv("THESIS_TOOLS_TEST_KEY", "already-set")
    env_file = tmp_path / ".env"
    env_file.write_text("THESIS_TOOLS_TEST_KEY=from-file\n", encoding="utf-8")

    env_module.load_dotenv_once(str(env_file))

    assert os.environ["THESIS_TOOLS_TEST_KEY"] == "already-set"


def test_load_dotenv_once_only_reads_file_once(tmp_path, monkeypatch):
    _reset_loaded_flag()
    monkeypatch.delenv("THESIS_TOOLS_TEST_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("THESIS_TOOLS_TEST_KEY=first\n", encoding="utf-8")
    env_module.load_dotenv_once(str(env_file))
    assert os.environ["THESIS_TOOLS_TEST_KEY"] == "first"

    monkeypatch.delenv("THESIS_TOOLS_TEST_KEY", raising=False)
    env_file.write_text("THESIS_TOOLS_TEST_KEY=second\n", encoding="utf-8")
    env_module.load_dotenv_once(str(env_file))  # should no-op, already loaded

    assert "THESIS_TOOLS_TEST_KEY" not in os.environ
    monkeypatch.delenv("THESIS_TOOLS_TEST_KEY", raising=False)


def test_load_dotenv_once_missing_file_is_a_noop(tmp_path):
    _reset_loaded_flag()
    env_module.load_dotenv_once(str(tmp_path / "does-not-exist.env"))  # should not raise


def test_save_to_dotenv_creates_new_file(tmp_path):
    path = tmp_path / ".env"
    env_module.save_to_dotenv("ANTHROPIC_API_KEY", "sk-test-123", str(path))
    assert path.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=sk-test-123\n"


def test_save_to_dotenv_replaces_existing_key_preserves_others(tmp_path):
    path = tmp_path / ".env"
    path.write_text("FOO=bar\nANTHROPIC_API_KEY=old-key\nBAZ=qux\n", encoding="utf-8")
    env_module.save_to_dotenv("ANTHROPIC_API_KEY", "new-key", str(path))
    text = path.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=new-key" in text
    assert "FOO=bar" in text
    assert "BAZ=qux" in text
    assert "old-key" not in text
