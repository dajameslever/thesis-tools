from pathlib import Path

from thesis_tools.stance_cache import StanceCache, questions_hash, text_hash


def test_text_hash_is_stable_and_sensitive_to_content():
    assert text_hash("abc") == text_hash("abc")
    assert text_hash("abc") != text_hash("abd")


def test_questions_hash_is_stable_and_order_sensitive():
    assert questions_hash(["a?", "b?"]) == questions_hash(["a?", "b?"])
    assert questions_hash(["a?", "b?"]) != questions_hash(["b?", "a?"])
    assert questions_hash(["a?", "b?"]) != questions_hash(["a?"])


def test_stance_cache_load_missing_file_returns_empty(tmp_path):
    cache = StanceCache.load(tmp_path / "does-not-exist.json")
    assert cache.entries == {}


def test_stance_cache_load_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("not json", encoding="utf-8")
    cache = StanceCache.load(path)
    assert cache.entries == {}


def test_stance_cache_put_get_roundtrip():
    cache = StanceCache()
    cache.put("paper-1", "texthash", "qhash", "claude-haiku-4-5", {"Q1": {"stance": "supports", "rationale": "because"}})
    assert cache.get("paper-1", "texthash", "qhash", "claude-haiku-4-5") == {"Q1": {"stance": "supports", "rationale": "because"}}


def test_stance_cache_get_misses_on_changed_text_hash():
    cache = StanceCache()
    cache.put("paper-1", "texthash-old", "qhash", "claude-haiku-4-5", {"Q1": {"stance": "supports", "rationale": "because"}})
    assert cache.get("paper-1", "texthash-new", "qhash", "claude-haiku-4-5") is None


def test_stance_cache_get_misses_on_changed_questions_hash():
    cache = StanceCache()
    cache.put("paper-1", "texthash", "qhash-old", "claude-haiku-4-5", {"Q1": {"stance": "supports", "rationale": "because"}})
    assert cache.get("paper-1", "texthash", "qhash-new", "claude-haiku-4-5") is None


def test_stance_cache_get_misses_for_unknown_paper():
    cache = StanceCache()
    assert cache.get("unknown-paper", "texthash", "qhash", "claude-haiku-4-5") is None


def test_stance_cache_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "library" / "stance_cache.json"
    cache = StanceCache()
    cache.put("paper-1", "texthash", "qhash", "claude-haiku-4-5", {"Q1": {"stance": "challenges", "rationale": "nope"}})
    cache.save(path)
    assert path.is_file()

    reloaded = StanceCache.load(path)
    assert reloaded.get("paper-1", "texthash", "qhash", "claude-haiku-4-5") == {
        "Q1": {"stance": "challenges", "rationale": "nope"}
    }


def test_stance_cache_get_misses_on_a_different_model():
    """A deliberate --llm-model change has to re-classify, not silently hand
    back what a cheaper model said earlier."""
    cache = StanceCache()
    cache.put("paper-1", "texthash", "qhash", "claude-haiku-4-5", {"Q1": {"stance": "supports", "rationale": "x"}})
    assert cache.get("paper-1", "texthash", "qhash", "claude-opus-5") is None
    assert cache.get("paper-1", "texthash", "qhash", "claude-haiku-4-5") is not None


def test_stance_cache_entry_without_a_model_misses_once(tmp_path):
    """Cache files written before the model was tracked refill rather than
    being trusted blindly."""
    path = tmp_path / "old.json"
    path.write_text(
        '{"version": 1, "entries": {"paper-1": {"text_hash": "t", "questions_hash": "q", '
        '"stances": {"Q1": {"stance": "supports", "rationale": "x"}}}}}',
        encoding="utf-8",
    )
    assert StanceCache.load(path).get("paper-1", "t", "q", "claude-haiku-4-5") is None
