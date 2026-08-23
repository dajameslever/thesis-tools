"""Shared data model and base class for literature-search source clients."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Paper:
    """A normalized record for a paper, regardless of which API it came from."""

    title: str
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    citation_count: Optional[int] = None
    sources: List[str] = field(default_factory=list)
    # Verbatim text extracted from the actual downloaded file (Part 2 only —
    # Part 1's search APIs never hand us more than an abstract). When
    # present, page markers ("[Page N]") may appear in the text where known,
    # so a direct quote can be cited with a real page number. Used by Part 3
    # to ground direct quotations in text we've actually seen, rather than
    # letting an LLM improvise a plausible-sounding one from the abstract.
    full_text_excerpt: Optional[str] = None
    # A direct, legitimate open-access PDF link (arXiv's own PDF endpoint,
    # Semantic Scholar's openAccessPdf, OpenAlex's best_oa_location), when the
    # source API says one exists. None means "no known open-access copy" —
    # never a paywall/publisher link to bypass.
    pdf_url: Optional[str] = None

    def key(self) -> str:
        """A best-effort stable identifier, preferring DOI."""
        if self.doi:
            return f"doi:{self.doi.strip().lower()}"
        return f"title:{normalize_title(self.title)}"


def normalize_title(title: str) -> str:
    return "".join(ch.lower() for ch in (title or "") if ch.isalnum() or ch.isspace()).strip()


def slug_for_paper(paper: Paper) -> str:
    """A filesystem-safe slug for a paper — shared so a given paper gets the
    same filename whether it lands in `processed/` via Part 1's
    --download-papers or Part 2's index-library, rather than each picking
    its own scheme."""
    base = re.sub(r"[^\w\s-]", "", paper.title or "untitled").strip().lower()
    base = re.sub(r"[-\s]+", "-", base)[:80] or "untitled"
    return f"{base}-{paper.year}" if paper.year else base


class SourceClient:
    """Base interface every literature source adapter implements.

    Subclasses must not raise on network/parsing errors from `search()` —
    they should catch them and return an empty list, printing a short
    warning instead. One flaky API should never take down the whole report.
    """

    name = "base"

    def search(self, query: str, limit: int = 15) -> List[Paper]:
        raise NotImplementedError
