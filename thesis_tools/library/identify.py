"""Turn an ExtractedDocument into a (hopefully verified) Paper record.

Strategy, in order:
  1. Look for a DOI in the extracted text and resolve it against Crossref
     (falling back to Semantic Scholar) — this gives fully canonical
     metadata when it works.
  2. Otherwise, build a best-effort title from file metadata / the text
     itself, and try to confirm it via a title search against the same
     two sources. A high title-similarity hit is treated as verified.
  3. Otherwise, fall back to whatever local heuristics found — flagged
     "unresolved" so the user knows to check it by hand.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from ..relevance import title_similarity
from ..sources.base import Paper
from ..sources.crossref import CrossrefClient
from ..sources.semantic_scholar import SemanticScholarClient
from .extract import ExtractedDocument

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_TRAILING_PUNCT = ").,;:]}>”’\""
_GENERIC_TITLE_RE = re.compile(r"^(microsoft word|untitled|document\d*|draft\d*)\b", re.I)

TITLE_MATCH_THRESHOLD = 0.85

# A paper's own DOI is essentially always printed on its title page (header,
# footer, or a "https://doi.org/..." line near the top) — never mined from
# deep in the body. extract.py now keeps the WHOLE document, bibliography
# included, and a reference list is often packed with other papers' DOIs.
# Searching the whole text would (a) very often pick up a citation's DOI
# instead of the paper's own, and (b) mean identify_document() below tries
# several of them in turn, each a real network round-trip — several minutes
# of stall for one file. Restricting the search window to roughly the first
# page keeps this fast and (more importantly) actually correct.
_DOI_SEARCH_WINDOW_CHARS = 3000


@dataclass
class IdentifiedPaper:
    paper: Paper
    confidence: str  # "verified-doi" | "verified-title-match" | "unresolved"
    matched_doi: Optional[str] = None
    # Lightweight {"doi", "title", "year"} records for papers *this* paper
    # cites — used for the citation-coverage view. Only populated when a DOI
    # was resolved and fetch_references=True was requested.
    references: List[dict] = field(default_factory=list)


def find_dois(text: str, max_results: int = 5, search_window_chars: int = _DOI_SEARCH_WINDOW_CHARS) -> List[str]:
    """DOI candidates likely to be the document's OWN identifier — restricted
    to a leading window of the text (see _DOI_SEARCH_WINDOW_CHARS) rather
    than the whole document, so a long bibliography full of other papers'
    DOIs doesn't get searched at all."""
    candidates: List[str] = []
    window = (text or "")[:search_window_chars]
    for m in _DOI_RE.finditer(window):
        doi = m.group(0).rstrip(_TRAILING_PUNCT)
        if doi and doi not in candidates:
            candidates.append(doi)
        if len(candidates) >= max_results:
            break
    return candidates


def guess_year(text: str) -> Optional[int]:
    years = [int(y) for y in _YEAR_RE.findall(text or "")]
    if not years:
        return None
    return Counter(years).most_common(1)[0][0]


def clean_title_hint(hint: Optional[str]) -> Optional[str]:
    if not hint:
        return None
    hint = hint.strip()
    if not hint or _GENERIC_TITLE_RE.match(hint):
        return None
    return hint


def guess_title_from_text(text: str) -> Optional[str]:
    for line in (text or "").splitlines():
        line = line.strip()
        if 15 <= len(line) <= 220 and not line.isupper():
            return line
    return None


def _reference_dicts(papers: List[Paper]) -> List[dict]:
    return [{"doi": p.doi, "title": p.title, "year": p.year} for p in papers if p.title]


def fetch_references_for_doi(
    doi: str, semantic_scholar_client: Optional[SemanticScholarClient] = None
) -> List[dict]:
    """The reference list for one already-identified paper, in the same
    lightweight shape identify_document() stores.

    Split out from identify_document() so an existing index entry can have
    its references backfilled without re-extracting the PDF and re-running
    the whole DOI/title identification it already passed once. Returns []
    on any lookup failure, same as everything else here.
    """
    client = semantic_scholar_client or SemanticScholarClient()
    return _reference_dicts(client.lookup_references(doi))


def local_heuristic_fallback(doc: ExtractedDocument, filename_fallback: str) -> IdentifiedPaper:
    """Build a record from the file itself alone — no network involved. This
    is what a normal, no-match run of identify_document() falls back to; it's
    also called directly by the indexer if identify_document() raises
    unexpectedly, so a lookup blowing up never means losing what the PDF
    already told us, just skipping the verification step."""
    heuristic_title = clean_title_hint(doc.title_hint) or guess_title_from_text(doc.text) or filename_fallback
    fallback = Paper(
        title=heuristic_title,
        authors=[doc.author_hint] if doc.author_hint else [],
        year=guess_year(doc.text),
        sources=["local-heuristic"],
    )
    return IdentifiedPaper(paper=fallback, confidence="unresolved")


def identify_document(
    doc: ExtractedDocument,
    filename_fallback: str,
    contact_email: Optional[str] = None,
    fetch_references: bool = False,
    crossref_client: Optional[CrossrefClient] = None,
    semantic_scholar_client: Optional[SemanticScholarClient] = None,
) -> IdentifiedPaper:
    crossref = crossref_client or CrossrefClient(mailto=contact_email)
    semantic_scholar = semantic_scholar_client or SemanticScholarClient()

    # 1. DOI-based lookup — most reliable when it works.
    doi_candidates = find_dois(doc.text)
    if doi_candidates:
        print(f"    found {len(doi_candidates)} candidate DOI(s) near the start of the document: {', '.join(doi_candidates)}", file=sys.stderr)
    for i, doi in enumerate(doi_candidates, start=1):
        print(f"    [{i}/{len(doi_candidates)}] resolving {doi} against Crossref...", file=sys.stderr)
        paper = crossref.lookup_doi(doi)
        if paper is None:
            print(f"    [{i}/{len(doi_candidates)}] not on Crossref, trying Semantic Scholar...", file=sys.stderr)
            paper = semantic_scholar.lookup_doi(doi)
        if paper is not None:
            print(f"    -> resolved via DOI {doi}", file=sys.stderr)
            references = []
            if fetch_references:
                print("    fetching this paper's own reference list from Semantic Scholar...", file=sys.stderr)
                references = _reference_dicts(semantic_scholar.lookup_references(doi))
            return IdentifiedPaper(paper=paper, confidence="verified-doi", matched_doi=doi, references=references)

    # 2. Heuristic title, confirmed via a title search.
    heuristic_title = clean_title_hint(doc.title_hint) or guess_title_from_text(doc.text) or filename_fallback
    print(f"    no DOI resolved — searching by title: \"{heuristic_title}\"...", file=sys.stderr)

    candidates: List[Paper] = []
    for client in (crossref, semantic_scholar):
        candidates.extend(client.search(heuristic_title, limit=3))

    best: Optional[Paper] = None
    best_similarity = 0.0
    for candidate in candidates:
        similarity = title_similarity(heuristic_title, candidate.title)
        if similarity > best_similarity:
            best, best_similarity = candidate, similarity

    if best is not None and best_similarity >= TITLE_MATCH_THRESHOLD:
        references = []
        if fetch_references and best.doi:
            references = _reference_dicts(semantic_scholar.lookup_references(best.doi))
        return IdentifiedPaper(paper=best, confidence="verified-title-match", matched_doi=best.doi, references=references)

    # 3. Local heuristics only — needs a manual check.
    return local_heuristic_fallback(doc, filename_fallback)
