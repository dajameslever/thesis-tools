"""Semantic Scholar Graph API client (no API key required for light use).

Docs: https://api.semanticscholar.org/api-docs/graph
"""

from __future__ import annotations

import sys
from typing import List

import requests

from .base import Paper, SourceClient

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,authors,venue,externalIds,url,citationCount"


class SemanticScholarClient(SourceClient):
    name = "semanticscholar"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search(self, query: str, limit: int = 15) -> List[Paper]:
        try:
            resp = requests.get(
                API_URL,
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
            authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
            external_ids = item.get("externalIds") or {}
            papers.append(
                Paper(
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
            )
        return papers
