"""What your library is actually about, in its own words.

Every other view on the page starts from questions you supplied: relevance
is scored against them, stances are classified against them, coverage is
counted against them. That makes those views blind in one specific way — a
library can be full of a topic you never thought to ask about, and nothing
built from your questions will ever show it.

Themes are extracted from the papers instead: recurring phrases in titles
and abstracts, ranked by how many DISTINCT papers use them. Document
frequency rather than raw count is the whole point — a phrase repeated
fifteen times inside one paper is that paper's vocabulary, while a phrase
appearing once each in nine papers is a theme running through the library.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..relevance import _STOPWORDS

# Words that carry no subject matter in an academic abstract, on top of the
# general stoplist. Without these, every library's top themes are "this
# paper", "the results" and "we propose" — true of all of them, and
# therefore about none of them.
_ACADEMIC_STOPWORDS = {
    "abstract", "article", "author", "authors", "conclusion", "conclusions",
    "contribution", "contributions", "data", "discussion", "finding", "findings",
    "framework", "future", "implication", "implications", "introduction",
    "issue", "journal", "keyword", "keywords", "limitation", "limitations",
    "literature", "method", "methods", "methodology", "model", "models",
    "paper", "papers", "practice", "present", "problem", "process", "propose",
    "proposed", "purpose", "question", "questions", "result", "results",
    "section", "studies", "theory", "university", "work", "works",
    # Title/abstract scaffolding that reads like a theme but names no
    # subject: "a systematic review exploring perspectives on X".
    "systematic", "empirical", "exploring", "examining", "investigating",
    "understanding", "insights", "perspective", "perspectives", "overview",
    "agenda", "towards", "toward", "case", "cases", "evidence",
    # Quantifier/verb filler that survives the general list and pairs into
    # phrases like "significant positive" that name no subject.
    "also", "based", "both", "different", "significant", "significantly",
    "various", "well", "within", "however", "therefore", "thus", "while",
    "more", "most", "such", "than", "these", "those", "through", "used",
    "use", "uses", "new", "high", "higher", "low", "lower", "large", "small",
    "one", "two", "three", "may", "might", "must", "should", "could", "would",
    "been", "being", "have", "has", "had", "was", "were", "will", "shall",
    "not", "but", "our", "we", "they", "them", "it", "he", "she",
}

STOPWORDS = {w.lower() for w in _STOPWORDS} | _ACADEMIC_STOPWORDS

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-']*")
_MIN_WORD_CHARS = 3
# Short all-caps tokens are acronyms, not noise, and in most fields they are
# the subject itself — AI, ML, UX, OTA, GDP. A flat minimum length drops
# exactly the terms a reader would look for first.
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9]+$")

# A theme has to recur — that is what makes it a theme rather than one
# paper's phrasing.
DEFAULT_MIN_PAPERS = 2
DEFAULT_MAX_THEMES = 45


@dataclass
class Theme:
    term: str
    paper_keys: List[str] = field(default_factory=list)
    # How many of the papers using this theme speak to at least one
    # sub-question. A theme carried entirely by papers that engage nothing
    # is the interesting case: a real cluster in the library that none of
    # the questions reach.
    engaged_papers: int = 0
    # The term as the papers themselves write it — "generative AI", not
    # "generative ai". Matching is done in lowercase; a reader should not
    # have to decode the machinery.
    display: str = ""

    @property
    def label(self) -> str:
        return self.display or self.term

    @property
    def paper_count(self) -> int:
        return len(self.paper_keys)

    @property
    def engages_questions(self) -> bool:
        return self.engaged_papers > 0


def _content_runs(text: str) -> List[List[Tuple[str, str]]]:
    """Split text into runs of consecutive content words, each kept as
    (lowercase, as-written).

    Phrases are built inside a run only, so a stopword or a full stop breaks
    the chain: "impact of AI on travel planning" yields ["ai"] and
    ["travel", "planning"], never the phantom bigram "ai travel".
    """
    runs: List[List[Tuple[str, str]]] = []
    for sentence in re.split(r"[.;:!?()\[\]{}\"]+", text or ""):
        current: List[Tuple[str, str]] = []
        for raw in _WORD_RE.findall(sentence):
            word = raw.lower().strip("-'")
            too_short = len(word) < _MIN_WORD_CHARS and not _ACRONYM_RE.match(raw)
            if too_short or word in STOPWORDS or word.isdigit():
                if current:
                    runs.append(current)
                    current = []
                continue
            current.append((word, raw.strip("-'")))
        if current:
            runs.append(current)
    return runs


def _phrases(text: str) -> Tuple[Set[str], Dict[str, Counter]]:
    """The distinct phrases this one document contributes, plus how it wrote
    each word. A set of phrases, so a paper that says "generative ai" twenty
    times still counts once — document frequency is what makes a theme a
    theme."""
    found: Set[str] = set()
    surfaces: Dict[str, Counter] = {}
    for run in _content_runs(text):
        for i, (word, raw) in enumerate(run):
            found.add(word)
            surfaces.setdefault(word, Counter())[raw] += 1
            if i + 1 < len(run):
                found.add(f"{word} {run[i + 1][0]}")
    return found, surfaces


def _drop_redundant(themes: List[Theme]) -> List[Theme]:
    """Remove a single word when a phrase containing it says the same thing.

    "generative" appearing in 11 papers next to "generative ai" in 10 is one
    theme shown twice, and the longer form is the one that reads as a theme.
    The single word survives only if it is used meaningfully beyond the
    phrase — appearing in noticeably more papers than the phrase does.
    """
    phrases = [t for t in themes if " " in t.term]
    kept: List[Theme] = []
    for theme in themes:
        if " " in theme.term:
            kept.append(theme)
            continue
        covering = [
            p for p in phrases
            if theme.term in p.term.split() and p.paper_count >= theme.paper_count * 0.7
        ]
        if not covering:
            kept.append(theme)
    return kept


def _surface_form(word: str, surfaces: Dict[str, Counter]) -> str:
    """How the corpus itself writes this word. Ties go to the more capitalised
    form, so an acronym that also appears lowercased still renders as one."""
    counts = surfaces.get(word)
    if not counts:
        return word
    best = max(counts.items(), key=lambda kv: (kv[1], sum(c.isupper() for c in kv[0])))
    return best[0]


def extract_themes(
    documents: Sequence[Tuple[str, str, bool]],
    min_papers: int = DEFAULT_MIN_PAPERS,
    max_themes: int = DEFAULT_MAX_THEMES,
) -> List[Theme]:
    """Themes across a library.

    `documents` is (paper key, text, engages any sub-question) per paper. The
    caller supplies the text so this module never has to know how a paper is
    stored — titles plus abstracts in practice, deliberately not the full
    extracted text, whose reference lists and running headers would swamp
    the actual subject matter.

    Returns themes ranked by how many distinct papers use them, most first.
    """
    # Keyed by term, then by paper — so the same paper reaching a term twice
    # counts once. It does reach twice in practice: a library routinely holds
    # the same paper saved to two files, and counting both would not merely
    # double a number, it would let a phrase used by ONE paper clear the
    # "appears in at least two papers" bar and be presented as a theme.
    keys_by_term: Dict[str, Dict[str, bool]] = {}
    surfaces: Dict[str, Counter] = {}
    for key, text, engaged in documents:
        phrases, doc_surfaces = _phrases(text)
        for word, counts in doc_surfaces.items():
            surfaces.setdefault(word, Counter()).update(counts)
        for term in phrases:
            papers = keys_by_term.setdefault(term, {})
            papers[key] = papers.get(key, False) or engaged

    by_term: Dict[str, Theme] = {}
    for term, papers in keys_by_term.items():
        by_term[term] = Theme(
            term=term,
            paper_keys=list(papers),
            engaged_papers=sum(1 for engaged in papers.values() if engaged),
            display=" ".join(_surface_form(word, surfaces) for word in term.split()),
        )

    recurring = [t for t in by_term.values() if t.paper_count >= min_papers]
    # Rank by reach, then prefer the phrase over the bare word at equal
    # reach, then alphabetically so the same library always renders the same
    # cloud rather than reshuffling on every run.
    recurring.sort(key=lambda t: (-t.paper_count, -len(t.term.split()), t.term))
    return _drop_redundant(recurring)[:max_themes]


def documents_from_entries(entries: Iterable, engaged_keys: Optional[Set[str]] = None) -> List[Tuple[str, str, bool]]:
    """Adapt library index entries into extract_themes()'s input: title plus
    abstract, and whether this paper speaks to any sub-question."""
    engaged_keys = engaged_keys or set()
    # One document per PAPER, not per file. The same paper saved twice is one
    # paper; merging the two entries' text also means a copy that happens to
    # carry an abstract contributes it even if the other does not.
    merged: Dict[str, List[str]] = {}
    for entry in entries:
        paper = entry.paper
        parts = merged.setdefault(paper.key(), [])
        for part in (paper.title, paper.abstract):
            if part and part not in parts:
                parts.append(part)
    # Joined with a full stop, never a bare space: without it the last word
    # of the title and the first of the abstract read as adjacent, and the
    # cloud fills up with phrases like "planning Generative" that no paper
    # ever wrote.
    return [(key, ". ".join(parts), key in engaged_keys) for key, parts in merged.items()]
