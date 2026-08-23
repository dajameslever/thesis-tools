"""Semantic Scholar Graph API client (no API key required for light use).

Docs: https://api.semanticscholar.org/api-docs/graph
"""

from __future__ import annotations

import sys
from typing import List, Optional

import requests

from .base import Paper, SourceClient

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
LOOKUP_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
REFERENCES_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/references"
FIELDS = "title,abstract,year,authors,venue,externalIds,url,citationCount"


def _parse_item(item: dict) -> Optional[Paper]:
    if not item or not item.get("title"):
        return None
    authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
    external_ids = item.get("externalIds") or {}
    return Paper(
        title=item.get("title") or "",
        authors=authors,
        year=item.get("year"),
        venue=item.get("venue") or None,
        abstract=item.get("abstract") or None,
        doi=external_ids.get("DOI"),
        url=item.get("url"),
        citation_count=item.get("citationCount"),
        sources=["semanticscholar"],
    )


class SemanticScholarClient(SourceClient):
    name = "semanticscholar"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search(self, query: str, limit: int = 15) -> List[Paper]:
        try:
            resp = requests.get(
                SEARCH_URL,
                params={"query": query, "limit": limit, "fields": FIELDS},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # network error, timeout, bad JSON, 4xx/5xx
            print(f"  [semanticscholar] skipped ({exc})", file=sys.stderr)
            return []

        papers = []
        for item in data.get("data", []):
            paper = _parse_item(item)
            if paper is not None:
                papers.append(paper)
        return papers

    def lookup_doi(self, doi: str) -> Optional[Paper]:
        """Fetch a single paper by DOI. Returns None if not found or on error."""
        try:
            resp = requests.get(
                LOOKUP_URL.format(doi=doi),
                params={"fields": FIELDS},
                timeout=self.timeout,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            item = resp.json()
        except Exception as exc:
            print(f"  [semanticscholar] DOI lookup failed for {doi} ({exc})", file=sys.stderr)
            return None
        return _parse_item(item)

    def lookup_references(self, doi: str, limit: int = 50) -> List[Paper]:
        """The papers `doi` itself cites — used for Part 2's citation-coverage
        view (which of a paper's own references are already in your library).
        Returns [] on any error rather than raising, same as search()."""
        try:
            resp = requests.get(
                REFERENCES_URL.format(doi=doi),
                params={"fields": FIELDS, "limit": limit},
                timeout=self.timeout,
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"  [semanticscholar] reference lookup failed for {doi} ({exc})", file=sys.stderr)
            return []

        papers = []
        for item in data.get("data", []):
            paper = _parse_item(item.get("citedPaper") or {})
            if paper is not None:
                papers.append(paper)
        return papers
