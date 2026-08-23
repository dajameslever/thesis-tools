from pathlib import Path

from thesis_tools.library.extract import extract_document, extract_html, extract_txt


def test_extract_txt(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Some plain text notes about sleep deprivation.", encoding="utf-8")
    doc = extract_txt(path)
    assert doc.file_type == "txt"
    assert "sleep deprivation" in doc.text
    assert doc.title_hint is None


def test_extract_html_pulls_title_and_strips_tags(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>Sleep and Cognition</title></head>"
        "<body><p>This is <b>bold</b> text about sleep.</p></body></html>",
        encoding="utf-8",
    )
    doc = extract_html(path)
    assert doc.file_type == "html"
    assert doc.title_hint == "Sleep and Cognition"
    assert "bold" not in "<b>"  # sanity: raw tag text shouldn't leak literally
    assert "This is bold text about sleep." in doc.text


def test_extract_document_returns_none_for_unsupported_extension(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b,c", encoding="utf-8")
    assert extract_document(path) is None


def test_extract_document_pdf_roundtrip(tmp_path):
    pypdf = __import__("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "blank.pdf"
    with path.open("wb") as f:
        writer.write(f)

    doc = extract_document(path)
    assert doc is not None
    assert doc.file_type == "pdf"
    # A blank page has no extractable text, but extraction shouldn't raise.
    assert doc.text == ""


def test_extract_document_docx_roundtrip(tmp_path):
    docx = __import__("docx")
    document = docx.Document()
    document.add_paragraph("Sleep Deprivation and Adolescent Decision-Making")
    document.add_paragraph("This paper studies the effect of sleep loss on risk-taking.")
    document.core_properties.title = "Sleep Deprivation and Adolescent Decision-Making"
    document.core_properties.author = "Jane Doe"
    path = tmp_path / "manuscript.docx"
    document.save(str(path))

    doc = extract_document(path)
    assert doc is not None
    assert doc.file_type == "docx"
    assert doc.title_hint == "Sleep Deprivation and Adolescent Decision-Making"
    assert doc.author_hint == "Jane Doe"
    assert "risk-taking" in doc.text


def test_extract_document_handles_corrupt_file_gracefully(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not actually a pdf")
    assert extract_document(path) is None


def test_extract_pdf_keeps_all_pages_no_truncation():
    """The old MAX_PDF_PAGES=4 cap would have dropped everything past page
    4 — "the pdf extract needs to be the entire copy". Simulated with a
    mocked reader since pypdf alone can't render real text into test
    fixtures."""
    from unittest.mock import MagicMock, patch

    from thesis_tools.library.extract import extract_pdf

    fake_pages = []
    for i in range(30):
        page = MagicMock()
        page.extract_text.return_value = f"Real content for page {i}. " * 50
        fake_pages.append(page)
    fake_reader = MagicMock()
    fake_reader.pages = fake_pages
    fake_reader.metadata = None

    with patch("pypdf.PdfReader", return_value=fake_reader):
        doc = extract_pdf(Path("fake.pdf"))

    assert "[Page 1]" in doc.text
    assert "[Page 30]" in doc.text
    assert len(doc.text) > 30000  # comfortably past the old 8000-char cap


def test_extract_pdf_no_character_cap():
    from unittest.mock import MagicMock, patch

    from thesis_tools.library.extract import extract_pdf

    huge_text = "word " * 20000  # ~100,000 characters on a single page
    page = MagicMock()
    page.extract_text.return_value = huge_text
    fake_reader = MagicMock()
    fake_reader.pages = [page]
    fake_reader.metadata = None

    with patch("pypdf.PdfReader", return_value=fake_reader):
        doc = extract_pdf(Path("fake.pdf"))

    assert len(doc.text) > 90000


def test_extract_txt_not_truncated_for_large_files(tmp_path):
    path = tmp_path / "big.txt"
    big_content = "word " * 20000  # ~100,000 characters, well past the old 8000-char cap
    path.write_text(big_content, encoding="utf-8")
    doc = extract_txt(path)
    assert len(doc.text) == len(big_content)


def test_extract_docx_keeps_all_paragraphs(tmp_path):
    docx = __import__("docx")
    document = docx.Document()
    for i in range(2000):  # past the old 1500-paragraph cap
        document.add_paragraph(f"Paragraph number {i} about sleep deprivation.")
    path = tmp_path / "long.docx"
    document.save(str(path))

    from thesis_tools.library.extract import extract_docx

    doc = extract_docx(path)
    assert "Paragraph number 0 " in doc.text
    assert "Paragraph number 1999 " in doc.text
