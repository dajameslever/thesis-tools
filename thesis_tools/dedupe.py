"""Merge duplicate papers returned by multiple sources."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import List

from .sources.base import Paper, normalize_title

FUZZY_TITLE_THRESHOLD = 0.92


def _years_compatible(a: Paper, b: Paper) -> bool:
    """Two papers can only be the same work if their years agree, when both are known."""
    return not (a.year and b.year and a.year != b.year)


def _merge(a: Paper, b: Paper) -> Paper:
    """Merge `b` into `a`, preferring whichever field is populated / richer."""
    a.abstract = a.abstract if (a.abstract and len(a.abstract) >= len(b.abstract or "")) else (b.abstract or a.abstract)
    a.full_text_excerpt = a.full_text_excerpt or b.full_text_excerpt
    a.doi = a.doi or b.doi
    a.venue = a.venue or b.venue
    a.year = a.year or b.year
    a.url = a.url or b.url
    a.volume = a.volume or b.volume
    a.issue = a.issue or b.issue
    a.pages = a.pages or b.pages
    if not a.authors:
        a.authors = b.authors
    if a.citation_count is None:
        a.citation_count = b.citation_count
    elif b.citation_count is not None:
        a.citation_count = max(a.citation_count, b.citation_count)
    for s in b.sources:
        if s not in a.sources:
            a.sources.append(s)
    return a


def dedupe_papers(papers: List[Paper]) -> List[Paper]:
    """Collapse papers that are the same work, merging their metadata.

    Strategy:
      1. Exact match on normalized DOI.
      2. Exact match on normalized title (for papers with no DOI, e.g. arXiv).
      3. Fuzzy title match (same publication year, high string similarity) to
         catch minor formatting differences between sources.
    """
    merged: List[Paper] = []

    for paper in papers:
        match = None

        # 1 & 2: exact key match (DOI, else normalized title)
        for existing in merged:
            if paper.doi and existing.doi and paper.doi.strip().lower() == existing.doi.strip().lower():
                match = existing
                break
            if (
                not paper.doi
                and not existing.doi
                and _years_compatible(paper, existing)
                and normalize_title(paper.title) == normalize_title(existing.title)
            ):
                match = existing
                break

        # 3: fuzzy title match, only when neither has already matched and years agree (or are unknown)
        if match is None:
            for existing in merged:
                if not _years_compatible(paper, existing):
                    continue
                ratio = SequenceMatcher(None, normalize_title(paper.title), normalize_title(existing.title)).ratio()
                if ratio >= FUZZY_TITLE_THRESHOLD:
                    match = existing
                    break

        if match is not None:
            _merge(match, paper)
        else:
            merged.append(paper)

    return merged
