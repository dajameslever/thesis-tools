"""Part 2 add-on: an Excel "synthesis matrix" — one row per indexed paper,
in the format literature-review guidance from university writing centers
recommends for tracking sources during a review (citation, key metadata,
a short summary, and how each paper relates to each of your research
questions), so the visualization has something a student can actually
work from outside a browser — filter, sort, add their own notes column,
or hand to a supervisor.

Pure local computation, same as visualize.py: reuses whatever stance
analysis compute_stats() already ran (or the free extractive summarizer)
rather than triggering its own Claude calls.
"""

from __future__ import annotations

from typing import List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..citations import format_citation
from ..relevance import score_relevance
from ..sources.base import Paper
from ..subquestions import SubquestionAnalysis
from ..summarize import extractive_summary
from .index_store import LibraryIndex

CONFIDENCE_DISPLAY = {
    "verified-doi": "Verified (DOI)",
    "verified-title-match": "Verified (title match)",
    "unresolved": "Unresolved",
}

STANCE_DISPLAY = {
    "supports": "Supports",
    "challenges": "Challenges",
    "mixed": "Mixed",
    "unrelated": "Unrelated",
}

_HEADER_FILL = PatternFill(start_color="2A2A2A", end_color="2A2A2A", fill_type="solid")
_WRAP = Alignment(wrap_text=True, vertical="top")
_BASE_FONT = "Calibri"

# Base columns every matrix has, before the one-per-sub-question stance
# columns tacked on at the end. (header, width, wrap)
_BASE_COLUMNS = [
    ("#", 5, False),
    ("Citation", 46, True),
    ("Authors", 24, True),
    ("Year", 8, False),
    ("Title", 36, True),
    ("Source / Venue", 24, True),
    ("DOI", 20, False),
    ("Verification", 20, False),
    ("Summary", 50, True),
]
_RELEVANCE_COLUMN = ("Relevance to research question", 14, False)
_FILE_COLUMN = ("Local file", 30, True)


def _authors_display(paper: Paper) -> str:
    return "; ".join(paper.authors) if paper.authors else "n.a."


def _summary_for(paper: Paper, research_question: Optional[str]) -> str:
    text = paper.abstract or paper.full_text_excerpt
    if not text:
        return ""
    # Free, local, deterministic — same extractive summarizer summarize.py
    # falls back to without an LLM. Never triggers a Claude call of its own;
    # this workbook is meant to be regenerated as often as the HTML page.
    return extractive_summary(text, research_question or paper.title, max_sentences=2) or ""


def build_literature_matrix_workbook(
    index: LibraryIndex,
    style: str = "apa",
    sub_questions: Optional[List[str]] = None,
    research_question: Optional[str] = None,
    analysis: Optional[SubquestionAnalysis] = None,
) -> Workbook:
    """One row per indexed paper. `analysis`, when given (compute_stats()
    already builds one whenever sub_questions are set), supplies the
    supports/challenges/mixed/unrelated column per sub-question — passed in
    rather than recomputed here so this never triggers a second round of
    Claude calls on top of whatever the HTML page already made."""
    sub_questions = sub_questions or []

    wb = Workbook()
    ws: Worksheet = wb.active
    ws.title = "Literature Review Matrix"

    columns = list(_BASE_COLUMNS)
    if research_question:
        columns.append(_RELEVANCE_COLUMN)
    columns.append(_FILE_COLUMN)
    stance_col_start = len(columns)  # 0-indexed position of the first stance column
    for q in sub_questions:
        # Truncate a long sub-question for the header cell itself; the full
        # text goes in a comment-free first data note instead — a header
        # row needs to stay one line to keep the sheet usable.
        label = q if len(q) <= 60 else q[:57] + "…"
        columns.append((f"Q: {label}", 22, True))

    for col_idx, (header, width, _wrap) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(name=_BASE_FONT, bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    row_idx = 2
    for i, entry in enumerate(index.entries, start=1):
        paper = entry.paper
        row = [
            i,
            format_citation(paper, style, ref_number=i if style.lower() == "ieee" else None),
            _authors_display(paper),
            paper.year or "",
            paper.title,
            paper.venue or "",
            paper.doi or "",
            CONFIDENCE_DISPLAY.get(entry.confidence, entry.confidence),
            _summary_for(paper, research_question),
        ]
        if research_question:
            row.append(round(score_relevance(research_question, paper), 2))
        row.append(entry.file_path)

        stances = analysis.stances_for(paper) if analysis else {}
        for q in sub_questions:
            stance = stances.get(q)
            row.append(STANCE_DISPLAY.get(stance.stance, "") if stance else "")

        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = Font(name=_BASE_FONT)
            if columns[col_idx - 1][2]:
                cell.alignment = _WRAP
        row_idx += 1

    last_col_letter = get_column_letter(len(columns))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{last_col_letter}{max(row_idx - 1, 1)}"
    return wb
