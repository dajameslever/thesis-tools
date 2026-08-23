"""Summarizing a paper's abstract into 1-2 sentences relevant to the user's topic.

Two modes:
  * extractive (default, no API key, no extra dependency): picks the
    sentence(s) from the abstract with the most keyword overlap with the
    user's proposed topic.
  * llm (optional, `--llm-summaries`): asks Claude to write a short, topic-
    aware summary. Requires `pip install anthropic` and an ANTHROPIC_API_KEY
    environment variable. Falls back to extractive if either is missing.
"""

from __future__ import annotations

import re
from typing import List, Optional

from . import llm
from .relevance import tokenize  # reuse the same simple tokenizer

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def extractive_summary(abstract: Optional[str], query_text: str, max_sentences: int = 2) -> Optional[str]:
    sentences = _split_sentences(abstract or "")
    if not sentences:
        return None
    if len(sentences) <= max_sentences:
        return " ".join(sentences)

    query_terms = set(tokenize(query_text))
    scored = []
    for i, sent in enumerate(sentences):
        overlap = len(query_terms & set(tokenize(sent)))
        # Slight bias toward earlier sentences (often the "what this paper does" line).
        scored.append((overlap - i * 0.01, i, sent))
    scored.sort(reverse=True)
    top = sorted(scored[:max_sentences], key=lambda x: x[1])  # restore original order
    return " ".join(s for _, _, s in top)


_LLM_SYSTEM_PROMPT = (
    "You summarize academic abstracts for a student who is scoping a thesis topic. "
    "In 1-2 plain sentences, say what the paper actually did/found and how it relates "
    "to the student's proposed topic. Be concrete, no filler, no restating the question."
)


def llm_summary(abstract: Optional[str], title: str, query_text: str, model: str = "claude-sonnet-5") -> Optional[str]:
    if not abstract:
        return None
    client = llm.get_client()
    if client is None:
        return None
    user_message = f"Student's proposed thesis topic: {query_text}\n\nPaper title: {title}\nAbstract: {abstract}"
    return llm.ask(client, _LLM_SYSTEM_PROMPT, user_message, model=model, max_tokens=150)


def summarize(abstract: Optional[str], title: str, query_text: str, use_llm: bool = False, model: str = "claude-sonnet-5") -> Optional[str]:
    if not abstract:
        return None
    if use_llm:
        result = llm_summary(abstract, title, query_text, model=model)
        if result:
            return result
    return extractive_summary(abstract, query_text)
