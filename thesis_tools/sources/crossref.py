"""Crossref REST API client (free, no API key required).

Docs: https://api.crossref.org/swagger-ui/index.html
Crossref indexes metadata for the vast majority of published journal
articles, which makes it the best source here for catching an *exact*
title collision even when the paper is paywalled on the publisher's site
(e.g. ScienceDirect / Elsevier).
"""

from __future__ import annotations

import re
import sys
from typing import List, Optional

import requests

from .base import Paper, SourceClient

API_URL = "https://api.crossref.org/works"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_jats(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return _TAG_RE.sub("", text).strip() or None


class CrossrefClient(SourceClient):
    name = "crossref"

    def __init__(self, timeout: int = 15, mailto: Optional[str] = None):
        self.timeout = timeout
        self.mailto = mailto

    def search(self, query: str, limit: int = 15) -> List[Paper]:
        params = {"query.bibliographic": query, "rows": limit}
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            resp = requests.get(API_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"  [crossref] skipped ({exc})", file=sys.stderr)
            return []

        papers = []
        for item in data.get("message", {}).get("items", []):
            titles = item.get("title") or []
            if not titles:
                continue
            authors = []
            for a in item.get("author") or []:
                name = " ".join(p for p in [a.get("given"), a.get("family")] if p)
                if name:
                    authors.append(name)
            year = None
            date_parts = (
                (item.get("published") or item.get("published-print") or item.get("published-online") or {})
                .get("date-parts")
            )
            if date_parts and date_parts[0]:
                year = date_parts[0][0]
            container = item.get("container-title") or []
            papers.append(
                Paper(
                    title=titles[0],
                    authors=authors,
                    year=year,
                    venue=container[0] if container else None,
                    abstract=_strip_jats(item.get("abstract")),
                    doi=item.get("DOI"),
                    url=item.get("URL"),
                    volume=item.get("volume"),
                    issue=item.get("issue"),
                    pages=item.get("page"),
                    citation_count=item.get("is-referenced-by-count"),
                    sources=["crossref"],
                )
            )
        return papers
