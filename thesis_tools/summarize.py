"""Summarizing a paper's abstract into 1-2 sentences relevant to the user's topic.

Two modes:
  * extractive (default, no API key, no extra dependency): picks the
    sentence(s) from the abstract with the most keyword overlap with the
    user's proposed topic.
  * llm (optional, `--llm-summaries`): asks Claude to write a short, topic-
    aware summary. Requires an ANTHROPIC_API_KEY environment variable (the
    `anthropic` package itself is a core dependency). Falls back to
    extractive if the key is missing.
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


def extractive_summary(text: Optional[str], query_text: str, max_sentences: int = 2) -> Optional[str]:
    sentences = _split_sentences(text or "")
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
    "In 1-2 sentences, say what the paper actually did/found and how it relates "
    "to the student's proposed topic. Be concrete, no filler, no restating the question.\n\n"
    + llm.ACADEMIC_STYLE_NOTE
)


# A much longer full-text excerpt (extract.py keeps the whole document now)
# is too much to put in every summary prompt — bound what actually goes in
# independently of that extraction limit.
MAX_TEXT_CHARS_FOR_SUMMARY_PROMPT = 6000


def llm_summary(text: Optional[str], title: str, query_text: str, model: str = llm.DEFAULT_EXTRACTION_MODEL, is_abstract: bool = True) -> Optional[str]:
    if not text:
        return None
    # quiet=True: this runs once per paper, so the caller checks
    # llm.availability_issue() up front and prints one notice instead of
    # this repeating the same warning for every paper.
    client = llm.get_client(quiet=True)
    if client is None:
        return None
    label = "Abstract" if is_abstract else "Excerpt from the original document"
    user_message = (
        f"Student's proposed thesis topic: {query_text}\n\nPaper title: {title}\n"
        f"{label}: {text[:MAX_TEXT_CHARS_FOR_SUMMARY_PROMPT]}"
    )
    return llm.ask(client, _LLM_SYSTEM_PROMPT, user_message, model=model, max_tokens=150)


def summarize(
    abstract: Optional[str],
    title: str,
    query_text: str,
    use_llm: bool = False,
    model: str = llm.DEFAULT_EXTRACTION_MODEL,
    full_text_excerpt: Optional[str] = None,
) -> Optional[str]:
    # Most locally-indexed PDFs have no machine-readable abstract field at
    # all (extraction grabs raw page text, not a parsed abstract) — fall
    # back to the extracted text rather than silently producing no summary
    # for every such paper.
    text = abstract or full_text_excerpt
    if not text:
        return None
    if use_llm:
        result = llm_summary(text, title, query_text, model=model, is_abstract=bool(abstract))
        if result:
            return result
    return extractive_summary(text, query_text)
