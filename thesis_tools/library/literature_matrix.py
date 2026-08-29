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
from ..recency import age_years
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


# The critical questions a taught dissertation bootcamp hands out as a
# "criticality chart" — questions down the side, one column per paper. Kept
# verbatim, because the value of a chart like this is that it is the same
# set of questions every time, asked of every paper.
#
# Each carries a filler: a callable that returns what the toolkit can
# honestly answer for a paper, or None where only the student can. A blank
# cell here is not a gap in the tool — it is the question being put to the
# reader, which is the entire point of the exercise. Pre-filling "is there
# bias?" with a guess would replace judgement with the appearance of it.
CRITICAL_QUESTIONS = [
    "Is the research relevant?",
    "Is the research biased?",
    "Is the research specific?",
    "Is the evidence valid?",
    "What is the evidence?",
    "Is the evidence robust?",
    "What is the main argument?",
    "Who agrees or disagrees with this stance?",
    "What are the conclusions that are drawn?",
    "What are the gaps, in this theory, work or, argument, research?",
    "Is the research or theory a product of its time?",
    "Is the sample appropriate for the conclusions drawn from it?",
    "What are the main themes?",
]

# How many papers get a column. The chart is for the papers being appraised
# closely, not the whole library: eighty columns is not a working document.
MAX_CRITICALITY_PAPERS = 15

# The reading log from the same material. Columns the student fills while
# reading are left empty on purpose — a log with the reflection already
# written is not a reading log.
READING_LOG_COLUMNS = [
    ("Title", 34, True, True),
    ("Author / Date", 22, True, True),
    ("Text (exact)", 40, True, False),
    ("What it means to me", 34, True, False),
    ("How it relates to what others say", 34, True, True),
    ("Argument link", 28, True, False),
    ("My summary", 40, True, True),
]


def _relevance_note(paper: Paper, research_question: Optional[str]) -> Optional[str]:
    if not research_question:
        return None
    score = score_relevance(research_question, paper)
    verdict = "strong" if score >= 0.35 else "moderate" if score >= 0.15 else "weak"
    return f"{verdict} keyword overlap with the research question ({score:.2f}) — your call"


def _age_note(paper: Paper) -> Optional[str]:
    if not paper.year:
        return None
    age = age_years(paper.year)
    if age is None:
        return None
    return f"published {paper.year} ({age} year(s) old)"


# Enough names to see the shape of the agreement without turning a cell
# into a bibliography.
_MAX_NAMED_PEERS = 3


def _short_ref(title: str) -> str:
    return title if len(title) <= 60 else title[:57] + "…"


def _peer_list(titles: List[str], exclude: str) -> str:
    others = [t for t in titles if t != exclude]
    if not others:
        return ""
    shown = "; ".join(_short_ref(t) for t in others[:_MAX_NAMED_PEERS])
    extra = len(others) - _MAX_NAMED_PEERS
    return shown + (f" (+{extra} more)" if extra > 0 else "")


def _agreement_note(paper: Paper, sub_questions: List[str], analysis: Optional[SubquestionAnalysis]) -> Optional[str]:
    """Who else in the library takes the same view, and who takes the
    opposite one. This is the one critical question the toolkit can answer
    better than the student can from memory: it has already classified every
    paper against every sub-question, so it can name the peers rather than
    leaving "who agrees?" as another blank to fill in."""
    if not analysis or not sub_questions:
        return None
    stances = analysis.stances_for(paper)
    lines = []
    for i, question in enumerate(sub_questions, start=1):
        stance = stances.get(question)
        if not stance or stance.stance == "unrelated":
            continue
        label = STANCE_DISPLAY.get(stance.stance, stance.stance)
        grouped = analysis.titles_by_stance(question) if hasattr(analysis, "titles_by_stance") else {}
        agreeing = _peer_list(grouped.get(stance.stance, []), paper.title)
        opposite = "challenges" if stance.stance == "supports" else "supports"
        disagreeing = _peer_list(grouped.get(opposite, []), paper.title)
        parts = [f"Q{i} ({label})"]
        if agreeing:
            parts.append(f"agrees with: {agreeing}")
        if disagreeing:
            parts.append(f"disagrees with: {disagreeing}")
        if not agreeing and not disagreeing:
            parts.append("no other paper in the library takes a position")
        lines.append(" — ".join(parts))
    return "\n".join(lines) if lines else None


def _themes_note(paper: Paper, themes: Optional[List[dict]]) -> Optional[str]:
    if not themes:
        return None
    key = paper.key()
    hits = [t["label"] for t in themes if any(p.get("key") == key for p in t.get("papers", []))]
    return ", ".join(hits[:8]) if hits else None


def _add_criticality_sheet(
    wb: Workbook,
    index: LibraryIndex,
    sub_questions: List[str],
    research_question: Optional[str],
    analysis: Optional[SubquestionAnalysis],
    themes: Optional[List[dict]],
) -> None:
    entries = list(index.entries)
    if research_question:
        entries.sort(key=lambda e: score_relevance(research_question, e.paper), reverse=True)
    entries = entries[:MAX_CRITICALITY_PAPERS]
    if not entries:
        return

    ws = wb.create_sheet("Criticality")
    ws.cell(row=1, column=1, value="Critical question").font = Font(name=_BASE_FONT, bold=True, color="FFFFFF")
    ws.cell(row=1, column=1).fill = _HEADER_FILL
    ws.column_dimensions["A"].width = 44

    for col, entry in enumerate(entries, start=2):
        paper = entry.paper
        author = paper.authors[0].split()[-1] if paper.authors and paper.authors[0].split() else "n.a."
        cell = ws.cell(row=1, column=col, value=f"{author} ({paper.year or 'n.d.'})\n{paper.title}")
        cell.font = Font(name=_BASE_FONT, bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = 34

    fillers = {
        "Is the research relevant?": lambda p: _relevance_note(p, research_question),
        "Who agrees or disagrees with this stance?": lambda p: _agreement_note(p, sub_questions, analysis),
        "Is the research or theory a product of its time?": _age_note,
        "What are the main themes?": lambda p: _themes_note(p, themes),
    }

    for row, question in enumerate(CRITICAL_QUESTIONS, start=2):
        label = ws.cell(row=row, column=1, value=question)
        label.font = Font(name=_BASE_FONT, bold=True)
        label.alignment = _WRAP
        filler = fillers.get(question)
        for col, entry in enumerate(entries, start=2):
            value = filler(entry.paper) if filler else None
            cell = ws.cell(row=row, column=col, value=value or "")
            cell.font = Font(name=_BASE_FONT)
            cell.alignment = _WRAP
        ws.row_dimensions[row].height = 46

    ws.freeze_panes = "B2"


def _add_reading_log_sheet(
    wb: Workbook,
    index: LibraryIndex,
    sub_questions: List[str],
    research_question: Optional[str],
    analysis: Optional[SubquestionAnalysis],
) -> None:
    ws = wb.create_sheet("Reading log")
    for col, (header, width, _wrap, prefilled) in enumerate(READING_LOG_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=header if prefilled else f"{header} (yours to write)")
        cell.font = Font(name=_BASE_FONT, bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = width

    for row, entry in enumerate(index.entries, start=2):
        paper = entry.paper
        author = "; ".join(paper.authors) if paper.authors else "n.a."
        values = [
            paper.title,
            f"{author} ({paper.year or 'n.d.'})",
            "",  # the exact wording is copied out while reading, by the reader
            "",  # what it means to me
            _agreement_note(paper, sub_questions, analysis) or "",
            "",  # argument link
            _summary_for(paper, research_question),
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = Font(name=_BASE_FONT)
            cell.alignment = _WRAP
        ws.row_dimensions[row].height = 58

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(READING_LOG_COLUMNS))}{max(len(index.entries) + 1, 1)}"


def build_literature_matrix_workbook(
    index: LibraryIndex,
    style: str = "apa",
    sub_questions: Optional[List[str]] = None,
    research_question: Optional[str] = None,
    analysis: Optional[SubquestionAnalysis] = None,
    themes: Optional[List[dict]] = None,
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

    # Two more sheets from the same taught material: the criticality chart
    # (the same questions asked of every paper) and the reading log. Both are
    # working documents rather than reports, so both are deliberately part
    # blank — see CRITICAL_QUESTIONS and READING_LOG_COLUMNS.
    _add_criticality_sheet(wb, index, sub_questions, research_question, analysis, themes)
    _add_reading_log_sheet(wb, index, sub_questions, research_question, analysis)
    return wb
