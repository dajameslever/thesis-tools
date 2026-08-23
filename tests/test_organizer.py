from pathlib import Path

from thesis_tools.library.index_store import LibraryEntry
from thesis_tools.library.organizer import organize_entries, organized_filename
from thesis_tools.sources.base import Paper


_UNSET = object()


def _entry(path, title="A Paper", authors=_UNSET, year=2021):
    if authors is _UNSET:
        authors = ["Jane Doe"]
    return LibraryEntry(
        file_path=str(path),
        file_hash=f"hash-{path}",
        file_type="pdf",
        size_bytes=100,
        indexed_at="2026-01-01T00:00:00",
        confidence="verified-doi",
        doi=None,
        paper=Paper(title=title, authors=authors, year=year),
    )


def test_organized_filename_uses_last_author_year_title():
    entry = _entry("/downloads/x.pdf", title="Sleep and Cognition", authors=["Jane A. Doe"], year=2020)
    name = organized_filename(entry)
    assert name == "Doe_2020_Sleep_and_Cognition.pdf"


def test_organized_filename_handles_missing_author_and_year():
    entry = _entry("/downloads/x.pdf", title="Untitled Findings", authors=[], year=None)
    name = organized_filename(entry)
    assert name.startswith("Unknown_nd_")
    assert name.endswith(".pdf")


def test_organize_entries_copies_files_and_leaves_originals(tmp_path):
    src_dir = tmp_path / "downloads"
    src_dir.mkdir()
    src = src_dir / "paper.pdf"
    src.write_text("pdf content")

    dest = tmp_path / "organized"
    entry = _entry(src, title="Sleep and Cognition", authors=["Jane Doe"], year=2020)

    results = organize_entries([entry], dest)

    assert src.exists()  # original untouched
    assert len(results) == 1
    dest_path = dest / "Doe_2020_Sleep_and_Cognition.pdf"
    assert dest_path.exists()
    assert dest_path.read_text() == "pdf content"


def test_organize_entries_dry_run_does_not_write_files(tmp_path):
    src = tmp_path / "paper.pdf"
    src.write_text("pdf content")
    dest = tmp_path / "organized"

    entry = _entry(src, title="Sleep and Cognition", year=2020)
    results = organize_entries([entry], dest, dry_run=True)

    assert len(results) == 1
    assert not dest.exists()


def test_organize_entries_skips_missing_source_files(tmp_path):
    entry = _entry(tmp_path / "gone.pdf")
    results = organize_entries([entry], tmp_path / "organized")
    assert results == []


def test_organize_entries_avoids_name_collisions(tmp_path):
    src1 = tmp_path / "paper1.pdf"
    src2 = tmp_path / "paper2.pdf"
    src1.write_text("first")
    src2.write_text("second")
    dest = tmp_path / "organized"

    entry1 = _entry(src1, title="Sleep and Cognition", authors=["Jane Doe"], year=2020)
    entry2 = _entry(src2, title="Sleep and Cognition", authors=["Jane Doe"], year=2020)

    results = organize_entries([entry1, entry2], dest)
    dest_names = {Path(d).name for _, d in results}

    assert len(dest_names) == 2
    assert "Doe_2020_Sleep_and_Cognition.pdf" in dest_names
    assert "Doe_2020_Sleep_and_Cognition_2.pdf" in dest_names
