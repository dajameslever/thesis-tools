from thesis_tools.library.index_store import LibraryEntry, LibraryIndex, hash_file
from thesis_tools.sources.base import Paper


def _entry(path, doi=None, file_hash=None):
    return LibraryEntry(
        file_path=str(path),
        file_hash=file_hash or f"hash-{path}",
        file_type="pdf",
        size_bytes=100,
        indexed_at="2026-01-01T00:00:00",
        confidence="verified-doi",
        doi=doi,
        paper=Paper(title=f"Paper at {path}", doi=doi, year=2020),
    )


def test_hash_file_is_stable_and_content_sensitive(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("same content")
    b.write_text("same content")
    c = tmp_path / "c.txt"
    c.write_text("different content")

    assert hash_file(a) == hash_file(b)
    assert hash_file(a) != hash_file(c)


def test_library_entry_to_dict_from_dict_roundtrip():
    entry = _entry("/downloads/paper.pdf", doi="10.1234/x")
    entry.references = [{"doi": "10.1234/old", "title": "Old Paper", "year": 2001}]
    restored = LibraryEntry.from_dict(entry.to_dict())
    assert restored == entry


def test_library_entry_from_dict_defaults_missing_references_for_backward_compat():
    entry = _entry("/downloads/paper.pdf", doi="10.1234/x")
    data = entry.to_dict()
    del data["references"]  # simulate an index.json written before `references` existed
    restored = LibraryEntry.from_dict(data)
    assert restored.references == []


def test_upsert_replaces_by_hash():
    index = LibraryIndex()
    entry1 = _entry("/downloads/paper.pdf", file_hash="samehash")
    entry2 = _entry("/downloads/paper_renamed.pdf", file_hash="samehash")
    index.upsert(entry1)
    index.upsert(entry2)
    assert len(index.entries) == 1
    assert index.entries[0].file_path == "/downloads/paper_renamed.pdf"


def test_upsert_replaces_by_path_even_if_hash_changed():
    index = LibraryIndex()
    index.upsert(_entry("/downloads/paper.pdf", file_hash="hash1"))
    index.upsert(_entry("/downloads/paper.pdf", file_hash="hash2"))  # file content changed, rescanned
    assert len(index.entries) == 1
    assert index.entries[0].file_hash == "hash2"


def test_upsert_appends_new_distinct_entries():
    index = LibraryIndex()
    index.upsert(_entry("/downloads/a.pdf", file_hash="h1"))
    index.upsert(_entry("/downloads/b.pdf", file_hash="h2"))
    assert len(index.entries) == 2


def test_prune_missing_removes_entries_whose_file_is_gone(tmp_path):
    existing = tmp_path / "exists.pdf"
    existing.write_text("x")
    index = LibraryIndex([_entry(existing), _entry(tmp_path / "gone.pdf")])
    removed = index.prune_missing()
    assert removed == 1
    assert len(index.entries) == 1
    assert index.entries[0].file_path == str(existing)


def test_duplicates_by_doi_groups_same_doi_different_files():
    index = LibraryIndex(
        [
            _entry("/downloads/a.pdf", doi="10.1234/x"),
            _entry("/downloads/a (1).pdf", doi="10.1234/X"),  # case-insensitive match
            _entry("/downloads/b.pdf", doi="10.1234/y"),
        ]
    )
    dupes = index.duplicates_by_doi()
    assert list(dupes.keys()) == ["10.1234/x"]
    assert len(dupes["10.1234/x"]) == 2


def test_save_and_load_roundtrip(tmp_path):
    index_path = tmp_path / "library" / "index.json"
    index = LibraryIndex([_entry("/downloads/a.pdf", doi="10.1234/x")])
    index.save(index_path)

    loaded = LibraryIndex.load(index_path)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].doi == "10.1234/x"


def test_load_missing_file_returns_empty_index(tmp_path):
    loaded = LibraryIndex.load(tmp_path / "does-not-exist.json")
    assert loaded.entries == []
