from thesis_tools.library.index_store import LibraryEntry, LibraryIndex
from thesis_tools.library.literature_matrix import build_literature_matrix_workbook
from thesis_tools.sources.base import Paper
from thesis_tools.subquestions import analyze_subquestions


def _entry(title, year=2020, doi=None, confidence="verified-doi", venue=None, authors=None, abstract=None):
    return LibraryEntry(
        file_path=f"/x/{title}.pdf",
        file_hash=f"hash-{title}",
        file_type="pdf",
        size_bytes=100,
        indexed_at="2026-01-01T00:00:00",
        confidence=confidence,
        doi=doi,
        paper=Paper(title=title, authors=authors or ["Jane Doe"], year=year, doi=doi, venue=venue, abstract=abstract),
    )


def _rows(wb):
    ws = wb.active
    return list(ws.iter_rows(values_only=True))


def test_empty_index_has_only_header_row():
    wb = build_literature_matrix_workbook(LibraryIndex())
    rows = _rows(wb)
    assert len(rows) == 1
    assert rows[0][0] == "#"


def test_base_columns_present_without_subquestions_or_research_question():
    entry = _entry("A Paper", venue="Journal X", abstract="An abstract.")
    wb = build_literature_matrix_workbook(LibraryIndex([entry]))
    header, row = _rows(wb)
    assert header == ("#", "Citation", "Authors", "Year", "Title", "Source / Venue", "DOI", "Verification", "Summary", "Local file")
    assert row[0] == 1
    assert "Doe" in row[1]  # citation
    assert row[2] == "Jane Doe"
    assert row[3] == 2020
    assert row[4] == "A Paper"
    assert row[5] == "Journal X"
    assert row[7] == "Verified (DOI)"
    assert row[8] == "An abstract."
    assert row[9] == "/x/A Paper.pdf"


def test_citation_uses_configured_style():
    entry = _entry("A Paper", doi="10.1/a")
    wb = build_literature_matrix_workbook(LibraryIndex([entry]), style="mla")
    _, row = _rows(wb)
    assert row[1].startswith("Doe, Jane.")  # MLA full first-author name


def test_relevance_column_only_added_with_research_question():
    entry = _entry("Digital Transformation and Sustainability", abstract="About digital transformation and sustainability.")
    wb_without = build_literature_matrix_workbook(LibraryIndex([entry]))
    header_without, _ = _rows(wb_without)
    assert "Relevance to research question" not in header_without

    wb_with = build_literature_matrix_workbook(LibraryIndex([entry]), research_question="digital transformation sustainability")
    header_with, row_with = _rows(wb_with)
    assert "Relevance to research question" in header_with
    idx = header_with.index("Relevance to research question")
    assert isinstance(row_with[idx], float)


def test_subquestion_columns_reflect_stance_analysis():
    question = "Does sleep deprivation affect adolescent decision-making?"
    supports_entry = _entry(
        "Supporting Paper",
        abstract="We find a significant effect of sleep deprivation on adolescent decision-making, consistent with theory.",
    )
    challenges_entry = _entry(
        "Challenging Paper",
        abstract="Contrary to expectations, we found no significant effect of sleep deprivation on adolescent decision-making.",
    )
    index = LibraryIndex([supports_entry, challenges_entry])
    analysis = analyze_subquestions([question], [supports_entry.paper, challenges_entry.paper], use_llm=False)

    wb = build_literature_matrix_workbook(index, sub_questions=[question], analysis=analysis)
    header, row1, row2 = _rows(wb)
    assert header[-1] == f"Q: {question}"
    assert row1[-1] == "Supports"
    assert row2[-1] == "Challenges"


def test_subquestion_column_blank_without_analysis():
    question = "Does X affect Y?"
    entry = _entry("A Paper", abstract="An abstract.")
    wb = build_literature_matrix_workbook(LibraryIndex([entry]), sub_questions=[question], analysis=None)
    _, row = _rows(wb)
    assert row[-1] == ""


def test_long_subquestion_header_is_truncated():
    question = "Q" * 100 + "?"
    entry = _entry("A Paper")
    wb = build_literature_matrix_workbook(LibraryIndex([entry]), sub_questions=[question])
    header, _ = _rows(wb)
    assert len(header[-1]) <= 65  # "Q: " prefix + truncated text + ellipsis
    assert header[-1].endswith("…")


def test_ieee_style_numbers_citations_by_row():
    entries = [_entry("First Paper", doi="10.1/first"), _entry("Second Paper", doi="10.1/second")]
    wb = build_literature_matrix_workbook(LibraryIndex(entries), style="ieee")
    _, row1, row2 = _rows(wb)
    assert row1[1].startswith("[1]")
    assert row2[1].startswith("[2]")


def test_freeze_panes_and_autofilter_set():
    entry = _entry("A Paper")
    wb = build_literature_matrix_workbook(LibraryIndex([entry]))
    ws = wb.active
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref is not None
