"""Break a thesis topic into 3-4 sub-questions, then work out how each found
paper relates to each one: does it support the underlying assumption,
challenge it, or say nothing useful either way? Finally, flag sub-questions
where the literature itself disagrees — since that's often exactly the gap
a thesis can sit in.

Two tiers, same as summarize.py:
  * heuristic (default, no API key): a small support/challenge lexicon
    scanned against each paper's abstract, gated by topical overlap with
    the sub-question so an unrelated paper isn't scored at all.
  * LLM (optional, reuses the same Claude access as --llm-summaries): one
    call per paper classifies it against every sub-question at once, for
    a far more reliable read than the lexicon can manage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import llm
from .relevance import tokenize
from .sources.base import Paper

STANCES = ("supports", "challenges", "mixed", "unrelated")

_SUPPORT_CUES = [
    "supports", "support for", "consistent with", "confirms", "confirming",
    "in line with", "corroborates", "replicates", "replicated", "significant effect",
    "significantly associated", "strong evidence for", "consistent evidence",
]
_CHALLENGE_CUES = [
    "contrary to", "in contrast", "no significant", "did not support", "does not support",
    "failed to replicate", "inconsistent with", "contradicts", "no evidence",
    "null result", "challenges the assumption", "unlike prior work", "fails to confirm",
    "not associated", "no effect of",
]

_OVERLAP_THRESHOLD = 0.15  # minimum keyword overlap with the sub-question to even attempt a stance

# Phrases immediately before a support cue that flip its meaning, e.g. "no
# significant effect" — without this, that phrase would count as *both* a
# challenge cue ("no significant") and a support cue ("significant effect").
_NEGATION_WORDS = ["no ", "not ", "non-", "non ", "n't ", "without ", "lack of ", "lacking ", "fails to ", "failed to "]
_NEGATION_WINDOW = 20


def _cue_present(text: str, cues: List[str]) -> bool:
    """True if any cue appears in `text` without being immediately negated."""
    for cue in cues:
        start = 0
        while True:
            idx = text.find(cue, start)
            if idx == -1:
                break
            window = text[max(0, idx - _NEGATION_WINDOW) : idx]
            if not any(neg in window for neg in _NEGATION_WORDS):
                return True
            start = idx + 1
    return False


@dataclass
class StanceResult:
    stance: str  # one of STANCES
    rationale: str = ""


@dataclass
class SubquestionAnalysis:
    sub_questions: List[str]
    # paper key (Paper.key(), prefers DOI so identical titles never collide) ->
    # {sub_question -> StanceResult}
    stances: Dict[str, Dict[str, StanceResult]] = field(default_factory=dict)
    # paper key -> display title, so callers/tensions() can report on papers by name
    paper_titles: Dict[str, str] = field(default_factory=dict)

    def stances_for(self, paper: Paper) -> Dict[str, StanceResult]:
        return self.stances.get(paper.key(), {})

    def titles_by_stance(self, question: str) -> Dict[str, List[str]]:
        """For one sub-question, group the papers that took a stance on it.
        Returns {"supports": [titles], "challenges": [titles], "mixed": [titles]}
        (omitting "unrelated" — that's the default for everything else)."""
        grouped: Dict[str, List[str]] = {"supports": [], "challenges": [], "mixed": []}
        for key, stances in self.stances.items():
            stance = stances.get(question)
            if stance and stance.stance in grouped:
                grouped[stance.stance].append(self.paper_titles[key])
        return grouped

    def grouped_papers(self, question: str, papers: List[Paper]) -> Dict[str, List[Paper]]:
        """Like titles_by_stance, but returns the actual Paper objects (keyed
        safely by Paper.key(), so identical titles never collide) — used by
        Part 3 to pull abstracts/authors/years for synthesis, not just names."""
        by_key = {p.key(): p for p in papers}
        grouped: Dict[str, List[Paper]] = {"supports": [], "challenges": [], "mixed": []}
        for key, stances in self.stances.items():
            stance = stances.get(question)
            paper = by_key.get(key)
            if stance and paper and stance.stance in grouped:
                grouped[stance.stance].append(paper)
        return grouped

    def tensions(self) -> Dict[str, Dict[str, List[str]]]:
        """Sub-questions where at least one paper supports and at least one
        challenges — i.e. the literature disagrees with itself. Returns
        {sub_question: {"supports": [paper titles], "challenges": [paper titles]}}.
        """
        result: Dict[str, Dict[str, List[str]]] = {}
        for question in self.sub_questions:
            grouped = self.titles_by_stance(question)
            if grouped["supports"] and grouped["challenges"]:
                result[question] = {"supports": grouped["supports"], "challenges": grouped["challenges"]}
        return result


_SUBQUESTION_SYSTEM_PROMPT = (
    "You help a student scope a thesis. Given their working title and/or research "
    "question, produce exactly 3 or 4 sharper sub-questions that break the topic into "
    "testable parts. One per line, no numbering, no preamble, no explanation — just the "
    "questions themselves."
)


def generate_subquestions(topic_text: str, model: str = "claude-sonnet-5") -> List[str]:
    """Ask Claude for 3-4 sub-questions. Returns [] if the LLM is unavailable
    or the request fails — callers should treat that as "skip this section",
    not as an error, and the CLI lets the user supply their own instead."""
    client = llm.get_client()
    if client is None:
        return []
    response = llm.ask(client, _SUBQUESTION_SYSTEM_PROMPT, topic_text, model=model, max_tokens=300)
    if not response:
        return []
    questions = [line.strip(" -\t") for line in response.splitlines() if line.strip()]
    return questions[:4]


def _heuristic_stance(abstract: Optional[str], sub_question: str) -> StanceResult:
    if not abstract:
        return StanceResult("unrelated")

    overlap_terms = set(tokenize(sub_question))
    abstract_terms = set(tokenize(abstract))
    if not overlap_terms or not abstract_terms:
        return StanceResult("unrelated")
    overlap = len(overlap_terms & abstract_terms) / len(overlap_terms)
    if overlap < _OVERLAP_THRESHOLD:
        return StanceResult("unrelated")

    text = abstract.lower()
    has_support = _cue_present(text, _SUPPORT_CUES)
    has_challenge = any(cue in text for cue in _CHALLENGE_CUES)

    if has_support and has_challenge:
        return StanceResult("mixed", "Abstract contains both supporting and contradicting language (heuristic, unverified).")
    if has_support:
        return StanceResult("supports", "Abstract language suggests this supports the sub-question (heuristic, unverified).")
    if has_challenge:
        return StanceResult("challenges", "Abstract language suggests this challenges the sub-question (heuristic, unverified).")
    return StanceResult("unrelated")


_STANCE_LINE_RE = re.compile(r"^\s*(\d+)\s*[:.\-)]\s*(supports|challenges|mixed|unrelated)\s*[-:]?\s*(.*)$", re.I)

_STANCE_SYSTEM_PROMPT = (
    "You assess how a paper's abstract relates to a list of numbered sub-questions from a "
    "student's thesis. For EACH sub-question, reply on its own line as:\n"
    "<number>: <supports|challenges|mixed|unrelated> - <one short reason>\n"
    "\"unrelated\" means the abstract doesn't actually address that sub-question. Be strict: "
    "only say supports/challenges when the abstract's findings genuinely bear on the question."
)


def _llm_stance_for_paper(client, paper: Paper, sub_questions: List[str], model: str) -> Optional[Dict[str, StanceResult]]:
    if not paper.abstract:
        return None
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(sub_questions, start=1))
    user_message = f"Sub-questions:\n{numbered}\n\nPaper title: {paper.title}\nAbstract: {paper.abstract}"
    response = llm.ask(client, _STANCE_SYSTEM_PROMPT, user_message, model=model, max_tokens=400)
    if not response:
        return None

    results: Dict[str, StanceResult] = {}
    for line in response.splitlines():
        match = _STANCE_LINE_RE.match(line)
        if not match:
            continue
        index, stance, rationale = match.groups()
        idx = int(index) - 1
        if 0 <= idx < len(sub_questions):
            results[sub_questions[idx]] = StanceResult(stance.lower(), rationale.strip())
    return results or None


def analyze_subquestions(
    sub_questions: List[str],
    papers: List[Paper],
    use_llm: bool = False,
    model: str = "claude-sonnet-5",
) -> SubquestionAnalysis:
    analysis = SubquestionAnalysis(sub_questions=list(sub_questions))
    if not sub_questions:
        return analysis

    client = llm.get_client(quiet=True) if use_llm else None

    for paper in papers:
        stances: Optional[Dict[str, StanceResult]] = None
        if client is not None:
            stances = _llm_stance_for_paper(client, paper, sub_questions, model)
        if stances is None:
            stances = {q: _heuristic_stance(paper.abstract, q) for q in sub_questions}
        key = paper.key()
        analysis.stances[key] = stances
        analysis.paper_titles[key] = paper.title

    return analysis
