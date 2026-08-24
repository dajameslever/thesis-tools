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
from ..sources.base import Paper, slug_for_paper
from ..subquestions import analyze_subquestions
from ..summarize import summarize
from .extract import extract_document
from .identify import fetch_references_for_doi, identify_document, local_heuristic_fallback
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
    # Every Claude call this command makes is bulk, per-paper work
    # (summaries, sub-question stance classification) — no one-shot
    # "quality" task to reserve a pricier model for, unlike Part 1's
    # sub-question generation or Part 3's drafting. See llm.py.
    llm_model: str = llm.DEFAULT_EXTRACTION_MODEL
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
    backfilled_count = no_doi_count = 0

    for i, path in enumerate(files, start=1):
        progress = f"[{i}/{len(files)}]"
        try:
            file_hash = hash_file(path)
        except Exception as exc:
            print(f"{progress} couldn't read {path} ({exc}), skipping", file=sys.stderr)
            failed_count += 1
            continue

        if not inputs.rescan and file_hash in existing_by_hash:
            existing = existing_by_hash[file_hash]
            # An unchanged file is skipped — but --fetch-references on an
            # already-indexed library used to skip right past this point and
            # change nothing, so the citation views kept telling the user to
            # run the very command they had just run. The file's content is
            # what's unchanged; its reference list is simply absent, and
            # fetching it needs no re-extraction and no re-identification —
            # just one lookup against the DOI this entry already resolved.
            existing_doi = existing.doi or existing.paper.doi
            if inputs.fetch_references and not existing.references and existing_doi:
                print(f"{progress} {path.name} — unchanged, fetching its reference list...", file=sys.stderr)
                existing.references = fetch_references_for_doi(existing_doi)
                print(f"  -> {len(existing.references)} reference(s) fetched", file=sys.stderr)
                backfilled_count += 1
            elif inputs.fetch_references and not existing.references:
                # No DOI ever resolved for this file, so there is nothing to
                # ask Semantic Scholar about. Counted and reported rather
                # than passed over in silence — it is the same unresolved
                # files that hollow out every other view.
                print(
                    f"{progress} {path.name} — unchanged, but unresolved (no DOI), so it has no "
                    "reference list to fetch",
                    file=sys.stderr,
                )
                no_doi_count += 1
            else:
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

    if inputs.fetch_references:
        with_refs = sum(1 for e in index.entries if e.references)
        print(
            f"Reference lists: {with_refs} of {len(index.entries)} entries now have one"
            + (f" ({backfilled_count} fetched just now)" if backfilled_count else "")
            + (f"; {no_doi_count} unresolved entry/entries have no DOI to fetch against" if no_doi_count else ""),
            file=sys.stderr,
        )

    pruned_count = index.prune_missing() if inputs.prune else 0

    index.save(index_path)

    # Relevance/stance/summaries are recomputed fresh on every run from
    # whatever's already in the index — never cached — so editing
    # --question/--sub-questions and re-running updates them instantly,
    # with no need to rescan or re-fetch anything. This runs over EVERY
    # entry in the index, not just the ones just indexed above, so it's a
    # second slow-ish pass after the per-file loop above finishes — worth
    # its own progress notice, especially with --llm-summaries (a Claude
    # call per paper).
    print(
        f"Scoring relevance and building summaries for {len(index.entries)} paper(s) in the index"
        + (" with Claude..." if inputs.use_llm else "..."),
        file=sys.stderr,
    )
    summaries: Dict[str, str] = {}
    relevance_scores: Dict[str, float] = {}
    for i, entry in enumerate(index.entries, start=1):
        key = entry.paper.key()
        if inputs.use_llm:
            print(f"  [{i}/{len(index.entries)}] {entry.paper.title}", file=sys.stderr)
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
        "references_backfilled": backfilled_count,
        "references_unavailable": no_doi_count,
        "total": len(index.entries),
        "organized": len(organized),
    }


def index_known_papers(papers: List[Paper], dest_dir: str, index_path: str) -> int:
    """Add already-identified papers straight into this library's index —
    used by Part 1's --download-papers, so a paper it finds for the topic/
    sub-questions and downloads shows up in visualize-library and Part 3's
    literature review too, not just topic-finder's own report.

    Unlike run_library_indexer() above, this never runs DOI/title
    identification: the paper's metadata already came straight from a
    source API (Crossref/OpenAlex/Semantic Scholar/arXiv) when Part 1 found
    it, not inferred from a local file's contents, so it's already at least
    as trustworthy as what identify_document() would produce.

    Only considers a paper that actually has extracted text (download_papers
    sets full_text_excerpt on success; a paper with no open-access copy, or
    a failed download, never gets one) and whose PDF is really on disk under
    dest_dir/pdfs — skipping anything else rather than guessing. Loads/saves
    the index only when there is at least one such paper, so a run that
    downloaded nothing never touches (or creates) index_path. Returns how
    many papers were added/updated.
    """
    pdf_dir = Path(dest_dir) / "pdfs"
    to_add: List[tuple] = []
    for paper in papers:
        if not paper.full_text_excerpt:
            continue
        pdf_path = pdf_dir / f"{slug_for_paper(paper)}.pdf"
        if not pdf_path.is_file():
            continue
        to_add.append((paper, pdf_path))

    if not to_add:
        return 0

    path = Path(index_path)
    index = LibraryIndex.load(path)
    for paper, pdf_path in to_add:
        entry = LibraryEntry(
            file_path=str(pdf_path),
            file_hash=hash_file(pdf_path),
            file_type="pdf",
            size_bytes=pdf_path.stat().st_size,
            indexed_at=_dt.datetime.now().isoformat(timespec="seconds"),
            # Already came from a source API's own record, not an inferred
            # match — "verified-doi" when that record includes a DOI,
            # otherwise the paper's title is itself the API's own record
            # (not a guess), so "verified-title-match" fits better than
            # "unresolved".
            confidence="verified-doi" if paper.doi else "verified-title-match",
            doi=paper.doi,
            paper=paper,
        )
        index.upsert(entry)
    index.save(path)
    return len(to_add)
