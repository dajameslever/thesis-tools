"""Persistent cache for `subquestions.analyze_subquestions()`'s Claude-
powered stance classification, keyed per paper — so re-running
`visualize-library --llm-summaries` on an unchanged library and unchanged
sub-questions never pays for another round of Claude calls, restoring the
"cheap to regenerate any time" promise visualize.py's own docstring makes.

A cached per-paper result is reused only while BOTH of these still hold:
  * the paper's own text is unchanged — tracked via a hash of whichever
    text `analyze_subquestions()` actually classified (abstract, or the
    extracted full-text excerpt), not the paper's title/DOI. Re-indexing a
    file with a fuller extraction, or a paper's abstract becoming available,
    naturally invalidates just that paper's cached entry.
  * the configured sub-questions are unchanged — a single Claude call
    classifies a paper against every sub-question at once (see
    subquestions._llm_stance_for_paper), so a change to the question set
    means the whole per-paper result needs a fresh call, not a partial
    patch. Every entry shares one questions_hash, so changing your
    sub-questions invalidates the whole cache in one go, not paper by
    paper.

A plain JSON file, same rationale as library/index_store.py: small,
human-readable, diffable, no extra dependency.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

CACHE_VERSION = 1


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def questions_hash(sub_questions: List[str]) -> str:
    # \x1f (unit separator) as a joiner rather than e.g. "\n" — sub-questions
    # are free text and could plausibly contain a newline themselves.
    return text_hash("\x1f".join(sub_questions))


class StanceCache:
    def __init__(self, entries: Optional[Dict[str, dict]] = None):
        self.entries: Dict[str, dict] = dict(entries) if entries else {}

    @classmethod
    def load(cls, path: Path) -> "StanceCache":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(data.get("entries", {}))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CACHE_VERSION, "entries": self.entries}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, paper_key: str, paper_text_hash: str, q_hash: str) -> Optional[dict]:
        """The cached {question: {"stance", "rationale"}} dict for this
        paper, or None if there's no entry or it's stale against either
        hash."""
        entry = self.entries.get(paper_key)
        if not entry:
            return None
        if entry.get("text_hash") != paper_text_hash or entry.get("questions_hash") != q_hash:
            return None
        return entry.get("stances")

    def put(self, paper_key: str, paper_text_hash: str, q_hash: str, stances: Dict[str, dict]) -> None:
        self.entries[paper_key] = {
            "text_hash": paper_text_hash,
            "questions_hash": q_hash,
            "stances": stances,
        }
