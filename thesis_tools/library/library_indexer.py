"""Part 2: Library Indexer — orchestrates scan/extract/identify/store/report."""

from __future__ import annotations

import datetime as _dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from .. import llm
from ..citations import STYLES
from ..relevance import score_relevance
from ..sources.base import slug_for_paper
from ..subquestions import analyze_subquestions
from ..summarize import summarize
from .extract import extract_document
from .identify import identify_document, local_heuristic_fallback
from .index_store import LibraryEntry, LibraryIndex, hash_file
from .organizer import organize_entries
from .report import build_library_report

DEFAULT_EXTENSIONS = [".pdf", ".docx", ".txt", ".html", ".htm"]


@dataclass
class LibraryIndexerInputs:
    folder: str
    recursive: bool = True
    extensions: Optional[List[str]] = None
    index_path: str = "library/index.json"
    style: str = "apa"
    report_path: Optional[str] = None
    rescan: bool = False
    prune: bool = False
    organize: bool = False
    organize_to: str = "library/organized"
    contact_email: Optional[str] = None
    fetch_references: bool = False
    research_question: Optional[str] = None
    sub_questions: Optional[List[str]] = None
    use_llm: bool = False
    llm_model: str = "claude-sonnet-5"
    # Where each file's extracted text is also saved as a plain .txt, one per
    # paper, so you can inspect exactly what was extracted (and confirm it's
    # the whole document, not a prefix) without opening the JSON index. Same
    # `processed/text/` location and naming Part 1's --download-papers uses,
    # so both land in one place.
    processed_dir: str = "processed"


def _normalize_extensions(extensions: Optional[List[str]]) -> List[str]:
    raw = extensions or DEFAULT_EXTENSIONS
    return [e.lower() if e.startswith(".") else f".{e.lower()}" for e in raw]


def _iter_files(folder: Path, recursive: bool, extensions: List[str], exclude_dir: Path) -> Iterator[Path]:
    walker = folder.rglob("*") if recursive else folder.glob("*")
    exclude_dir = exclude_dir.resolve()
    for path in walker:
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        if exclude_dir.exists() and path.resolve().is_relative_to(exclude_dir):
            continue  # don't re-index our own --organize output
        yield path


def run_library_indexer(inputs: LibraryIndexerInputs) -> Dict[str, object]:
    folder = Path(inputs.folder).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Folder not found: {folder}")

    if inputs.style.lower() not in STYLES:
        raise ValueError(f"Unknown citation style '{inputs.style}'. Choose from: {', '.join(STYLES)}")

    if inputs.use_llm:
        issue = llm.availability_issue()
        if issue:
            print(f"Claude requested but unavailable ({issue}) — using heuristics for this run.", file=sys.stderr)

    extensions = _normalize_extensions(inputs.extensions)
    index_path = Path(inputs.index_path)
    organize_to = Path(inputs.organize_to).expanduser()

    index = LibraryIndex.load(index_path)
    existing_by_hash = index.by_hash()

    files = list(_iter_files(folder, inputs.recursive, extensions, organize_to))
    print(
        f"Found {len(files)} file(s) in {folder} matching {', '.join(extensions)}"
        + (" (scanning subfolders too)" if inputs.recursive else ""),
        file=sys.stderr,
    )
    if inputs.fetch_references:
        print(
            "Fetching each paper's own reference list too (--fetch-references) — this is the slow part, "
            "one extra Semantic Scholar call per file.",
            file=sys.stderr,
        )

    new_count = skipped_count = failed_count = 0

    for i, path in enumerate(files, start=1):
        progress = f"[{i}/{len(files)}]"
        try:
            file_hash = hash_file(path)
        except Exception as exc:
            print(f"{progress} couldn't read {path} ({exc}), skipping", file=sys.stderr)
            failed_count += 1
            continue

        if not inputs.rescan and file_hash in existing_by_hash:
            print(f"{progress} {path.name} — unchanged since last run, skipping", file=sys.stderr)
            skipped_count += 1
            continue

        print(f"{progress} {path.name} — extracting text...", file=sys.stderr)
        doc = extract_document(path)
        if doc is None or not (doc.text.strip() or doc.title_hint):
            print(f"  [index] no usable text/metadata in {path}, skipping", file=sys.stderr)
            failed_count += 1
            continue

        filename_fallback = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
        print(f"  looking up DOI/title against Crossref + Semantic Scholar...", file=sys.stderr)
        try:
            identified = identify_document(
                doc,
                filename_fallback=filename_fallback,
                contact_email=inputs.contact_email,
                fetch_references=inputs.fetch_references,
            )
        except Exception as exc:
            # A lookup blowing up (a flaky API, an unexpected response shape)
            # must never mean losing what we already know about this paper
            # from the file itself, and must never abort indexing every
            # other file in the folder either. Fall back to the same
            # local-heuristics-only record identify_document() itself would
            # return for "nothing verified" — flagged unresolved for a
            # manual check — rather than dropping the file.
            print(
                f"  [index] verification failed for {path} ({exc}) — indexing from local file metadata only",
                file=sys.stderr,
            )
            identified = local_heuristic_fallback(doc, filename_fallback)

        if identified.confidence == "verified-doi":
            print(f"  -> verified via DOI ({identified.matched_doi})", file=sys.stderr)
        elif identified.confidence == "verified-title-match":
            print(f'  -> verified via title match: "{identified.paper.title}"', file=sys.stderr)
        else:
            print("  -> unresolved — no confident DOI/title match, using local file metadata only", file=sys.stderr)
        if inputs.fetch_references:
            print(f"  -> {len(identified.references)} reference(s) fetched for the citation-coverage view", file=sys.stderr)

        # Attach the actual extracted text (not just the resolved metadata) so
        # Part 3 can quote real wording from this paper instead of just its
        # abstract — regardless of whether identification came from a DOI
        # lookup, a title match, or local heuristics.
        identified.paper.full_text_excerpt = doc.text or None

        if doc.text:
            text_dir = Path(inputs.processed_dir) / "text"
            text_dir.mkdir(parents=True, exist_ok=True)
            text_path = text_dir / f"{slug_for_paper(identified.paper)}.txt"
            text_path.write_text(doc.text, encoding="utf-8")
            print(f"  -> saved extracted text to {text_path}", file=sys.stderr)

        entry = LibraryEntry(
            file_path=str(path),
            file_hash=file_hash,
            file_type=doc.file_type,
            size_bytes=path.stat().st_size,
            indexed_at=_dt.datetime.now().isoformat(timespec="seconds"),
            confidence=identified.confidence,
            doi=identified.matched_doi,
            paper=identified.paper,
            references=identified.references,
        )
        index.upsert(entry)
        existing_by_hash[file_hash] = entry
        new_count += 1

    pruned_count = index.prune_missing() if inputs.prune else 0

    index.save(index_path)

    # Relevance/stance/summaries are recomputed fresh on every run from
    # whatever's already in the index — never cached — so editing
    # --question/--sub-questions and re-running updates them immediately,
    # with no need to rescan or re-fetch anything.
    summaries: Dict[str, str] = {}
    relevance_scores: Dict[str, float] = {}
    for entry in index.entries:
        key = entry.paper.key()
        # "What it's about" doesn't need a research question — fall back to the
        # paper's own title so the extractive summarizer still has something
        # to rank sentences against.
        summary_context = inputs.research_question or entry.paper.title
        summary = summarize(
            entry.paper.abstract,
            entry.paper.title,
            summary_context,
            use_llm=inputs.use_llm,
            model=inputs.llm_model,
            full_text_excerpt=entry.paper.full_text_excerpt,
        )
        if summary:
            summaries[key] = summary
        if inputs.research_question:
            relevance_scores[key] = score_relevance(inputs.research_question, entry.paper)

    subquestion_analysis = None
    if inputs.sub_questions:
        subquestion_analysis = analyze_subquestions(
            inputs.sub_questions,
            [e.paper for e in index.entries],
            use_llm=inputs.use_llm,
            model=inputs.llm_model,
        )

    report_path = Path(inputs.report_path) if inputs.report_path else index_path.parent / "library.md"
    report_text = build_library_report(
        index,
        style=inputs.style,
        research_question=inputs.research_question,
        subquestion_analysis=subquestion_analysis,
        summaries=summaries,
        relevance_scores=relevance_scores,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    organized: List = []
    if inputs.organize:
        organized = organize_entries(index.entries, organize_to)

    return {
        "index_path": str(index_path),
        "report_path": str(report_path),
        "new": new_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "pruned": pruned_count,
        "total": len(index.entries),
        "organized": len(organized),
    }
