from unittest.mock import MagicMock, patch

from thesis_tools.paper_download import download_and_extract, download_papers
from thesis_tools.sources.base import Paper


def _fake_pdf_bytes() -> bytes:
    # A minimal but real PDF pypdf can open and extract (empty) text from.
    from io import BytesIO

    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_download_and_extract_skips_paper_without_pdf_url(tmp_path):
    paper = Paper(title="No PDF Here", pdf_url=None)
    result = download_and_extract(paper, dest_dir=str(tmp_path))
    assert result is None
    assert not (tmp_path / "pdfs").exists()


def test_download_and_extract_saves_pdf_and_text(tmp_path):
    paper = Paper(title="Great Paper", year=2020, pdf_url="https://example.org/great.pdf")
    fake_response = MagicMock()
    fake_response.content = _fake_pdf_bytes()
    fake_response.raise_for_status = MagicMock()

    with patch("thesis_tools.paper_download.requests.get", return_value=fake_response):
        result = download_and_extract(paper, dest_dir=str(tmp_path))

    assert result is not None
    assert (tmp_path / "pdfs" / "great-paper-2020.pdf").is_file()
    assert (tmp_path / "text" / "great-paper-2020.txt").is_file()
    assert paper.full_text_excerpt is not None


def test_download_and_extract_skips_non_pdf_response(tmp_path, capsys):
    paper = Paper(title="Landing Page Paper", pdf_url="https://example.org/paywall")
    fake_response = MagicMock()
    fake_response.content = b"<html>not a pdf</html>"
    fake_response.raise_for_status = MagicMock()

    with patch("thesis_tools.paper_download.requests.get", return_value=fake_response):
        result = download_and_extract(paper, dest_dir=str(tmp_path))

    assert result is None
    assert paper.full_text_excerpt is None
    assert "wasn't a PDF" in capsys.readouterr().err


def test_download_and_extract_handles_request_failure(tmp_path, capsys):
    paper = Paper(title="Unreachable Paper", pdf_url="https://example.org/404.pdf")

    with patch("thesis_tools.paper_download.requests.get", side_effect=RuntimeError("boom")):
        result = download_and_extract(paper, dest_dir=str(tmp_path))

    assert result is None
    assert "failed for" in capsys.readouterr().err


def test_download_papers_counts_only_successes(tmp_path):
    ok_paper = Paper(title="Has PDF", pdf_url="https://example.org/ok.pdf")
    no_pdf_paper = Paper(title="No PDF", pdf_url=None)
    fake_response = MagicMock()
    fake_response.content = _fake_pdf_bytes()
    fake_response.raise_for_status = MagicMock()

    with patch("thesis_tools.paper_download.requests.get", return_value=fake_response):
        count = download_papers([ok_paper, no_pdf_paper], dest_dir=str(tmp_path))

    assert count == 1
