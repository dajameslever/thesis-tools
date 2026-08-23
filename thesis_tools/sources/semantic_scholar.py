"""Semantic Scholar Graph API client (no API key required for light use).

Docs: https://api.semanticscholar.org/api-docs/graph

The unauthenticated tier shares a strict, global rate limit across everyone
using it without an API key, so a 429 here is routine, not exceptional —
worth one or two short retries before giving up on this source for the run.
"""

from __future__ import annotations

import sys
import time
from typing import List, Optional

import requests

from .base import Paper, SourceClient

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
LOOKUP_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
REFERENCES_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/references"
FIELDS = "title,abstract,year,authors,venue,externalIds,url,citationCount,openAccessPdf"

MAX_RETRIES = 2
BASE_BACKOFF_SECONDS = 1.5
MAX_BACKOFF_SECONDS = 10.0


def _get_with_retry(url: str, params: dict, timeout: int) -> requests.Response:
    """GET with a couple of short, bounded retries on 429 — respecting the
    server's Retry-After header when it sends one, otherwise a small
    increasing backoff. Any other status/exception is left for the caller
    to handle (e.g. via raise_for_status())."""
    resp = requests.get(url, params=params, timeout=timeout)
    attempt = 0
    while resp.status_code == 429 and attempt < MAX_RETRIES:
        retry_after = resp.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else BASE_BACKOFF_SECONDS * (attempt + 1)
        except ValueError:
            delay = BASE_BACKOFF_SECONDS * (attempt + 1)
        time.sleep(min(delay, MAX_BACKOFF_SECONDS))
        attempt += 1
        resp = requests.get(url, params=params, timeout=timeout)
    return resp


def _parse_item(item: dict) -> Optional[Paper]:
    if not item or not item.get("title"):
        return None
    authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
    external_ids = item.get("externalIds") or {}
    open_access_pdf = item.get("openAccessPdf") or {}
    return Paper(
        title=item.get("title") or "",
        authors=authors,
        year=item.get("year"),
        venue=item.get("venue") or None,
        abstract=item.get("abstract") or None,
        doi=external_ids.get("DOI"),
        url=item.get("url"),
        citation_count=item.get("citationCount"),
        pdf_url=open_access_pdf.get("url") or None,
        sources=["semanticscholar"],
    )


class SemanticScholarClient(SourceClient):
    name = "semanticscholar"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search(self, query: str, limit: int = 15) -> List[Paper]:
        try:
            resp = _get_with_retry(
                SEARCH_URL,
                {"query": query, "limit": limit, "fields": FIELDS},
                self.timeout,
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
            resp = _get_with_retry(LOOKUP_URL.format(doi=doi), {"fields": FIELDS}, self.timeout)
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
            resp = _get_with_retry(REFERENCES_URL.format(doi=doi), {"fields": FIELDS, "limit": limit}, self.timeout)
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
