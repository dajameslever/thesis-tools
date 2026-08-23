from unittest.mock import patch

from thesis_tools.library.identify import IdentifiedPaper
from thesis_tools.library.index_store import LibraryIndex
from thesis_tools.library.library_indexer import LibraryIndexerInputs, run_library_indexer
from thesis_tools.sources.base import Paper


def _fake_identify(paper_title="Sleep and Cognition", confidence="verified-doi", doi="10.1234/x", abstract=None):
    def _identify(doc, filename_fallback, **kwargs):
        return IdentifiedPaper(
            paper=Paper(title=paper_title, doi=doi, year=2020, abstract=abstract),
            confidence=confidence,
            matched_doi=doi,
        )

    return _identify


def test_run_library_indexer_indexes_new_pdf(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    index_path = tmp_path / "library" / "index.json"

    with patch("thesis_tools.library.library_indexer.extract_document") as mock_extract, patch(
        "thesis_tools.library.library_indexer.identify_document", side_effect=_fake_identify()
    ):
        from thesis_tools.library.extract import ExtractedDocument

        mock_extract.return_value = ExtractedDocument(text="some text", title_hint=None, author_hint=None, file_type="pdf")

        inputs = LibraryIndexerInputs(folder=str(downloads), index_path=str(index_path))
        stats = run_library_indexer(inputs)

    assert stats["new"] == 1
    assert stats["skipped"] == 0
    index = LibraryIndex.load(index_path)
    assert len(index.entries) == 1
    assert index.entries[0].paper.title == "Sleep and Cognition"


def test_run_library_indexer_skips_unchanged_files_on_rescan(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    index_path = tmp_path / "library" / "index.json"

    from thesis_tools.library.extract import ExtractedDocument

    with patch("thesis_tools.library.library_indexer.extract_document") as mock_extract, patch(
        "thesis_tools.library.library_indexer.identify_document", side_effect=_fake_identify()
    ) as mock_identify:
        mock_extract.return_value = ExtractedDocument(text="some text", title_hint=None, author_hint=None, file_type="pdf")
        inputs = LibraryIndexerInputs(folder=str(downloads), index_path=str(index_path))
        run_library_indexer(inputs)
        assert mock_identify.call_count == 1

        stats = run_library_indexer(inputs)  # second run, file unchanged
        assert stats["new"] == 0
        assert stats["skipped"] == 1
        assert mock_identify.call_count == 1  # not called again


def test_run_library_indexer_rescan_forces_reextraction(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    index_path = tmp_path / "library" / "index.json"

    from thesis_tools.library.extract import ExtractedDocument

    with patch("thesis_tools.library.library_indexer.extract_document") as mock_extract, patch(
        "thesis_tools.library.library_indexer.identify_document", side_effect=_fake_identify()
    ) as mock_identify:
        mock_extract.return_value = ExtractedDocument(text="some text", title_hint=None, author_hint=None, file_type="pdf")
        inputs = LibraryIndexerInputs(folder=str(downloads), index_path=str(index_path), rescan=True)
        run_library_indexer(inputs)
        run_library_indexer(inputs)
        assert mock_identify.call_count == 2


def test_run_library_indexer_prune_removes_deleted_files(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    paper_path = downloads / "paper.pdf"
    paper_path.write_bytes(b"%PDF-1.4 fake")
    index_path = tmp_path / "library" / "index.json"

    from thesis_tools.library.extract import ExtractedDocument

    with patch("thesis_tools.library.library_indexer.extract_document") as mock_extract, patch(
        "thesis_tools.library.library_indexer.identify_document", side_effect=_fake_identify()
    ):
        mock_extract.return_value = ExtractedDocument(text="some text", title_hint=None, author_hint=None, file_type="pdf")
        inputs = LibraryIndexerInputs(folder=str(downloads), index_path=str(index_path))
        run_library_indexer(inputs)

    paper_path.unlink()
    inputs = LibraryIndexerInputs(folder=str(downloads), index_path=str(index_path), prune=True)
    stats = run_library_indexer(inputs)
    assert stats["pruned"] == 1
    assert stats["total"] == 0


def test_run_library_indexer_organize_copies_without_touching_originals(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    index_path = tmp_path / "library" / "index.json"
    organize_to = tmp_path / "organized"

    from thesis_tools.library.extract import ExtractedDocument

    with patch("thesis_tools.library.library_indexer.extract_document") as mock_extract, patch(
        "thesis_tools.library.library_indexer.identify_document", side_effect=_fake_identify()
    ):
        mock_extract.return_value = ExtractedDocument(text="some text", title_hint=None, author_hint=None, file_type="pdf")
        inputs = LibraryIndexerInputs(
            folder=str(downloads), index_path=str(index_path), organize=True, organize_to=str(organize_to)
        )
        stats = run_library_indexer(inputs)

    assert stats["organized"] == 1
    assert (downloads / "paper.pdf").exists()  # original untouched
    assert any(organize_to.iterdir())


def test_run_library_indexer_raises_for_missing_folder(tmp_path):
    import pytest

    inputs = LibraryIndexerInputs(folder=str(tmp_path / "does-not-exist"))
    with pytest.raises(ValueError):
        run_library_indexer(inputs)


def test_run_library_indexer_raises_for_unknown_style(tmp_path):
    import pytest

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    inputs = LibraryIndexerInputs(folder=str(downloads), style="vancouver")
    with pytest.raises(ValueError):
        run_library_indexer(inputs)


def test_run_library_indexer_report_includes_relevance_and_summary(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    index_path = tmp_path / "library" / "index.json"
    report_path = tmp_path / "library" / "library.md"

    from thesis_tools.library.extract import ExtractedDocument

    abstract = "This paper studies sleep deprivation and adolescent decision-making in depth."
    with patch("thesis_tools.library.library_indexer.extract_document") as mock_extract, patch(
        "thesis_tools.library.library_indexer.identify_document",
        side_effect=_fake_identify(paper_title="Sleep Deprivation and Adolescent Decision-Making", abstract=abstract),
    ):
        mock_extract.return_value = ExtractedDocument(text="some text", title_hint=None, author_hint=None, file_type="pdf")
        inputs = LibraryIndexerInputs(
            folder=str(downloads),
            index_path=str(index_path),
            report_path=str(report_path),
            research_question="Does sleep deprivation affect adolescent decision-making?",
        )
        run_library_indexer(inputs)

    text = report_path.read_text()
    assert "Relevance to your research question" in text
    assert "What it's about" in text
    assert "Contributors" in text
