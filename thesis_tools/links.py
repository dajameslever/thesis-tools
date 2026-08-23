"""Deep-search links for manual verification.

These are plain URL templates — not API calls — which is exactly why they
work for ScienceDirect and Google Scholar even though neither can be
queried programmatically (see the README's coverage note). When our own
resolution fails, handing the user a pre-filled search link is the honest
middle ground between "we found nothing" and pretending we checked.
"""

from __future__ import annotations

from urllib.parse import quote_plus


def google_scholar_search_url(query: str) -> str:
    return f"https://scholar.google.com/scholar?q={quote_plus(query)}"


def sciencedirect_search_url(query: str) -> str:
    return f"https://www.sciencedirect.com/search?qs={quote_plus(query)}"


def doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}"
