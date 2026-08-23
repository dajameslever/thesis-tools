"""Relevance scoring: how related is a found paper to the user's proposed topic,
and — separately — how *dangerously close* is it to being the same question.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List

from .sources.base import Paper

_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "and", "or", "to", "with", "using",
    "is", "are", "how", "what", "why", "does", "do", "can", "study", "analysis",
    "impact", "effect", "effects", "role", "between", "among", "into", "from",
    "this", "that", "based", "approach", "towards", "toward", "via", "as", "at",
    "by", "an", "its", "their", "case", "review", "research",
}

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]+")


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _STOPWORDS and len(w) > 2]


def keywords_from_text(text: str, max_keywords: int = 12) -> List[str]:
    """Pull a simple ranked keyword list out of a title/question, for building
    search queries against the literature APIs."""
    tokens = tokenize(text)
    seen: List[str] = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
    return seen[:max_keywords]


def score_relevance(query_text: str, paper: Paper) -> float:
    """Bag-of-words overlap score in [0, 1], weighting the paper's title higher
    than its body text. Deliberately simple/deterministic — no ML dependency —
    good enough to *rank* candidates, not meant as a precise similarity metric.
    """
    query_terms = set(tokenize(query_text))
    if not query_terms:
        return 0.0

    title_terms = set(tokenize(paper.title))
    # Not every paper has an abstract — PDFs indexed locally by Part 2 usually
    # don't (extraction grabs raw page text, not a parsed abstract field), even
    # though they often do have real body text. Fall back to that extracted
    # excerpt so those papers aren't scored on title overlap alone and don't
    # get silently filtered out by --min-relevance.
    body_text = paper.abstract or paper.full_text_excerpt or ""
    body_terms = set(tokenize(body_text))

    title_overlap = len(query_terms & title_terms) / len(query_terms)
    body_overlap = len(query_terms & body_terms) / len(query_terms) if body_terms else 0.0

    score = 0.7 * title_overlap + 0.3 * body_overlap
    return round(min(score, 1.0), 4)


def title_similarity(a: str, b: str) -> float:
    """Rough string similarity between two titles, used to flag when a found
    paper may be asking almost exactly the same question as the proposed one."""
    return round(SequenceMatcher(None, (a or "").lower().strip(), (b or "").lower().strip()).ratio(), 4)


def overlap_flag(similarity: float) -> str:
    """Classify a title-similarity score into a human-readable novelty flag."""
    if similarity >= 0.85:
        return "critical"
    if similarity >= 0.65:
        return "high"
    if similarity >= 0.40:
        return "related"
    return "low"


OVERLAP_LABELS = {
    "critical": "⚠️ Near-identical — this looks like the same question, already answered",
    "high": "🟠 High overlap — read closely and differentiate your angle",
    "related": "🟡 Related — useful background/context",
    "low": "⚪ Low overlap",
}
