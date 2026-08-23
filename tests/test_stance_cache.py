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
    cache.put("paper-1", "texthash", "qhash", {"Q1": {"stance": "supports", "rationale": "because"}})
    assert cache.get("paper-1", "texthash", "qhash") == {"Q1": {"stance": "supports", "rationale": "because"}}


def test_stance_cache_get_misses_on_changed_text_hash():
    cache = StanceCache()
    cache.put("paper-1", "texthash-old", "qhash", {"Q1": {"stance": "supports", "rationale": "because"}})
    assert cache.get("paper-1", "texthash-new", "qhash") is None


def test_stance_cache_get_misses_on_changed_questions_hash():
    cache = StanceCache()
    cache.put("paper-1", "texthash", "qhash-old", {"Q1": {"stance": "supports", "rationale": "because"}})
    assert cache.get("paper-1", "texthash", "qhash-new") is None


def test_stance_cache_get_misses_for_unknown_paper():
    cache = StanceCache()
    assert cache.get("unknown-paper", "texthash", "qhash") is None


def test_stance_cache_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "library" / "stance_cache.json"
    cache = StanceCache()
    cache.put("paper-1", "texthash", "qhash", {"Q1": {"stance": "challenges", "rationale": "nope"}})
    cache.save(path)
    assert path.is_file()

    reloaded = StanceCache.load(path)
    assert reloaded.get("paper-1", "texthash", "qhash") == {"Q1": {"stance": "challenges", "rationale": "nope"}}
