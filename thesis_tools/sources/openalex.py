"""OpenAlex API client (free, no API key required).

Docs: https://docs.openalex.org/api-entities/works
"""

from __future__ import annotations

import sys
from typing import Dict, List, Optional

import requests

from .base import Paper, SourceClient

API_URL = "https://api.openalex.org/works"


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:
    """OpenAlex stores abstracts as {word: [positions]} to dodge copyright issues.

    Rebuild the plain-text abstract from that inverted index.
    """
    if not inverted_index:
        return None
    positions: Dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    if not positions:
        return None
    ordered = [positions[i] for i in sorted(positions)]
    return " ".join(ordered)


class OpenAlexClient(SourceClient):
    name = "openalex"

    def __init__(self, timeout: int = 15, mailto: Optional[str] = None):
        self.timeout = timeout
        # OpenAlex asks for a contact email via `mailto` to use their "polite pool"
        # (faster, more reliable rate limits). Optional — works fine without it.
        self.mailto = mailto

    def search(self, query: str, limit: int = 15) -> List[Paper]:
        params = {"search": query, "per-page": limit}
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            resp = requests.get(API_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            # A 200 with an empty/"null" body parses to None, not {} — guard
            # against that rather than blowing up on .get() below.
            data = resp.json() or {}
        except Exception as exc:
            print(f"  [openalex] skipped ({exc})", file=sys.stderr)
            return []

        papers = []
        # `.get("results", [])` only falls back when the key is *missing* —
        # guard the "key present but null" case too.
        for item in data.get("results") or []:
            authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in (item.get("authorships") or [])
            ]
            authors = [a for a in authors if a]
            primary_location = item.get("primary_location") or {}
            source = primary_location.get("source") or {}
            doi = item.get("doi")
            if doi:
                doi = doi.replace("https://doi.org/", "")
            biblio = item.get("biblio") or {}
            best_oa_location = item.get("best_oa_location") or {}
            open_access = item.get("open_access") or {}
            pdf_url = best_oa_location.get("pdf_url") or open_access.get("oa_url")
            papers.append(
                Paper(
                    title=item.get("display_name") or item.get("title") or "",
                    authors=authors,
                    year=item.get("publication_year"),
                    venue=source.get("display_name"),
                    abstract=reconstruct_abstract(item.get("abstract_inverted_index")),
                    doi=doi,
                    url=item.get("id"),
                    volume=biblio.get("volume"),
                    issue=biblio.get("issue"),
                    pages=_pages(biblio),
                    citation_count=item.get("cited_by_count"),
                    pdf_url=pdf_url,
                    sources=["openalex"],
                )
            )
        return papers


def _pages(biblio: Dict) -> Optional[str]:
    first, last = biblio.get("first_page"), biblio.get("last_page")
    if first and last:
        return f"{first}-{last}"
    return first or last
