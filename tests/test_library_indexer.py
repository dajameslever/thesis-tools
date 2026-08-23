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


def test_run_library_indexer_prints_one_llm_notice_not_one_per_paper(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    for i in range(4):
        (downloads / f"paper{i}.txt").write_text(f"Paper {i} body text about sleep and cognition.", encoding="utf-8")
    index_path = tmp_path / "library" / "index.json"

    call_count = {"n": 0}

    def _fake_identify_many(doc, filename_fallback, **kwargs):
        call_count["n"] += 1
        return IdentifiedPaper(
            paper=Paper(title=f"Paper {call_count['n']}", doi=f"10.1/{call_count['n']}", year=2020, abstract="An abstract about sleep and cognition."),
            confidence="verified-doi",
            matched_doi=f"10.1/{call_count['n']}",
        )

    with patch("thesis_tools.library.library_indexer.identify_document", side_effect=_fake_identify_many):
        inputs = LibraryIndexerInputs(
            folder=str(downloads),
            index_path=str(index_path),
            research_question="Does sleep affect cognition?",
            use_llm=True,
        )
        run_library_indexer(inputs)

    stderr = capsys.readouterr().err
    assert stderr.count("ANTHROPIC_API_KEY not set") == 1
    assert "Claude requested but unavailable" in stderr


def test_run_library_indexer_survives_one_file_failing_identification(tmp_path, capsys):
    """A single file's identify_document() blowing up (a flaky API, an
    unexpected response shape) must not abort indexing the rest of the
    folder — same as an unreadable/unextractable file already doesn't. It
    also must not mean losing what the PDF itself told us: the file still
    gets indexed, from local heuristics alone, flagged unresolved."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "a-good-paper.pdf").write_bytes(b"%PDF-1.4 fake a")
    (downloads / "b-broken-paper.pdf").write_bytes(b"%PDF-1.4 fake b")
    index_path = tmp_path / "library" / "index.json"

    def _identify(doc, filename_fallback, **kwargs):
        if "broken" in filename_fallback:
            raise TypeError("'NoneType' object is not iterable")
        return IdentifiedPaper(
            paper=Paper(title="A Good Paper", doi="10.1234/good", year=2020),
            confidence="verified-doi",
            matched_doi="10.1234/good",
        )

    with patch("thesis_tools.library.library_indexer.extract_document") as mock_extract, patch(
        "thesis_tools.library.library_indexer.identify_document", side_effect=_identify
    ):
        from thesis_tools.library.extract import ExtractedDocument

        mock_extract.return_value = ExtractedDocument(
            text="some text", title_hint="Locally Extracted Title", author_hint=None, file_type="pdf"
        )

        inputs = LibraryIndexerInputs(folder=str(downloads), index_path=str(index_path))
        stats = run_library_indexer(inputs)

    assert stats["new"] == 2
    assert stats["failed"] == 0
    index = LibraryIndex.load(index_path)
    assert len(index.entries) == 2
    by_title = {e.paper.title: e for e in index.entries}
    assert "A Good Paper" in by_title
    assert by_title["A Good Paper"].confidence == "verified-doi"
    # The broken file still got indexed — from the file's own metadata,
    # since verification blew up — rather than dropped entirely.
    assert "Locally Extracted Title" in by_title
    assert by_title["Locally Extracted Title"].confidence == "unresolved"
    assert "verification failed" in capsys.readouterr().err
