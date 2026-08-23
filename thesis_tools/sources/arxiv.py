"""arXiv API client (free, no API key required, Atom XML response).

Docs: https://info.arxiv.org/help/api/user-manual.html
Most useful for CS / physics / math / stats topics; returns nothing (which
is fine, and handled gracefully) for fields arXiv doesn't cover.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from typing import List

import requests

from .base import Paper, SourceClient

API_URL = "http://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ArxivClient(SourceClient):
    name = "arxiv"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search(self, query: str, limit: int = 15) -> List[Paper]:
        params = {
            "search_query": f"all:{query}",
            "max_results": limit,
        }
        try:
            resp = requests.get(API_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            print(f"  [arxiv] skipped ({exc})", file=sys.stderr)
            return []

        papers = []
        for entry in root.findall(f"{_ATOM_NS}entry"):
            title_el = entry.find(f"{_ATOM_NS}title")
            summary_el = entry.find(f"{_ATOM_NS}summary")
            published_el = entry.find(f"{_ATOM_NS}published")
            id_el = entry.find(f"{_ATOM_NS}id")
            authors = [
                (a.findtext(f"{_ATOM_NS}name") or "").strip()
                for a in entry.findall(f"{_ATOM_NS}author")
            ]
            authors = [a for a in authors if a]
            year = None
            if published_el is not None and published_el.text:
                year = int(published_el.text[:4])
            papers.append(
                Paper(
                    title=_clean(title_el.text if title_el is not None else ""),
                    authors=authors,
                    year=year,
                    venue="arXiv preprint",
                    abstract=_clean(summary_el.text if summary_el is not None else None),
                    doi=None,
                    url=id_el.text.strip() if id_el is not None and id_el.text else None,
                    sources=["arxiv"],
                )
            )
        return papers


def _clean(text):
    if text is None:
        return None
    return " ".join(text.split())
