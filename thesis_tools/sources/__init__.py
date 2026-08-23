from .base import Paper, SourceClient
from .semantic_scholar import SemanticScholarClient
from .openalex import OpenAlexClient
from .crossref import CrossrefClient
from .arxiv import ArxivClient

ALL_SOURCES = {
    "semanticscholar": SemanticScholarClient,
    "openalex": OpenAlexClient,
    "crossref": CrossrefClient,
    "arxiv": ArxivClient,
}

__all__ = [
    "Paper",
    "SourceClient",
    "SemanticScholarClient",
    "OpenAlexClient",
    "CrossrefClient",
    "ArxivClient",
    "ALL_SOURCES",
]
