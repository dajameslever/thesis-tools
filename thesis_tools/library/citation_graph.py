"""Citation-coverage view: of everything your indexed papers themselves
cite, how much is already in your library — and what's a recurring gap?

Requires each entry's `references` (populated by --fetch-references at
index time). Everything here is pure local computation over already-cached
data — no network calls — so it's cheap to rebuild on every report.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..relevance import tokenize
from ..sources.base import normalize_title
from .index_store import LibraryEntry

MAX_MISSING_NODES = 15
MIN_CITING_COUNT_FOR_GAP = 2  # only surface references cited by 2+ of your papers

# A missing reference is known only by its title — there is no abstract to
# score against — so relevance here is "what share of this title's meaningful
# words are words you are actually asking about". Normalising by the title
# (rather than by the question, as score_relevance does) keeps the measure
# stable as you add sub-questions: otherwise every suggestion would look less
# relevant simply because the question set grew.
DEFAULT_MIN_GAP_RELEVANCE = 0.1
_STEM_PREFIX_LEN = 5


def indexed_dois(entries: List[LibraryEntry]) -> set:
    dois = set()
    for entry in entries:
        for doi in (entry.doi, entry.paper.doi):
            if doi:
                dois.add(doi.strip().lower())
    return dois


def build_coverage(entries: List[LibraryEntry]) -> dict:
    """Returns total/included/missing reference counts, plus a "frequently
    missing" list: references cited by multiple indexed papers that aren't
    themselves in the library yet — often the foundational/older works worth
    tracking down next."""
    known_dois = indexed_dois(entries)
    gaps: Dict[str, dict] = {}
    total = included = 0

    for entry in entries:
        for ref in entry.references:
            total += 1
            doi = (ref.get("doi") or "").strip().lower()
            if doi and doi in known_dois:
                included += 1
                continue
            key = doi or (ref.get("title") or "").strip().lower()
            if not key:
                continue
            gap = gaps.setdefault(
                key, {"title": ref.get("title"), "year": ref.get("year"), "doi": ref.get("doi"), "cited_by": []}
            )
            gap["cited_by"].append(entry.paper.title)

    frequently_missing = sorted(
        (g for g in gaps.values() if len(g["cited_by"]) >= MIN_CITING_COUNT_FOR_GAP),
        key=lambda g: len(g["cited_by"]),
        reverse=True,
    )[:MAX_MISSING_NODES]

    return {
        "total_references": total,
        "included_references": included,
        "missing_references": total - included,
        "frequently_missing": frequently_missing,
    }


def _entry_node_id(entry: LibraryEntry) -> str:
    doi = (entry.doi or entry.paper.doi or "").strip().lower()
    return f"doi:{doi}" if doi else f"title:{normalize_title(entry.paper.title)}"


def _gap_node_id(gap: dict) -> str:
    doi = (gap.get("doi") or "").strip().lower()
    return f"doi:{doi}" if doi else f"title:{normalize_title(gap.get('title') or '')}"


def build_citation_network(entries: List[LibraryEntry], coverage: dict) -> dict:
    """A graph of who-cites-whom, for an interactive "citation network" view
    (as opposed to build_coverage's plain totals): every indexed paper is a
    node, plus a "gap" node for each frequently-missing reference already
    surfaced by build_coverage (same threshold — cited by 2+ of your
    papers — so this view and the Markdown report's mind-map agree). An
    edge means "source cites target": either one indexed paper citing
    another (the interesting case — reveals your own library's internal
    citation structure) or an indexed paper citing a gap.

    References cited by only one paper and not themselves indexed are
    deliberately left out — with hundreds of one-off references in a
    typical library, including every single one would make the graph
    unreadable rather than more informative.
    """
    known_dois = indexed_dois(entries)

    nodes: List[dict] = []
    node_ids: Dict[str, int] = {}

    def add_node(node: dict) -> None:
        node_ids[node["id"]] = len(nodes)
        nodes.append(node)

    for entry in entries:
        node_id = _entry_node_id(entry)
        if node_id in node_ids:
            continue  # two files resolved to the same paper (a duplicate) — one node is enough
        add_node(
            {
                "id": node_id,
                "kind": "indexed",
                "title": entry.paper.title,
                "year": entry.paper.year,
                "confidence": entry.confidence,
                "doi": entry.doi or entry.paper.doi,
                "file_path": entry.file_path,
            }
        )

    gap_ids_by_title: Dict[str, str] = {}
    for gap in coverage["frequently_missing"]:
        node_id = _gap_node_id(gap)
        if node_id in node_ids:
            continue  # already indexed under this DOI/title — not actually a gap
        gap_ids_by_title[gap["title"]] = node_id
        add_node(
            {
                "id": node_id,
                "kind": "gap",
                "title": gap["title"],
                "year": gap.get("year"),
                "confidence": None,
                "doi": gap.get("doi"),
                "cited_by_count": len(gap["cited_by"]),
            }
        )

    edges: List[dict] = []
    seen_edges = set()

    def add_edge(source: str, target: str) -> None:
        if source == target:
            return
        key = (source, target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"source": source, "target": target})

    for entry in entries:
        source = _entry_node_id(entry)
        for ref in entry.references:
            doi = (ref.get("doi") or "").strip().lower()
            if doi and doi in known_dois:
                target = f"doi:{doi}"
                if target in node_ids:
                    add_edge(source, target)
                continue
            target = gap_ids_by_title.get(ref.get("title"))
            if target:
                add_edge(source, target)

    return {"nodes": nodes, "edges": edges}


def _short_label(title: str, year, max_len: int = 40) -> str:
    title = title or "Untitled"
    year_part = f" ({year})" if year else ""
    if len(title) > max_len:
        title = title[: max_len - 1] + "…"
    # Mermaid node labels can't contain raw quotes/brackets without escaping.
    safe = title.replace('"', "'").replace("[", "(").replace("]", ")")
    return f"{safe}{year_part}"


def build_mermaid_mindmap(entries: List[LibraryEntry], coverage: dict) -> str:
    """A flowchart: your indexed papers (✅) pointing to the recurring gaps
    in what they cite (❌) — a visual "what we have vs. what we're missing"."""
    lines = ["flowchart LR"]

    paper_node_ids: Dict[str, str] = {}
    for i, entry in enumerate(entries):
        nid = f"P{i}"
        paper_node_ids[entry.paper.title] = nid
        lines.append(f'    {nid}["✅ {_short_label(entry.paper.title, entry.paper.year)}"]')

    missing_node_ids: Dict[str, str] = {}
    for j, gap in enumerate(coverage["frequently_missing"]):
        nid = f"M{j}"
        missing_node_ids[gap["title"]] = nid
        lines.append(f'    {nid}["❌ {_short_label(gap["title"], gap["year"])}"]')

    for entry in entries:
        src = paper_node_ids[entry.paper.title]
        for ref in entry.references:
            target = missing_node_ids.get(ref.get("title"))
            if target:
                lines.append(f"    {src} --> {target}")

    return "\n".join(lines)


def build_internal_links(entries: List[LibraryEntry]) -> dict:
    """Which of your own papers cite which others — the "connected articles"
    view, laid out for an arc diagram rather than a force-directed graph.

    Papers are returned in a deterministic reading order (oldest first,
    unknown year last, ties broken by title) so citations mostly arc
    right-to-left: newer work citing older. That ordering is the whole point
    of the form — a force layout has no such meaning and, past a handful of
    papers, degenerates into an unreadable hairball.

    A paper that neither cites nor is cited by anything else in the library
    is still returned (as an isolated node): "nothing else here talks to
    this" is a real finding about a library, not an absence to hide.
    """
    seen: Dict[str, LibraryEntry] = {}
    for entry in entries:
        seen.setdefault(_entry_node_id(entry), entry)

    ordered = sorted(
        seen.items(),
        # `year is None` sorts False(0) before True(1), so dated papers come
        # first and undated ones collect at the end rather than at year 0.
        key=lambda kv: (kv[1].paper.year is None, kv[1].paper.year or 0, kv[1].paper.title or ""),
    )
    index_by_id = {node_id: i for i, (node_id, _) in enumerate(ordered)}

    links: List[dict] = []
    seen_links = set()
    cites_count = [0] * len(ordered)
    cited_by_count = [0] * len(ordered)

    for node_id, entry in ordered:
        source = index_by_id[node_id]
        for ref in entry.references:
            doi = (ref.get("doi") or "").strip().lower()
            if not doi:
                continue
            target = index_by_id.get(f"doi:{doi}")
            if target is None or target == source:
                continue
            key = (source, target)
            if key in seen_links:
                continue
            seen_links.add(key)
            links.append({"source": source, "target": target})
            cites_count[source] += 1
            cited_by_count[target] += 1

    papers = [
        {
            "index": i,
            "title": entry.paper.title,
            "year": entry.paper.year,
            "doi": entry.doi or entry.paper.doi,
            "confidence": entry.confidence,
            "cites": cites_count[i],
            "cited_by": cited_by_count[i],
        }
        for i, (_, entry) in enumerate(ordered)
    ]
    connected = sum(1 for p in papers if p["cites"] or p["cited_by"])

    return {
        "papers": papers,
        "links": links,
        "connected_count": connected,
        "isolated_count": len(papers) - connected,
    }


def _stems(text: str) -> set:
    """Crude, dependency-free stemming: a long word is represented by its
    first few characters, so "sleepiness" matches "sleep" and "adolescents"
    matches "adolescent". Nowhere near a real stemmer, but the alternative —
    exact token equality — misses most of the morphological variation between
    how a question is phrased and how a paper title is."""
    stems = set()
    for token in tokenize(text):
        # A hyphenated compound is two words for matching purposes: without
        # this, "risk-taking" in a question never matches "Risk" in a title.
        for part in token.split("-"):
            if len(part) > 2:
                stems.add(part[:_STEM_PREFIX_LEN] if len(part) > _STEM_PREFIX_LEN else part)
    return stems


def question_term_weights(questions: List[str]) -> Dict[str, float]:
    """How central each term is across the question set: a word you ask about
    in three of four questions carries more weight than one that appears once.

    This is what lets a title-only match distinguish a real hit from an
    incidental one. Scoring against the questions concatenated into a single
    blob cannot: "Measuring Sleepiness" matching *sleep* and "Urban Planning
    and Commute Times" matching *times* both come out as one-word-in-four,
    even though only one of them is on-topic.
    """
    present = [q for q in questions if (q or "").strip()]
    if not present:
        return {}
    counts: Dict[str, float] = {}
    for question in present:
        for stem in _stems(question):
            counts[stem] = counts.get(stem, 0.0) + 1.0
    # Normalised against the most-repeated term, not the number of questions:
    # dividing by the question count would shrink every score as the question
    # set grew, so a fixed threshold would quietly get stricter each time a
    # sub-question was added. Against the peak, the scale stays put and the
    # weights keep saying what they should — how central a term is *relative
    # to the others you ask about*.
    peak = max(counts.values())
    return {stem: count / peak for stem, count in counts.items()}


def gap_relevance(title: str, questions: List[str]) -> float:
    """How on-topic a cited-but-missing work's title looks, in [0, 1].

    A missing reference is known only by its title — there is no abstract to
    score against — so this is "what share of this title's meaningful words
    are words you actually ask about, weighted by how central each is".
    Normalising by the title rather than by the question (as score_relevance
    does) keeps the measure stable as you add sub-questions; otherwise every
    suggestion would look less relevant simply because the question set grew.

    Returns 0.0 when there is nothing to score against, so callers can treat
    "no question configured" as "do not filter" rather than "nothing is
    relevant".
    """
    weights = question_term_weights(questions)
    title_stems = _stems(title or "")
    if not weights or not title_stems:
        return 0.0
    matched = sum(weights.get(stem, 0.0) for stem in title_stems)
    return round(matched / len(title_stems), 4)


def split_by_relevance(
    works: List[dict],
    questions: List[str],
    min_relevance: float = DEFAULT_MIN_GAP_RELEVANCE,
) -> Tuple[List[dict], List[dict]]:
    """Split cited-but-missing works into (on-topic, off-topic) against the
    questions being asked, each annotated with its score, best first.

    Suggesting whatever your papers happen to cite most is how a reading list
    fills up with well-cited work that has nothing to do with your thesis —
    methods papers, a co-author's unrelated output, a field's ambient
    classics. Deliberately a *split* rather than a drop: a title-only keyword
    match will sometimes misjudge a genuinely relevant work, so the off-topic
    side stays available rather than disappearing.

    With no question configured there is nothing to score against, so
    everything comes back on-topic and nothing is hidden.
    """
    scored = []
    for work in works:
        annotated = dict(work)
        annotated["relevance"] = gap_relevance(work.get("title") or "", questions)
        scored.append(annotated)

    def sort_key(w: dict) -> tuple:
        return (w["relevance"], len(w.get("cited_by") or []))

    if not any((q or "").strip() for q in questions):
        scored.sort(key=sort_key, reverse=True)
        return scored, []

    on_topic = sorted((w for w in scored if w["relevance"] >= min_relevance), key=sort_key, reverse=True)
    off_topic = sorted((w for w in scored if w["relevance"] < min_relevance), key=sort_key, reverse=True)
    return on_topic, off_topic


# Per paper, in the expandable tree. A single paper's reference list can run
# to a hundred entries; the point of the branch is "is there anything here
# worth chasing", not to reproduce the bibliography.
MAX_EXPLORE_PER_PAPER = 12


def build_exploration_tree(
    entries: List[LibraryEntry],
    questions: Optional[List[str]] = None,
    min_relevance: float = DEFAULT_MIN_GAP_RELEVANCE,
) -> dict:
    """Your library as an expandable route outward: for each indexed paper,
    what it cites that you already have, and — the point of the view — what
    it cites that you have *not* imported yet and might read next.

    Papers are ordered by how much unexplored on-topic work they lead to, so
    the paper that opens the most doors is the first branch, not whichever
    happened to be indexed first.
    """
    questions = [q for q in (questions or []) if (q or "").strip()]
    known_dois = indexed_dois(entries)
    title_to_entry = {normalize_title(e.paper.title): e for e in entries}

    # How many of your own papers cite each missing work — the "several of
    # your sources lean on this" signal, kept alongside per-paper relevance.
    citing_counts: Dict[str, int] = {}
    for entry in entries:
        for ref in entry.references:
            key = (ref.get("doi") or "").strip().lower() or normalize_title(ref.get("title") or "")
            if key:
                citing_counts[key] = citing_counts.get(key, 0) + 1

    papers: List[dict] = []
    distinct_to_explore: Dict[str, dict] = {}
    distinct_off_topic: Dict[str, dict] = {}

    for entry in entries:
        in_library: List[dict] = []
        candidates: List[dict] = []
        seen_keys = set()

        for ref in entry.references:
            doi = (ref.get("doi") or "").strip().lower()
            title = ref.get("title") or ""
            key = doi or normalize_title(title)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)

            if (doi and doi in known_dois) or (not doi and normalize_title(title) in title_to_entry):
                held = title_to_entry.get(normalize_title(title))
                in_library.append(
                    {"title": held.paper.title if held else title, "year": ref.get("year"), "doi": ref.get("doi")}
                )
                continue
            candidates.append(
                {
                    "title": title,
                    "year": ref.get("year"),
                    "doi": ref.get("doi"),
                    "cited_by_count": citing_counts.get(key, 1),
                    "_key": key,
                }
            )

        on_topic, off_topic = split_by_relevance(candidates, questions, min_relevance)
        for work in on_topic:
            distinct_to_explore.setdefault(work["_key"], work)
        for work in off_topic:
            distinct_off_topic.setdefault(work["_key"], work)

        papers.append(
            {
                "title": entry.paper.title,
                "year": entry.paper.year,
                "doi": entry.doi or entry.paper.doi,
                "confidence": entry.confidence,
                "in_library": sorted(in_library, key=lambda w: (w["year"] or 0, w["title"] or "")),
                "to_explore": on_topic[:MAX_EXPLORE_PER_PAPER],
                "to_explore_total": len(on_topic),
                "off_topic_count": len(off_topic),
            }
        )

    papers.sort(key=lambda p: (p["to_explore_total"], len(p["in_library"]), p["title"] or ""), reverse=True)

    return {
        "papers": papers,
        "distinct_to_explore": len(distinct_to_explore),
        "distinct_off_topic": len(distinct_off_topic),
        "questions_configured": bool(questions),
        "min_relevance": min_relevance,
    }
