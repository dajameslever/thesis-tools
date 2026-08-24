"""Part 3: draft a literature review structured around your sub-questions,
synthesizing whatever papers Part 1 (topic search) and/or Part 2 (your local
library) have already found — no new searching happens here.

Grounded generation only: every claim the LLM path writes must trace back to
an abstract already on hand. Two tiers, same pattern as the rest of the
toolkit:
  * LLM (recommended, needs ANTHROPIC_API_KEY): Claude writes real synthesis
    paragraphs per sub-question with in-text (Author, Year) citations.
  * heuristic fallback: a structured bullet outline grouped by stance — not
    prose, but still a legitimate starting skeleton with zero API calls.

Treat the output as a strong first draft to rewrite in your own voice and
verify against the actual papers — not a citable final product.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import llm
from .citations import STYLES, format_citation, in_text_citation
from .dedupe import dedupe_papers
from .relevance import score_relevance, tokenize
from .sources.base import Paper
from .review_html import render_review_html
from .subquestions import SubquestionAnalysis, analyze_subquestions

DISCLAIMER = (
    "> ⚠️ **This is an AI-assisted DRAFT.** Claims about papers Part 2 indexed locally draw on "
    "the real extracted document text (with page numbers where known) — claims about papers "
    "found only via Part 1's search APIs draw on the abstract only, since that's all those "
    "sources ever provide. Either way: automated text extraction can introduce artifacts (broken "
    "hyphenation, dropped characters, OCR noise), so check any direct quotation against the "
    "actual PDF before using it. Verify every claim, rewrite this in your own voice, and treat it "
    "as a structured starting point, not a citable final draft."
)


# A section of 1000-2000 words needs real material behind it; six papers is
# an outline's worth, not a literature review's.
MAX_PAPERS_PER_SYNTHESIS_CALL = 14

# Target length for each sub-question's section. A literature review chapter
# runs to roughly this per question — the previous 150-250 words produced a
# paragraph, not a section.
DEFAULT_WORDS_PER_QUESTION = 1200

# Total characters of paper text allowed into one synthesis prompt. Nothing
# is trimmed while the papers fit inside this, which is the normal case —
# but a dozen full papers can run past any model's context window, and the
# failure mode there is the whole call erroring out and the section
# collapsing to a bullet list. Budgeting keeps the call alive, and the draft
# says when trimming happened rather than hiding it.
MAX_PROMPT_TEXT_CHARS = 300_000



@dataclass
class LiteratureReviewInputs:
    field: str
    working_title: str
    research_question: Optional[str]
    sub_questions: List[str]
    paper_sources: List[str]  # paths to Part 1 <report>.papers.json and/or Part 2 library/index.json
    style: str = "apa"
    use_llm: bool = True
    # Sonnet by default — pass --llm-model claude-opus-5 explicitly if the
    # extra cost is worth it for a particular draft.
    llm_model: str = llm.DEFAULT_MODEL
    # Classifying each paper's stance against each sub-question is bulk
    # extraction work, not drafting — so it takes the cheap tier, and stays
    # on the same model visualize-library uses. Same model + same cache file
    # means Part 3 reuses classifications already paid for rather than
    # re-running them.
    extraction_llm_model: str = llm.DEFAULT_EXTRACTION_MODEL
    stance_cache_path: Optional[str] = None
    min_relevance: float = 0.1
    words_per_question: int = DEFAULT_WORDS_PER_QUESTION
    output_path: Optional[str] = None
    # Written alongside the Markdown draft unless disabled — same content,
    # styled for reading in a browser rather than in a text editor.
    html_output_path: Optional[str] = None
    write_html: bool = True


def _load_papers_from_source(path: str) -> List[Paper]:
    p = Path(path)
    if not p.is_file():
        print(f"  [literature-review] source not found, skipping: {p}", file=sys.stderr)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  [literature-review] couldn't read {p} ({exc})", file=sys.stderr)
        return []

    if "entries" in data:  # Part 2 library/index.json format
        return [Paper(**e["paper"]) for e in data["entries"] if e.get("paper")]
    if "papers" in data:  # Part 1 <report>.papers.json format
        return [Paper(**paper) for paper in data["papers"]]
    print(f"  [literature-review] unrecognized format in {p}, skipping", file=sys.stderr)
    return []


def _load_all_papers(paths: List[str]) -> List[Paper]:
    all_papers: List[Paper] = []
    for path in paths:
        all_papers.extend(_load_papers_from_source(path))
    return dedupe_papers(all_papers)


_INTRO_SYSTEM_PROMPT = (
    "Write a short academic-style introduction (3-5 sentences) for a literature review, framing "
    "why the student's research question matters and what the review covers. Do not invent any "
    "facts, findings, statistics, or citations here — this paragraph only frames motivation and "
    "scope. No citations in this paragraph.\n\n" + llm.ACADEMIC_STYLE_NOTE
)


def _draft_intro(inputs: LiteratureReviewInputs, num_papers: int, client) -> str:
    if client is not None:
        user_message = (
            f"Field: {inputs.field}\n"
            f"Working title: {inputs.working_title}\n"
            f"Research question: {inputs.research_question or 'n/a'}\n"
            f"Number of sub-questions this review covers: {len(inputs.sub_questions)}"
        )
        result = llm.ask(client, _INTRO_SYSTEM_PROMPT, user_message, model=inputs.llm_model, max_tokens=200)
        if result:
            return result

    topic = inputs.research_question or inputs.working_title
    return (
        f"This review synthesizes {num_papers} source(s) relevant to the question: \"{topic}\". "
        f"It is organized around the sub-questions below, noting where the literature agrees, "
        f"disagrees, or has not yet been explored."
    )


def _fit_paper_texts(texts: List[str], budget: int = MAX_PROMPT_TEXT_CHARS) -> Tuple[List[str], int]:
    """Fit each paper's text into a shared character budget, returning the
    (possibly trimmed) texts and how many were trimmed.

    Shares are equal, but a short paper donates what it does not use to the
    longer ones, so a budget is only ever spent on text that exists. Whole
    papers are never dropped: a review that quietly stopped considering a
    source would be worse than one that considered a long source in part.
    """
    if sum(len(t) for t in texts) <= budget or not texts:
        return list(texts), 0

    remaining_budget = budget
    remaining = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    allowance = {}
    for position, index in enumerate(remaining):
        share = remaining_budget // (len(remaining) - position)
        allowance[index] = min(len(texts[index]), share)
        remaining_budget -= allowance[index]

    fitted, trimmed = [], 0
    for i, text in enumerate(texts):
        if len(text) > allowance[i]:
            trimmed += 1
            fitted.append(text[: allowance[i]])
        else:
            fitted.append(text)
    return fitted, trimmed

# Grounded in standard literature-review guidance (e.g. Purdue OWL, university
# writing-center synthesis guides): synthesize by theme, don't summarize
# source-by-source; avoid the "laundry list"/"he-said-she-said" pattern where
# every sentence opens with an author's name; quote sparingly and only when
# exact wording earns its place, otherwise paraphrase; connect and contrast
# sources within the same sentence rather than listing them in sequence; when
# the evidence itself is contested, walk through both sides' reasoning as a
# real debate rather than a one-line "sources disagree" aside — a literature
# review is expected to critically evaluate competing evidence, not just
# report that it exists.
_SYNTHESIS_SYSTEM_PROMPT_TEMPLATE = (
    "You write ONE SECTION of a literature review — roughly {words} words, several paragraphs — "
    "addressing the given sub-question, using ONLY the material provided below for each paper. "
    "This is a full section of a thesis chapter, not a summary paragraph: develop the argument "
    "across paragraphs, each making its own point and building on the last, the way a published "
    "review does. Do not pad to reach the length; if the material genuinely does not support a "
    "section this long, write what it does support and say plainly where the evidence runs out.\n"
    "- STRUCTURE IT. Open by framing what is at stake in this sub-question, then work through the "
    "evidence thematically across several paragraphs, and close by stating where the weight of "
    "evidence currently sits. Do not use sub-headings or bullet points — continuous academic prose "
    "only.\n"
    "- SYNTHESIZE, don't summarize source-by-source. Never write a 'laundry list' where every "
    "sentence starts with an author's name (e.g. 'Smith (2020) found X. Jones (2019) found Y.'). "
    "Instead, lead with the claim or theme, and weave citations in as support — explicitly comparing, "
    "contrasting, or grouping sources that agree or disagree within the same sentence or two.\n"
    "- WHEN THE PAPERS DISAGREE, DEBATE IT. If the papers given include both a 'supports' and a "
    "'challenges' stance, do not just note that they disagree — structure the paragraph as a genuine "
    "debate: present the case FOR first (the supporting evidence and the reasoning behind it), then "
    "the case AGAINST (the challenging evidence and its reasoning), then close with a brief critical "
    "evaluation weighing the two — which side has the stronger, more recent, or more directly relevant "
    "evidence, or a plausible reason for the disagreement (different populations, methods, contexts, "
    "etc). If every paper given shares the same stance, skip the debate structure and just synthesize "
    "that consistent evidence.\n"
    "- CITE USING EXACTLY THE MARKER GIVEN. Each paper below comes with the exact in-text citation "
    "marker to use for it (already matching the student's chosen citation style) — reproduce that "
    "marker's punctuation and form exactly, right after the claim it supports. Never invent a "
    "different form or guess at style rules yourself. When quoting a passage near a '[Page N]' marker, "
    "work that page number into the given marker the natural way for its form (e.g. ', p. N' before "
    "the closing parenthesis for an author-date/MLA-style marker, or 'p. N' alongside a numbered "
    "marker like [3]).\n"
    "- PREFER PARAPHRASE. Use a short direct quotation only when the exact wording matters — a precise "
    "definition, a specific finding stated in a distinctive or memorable way, or language too important "
    "to paraphrase safely. Use at most 1-2 direct quotations in the whole paragraph, even with more "
    "papers available — quoting every paper is a sign of weak synthesis, not thoroughness.\n"
    "- QUOTE VERBATIM ONLY. Any text inside quotation marks must be copied character-for-character from "
    "an 'Abstract' or 'Excerpt from the original document' block given below — never invent, "
    "paraphrase-then-quote, or reconstruct a quotation from memory. If nothing given is worth quoting "
    "directly, use zero quotations — that's the normal case, not a failure.\n"
    "- Write in formal academic prose — full sentences and paragraphs, not bullet points.\n"
    "- Text extracted from PDFs can contain minor artifacts (broken hyphenation, odd line breaks, "
    "OCR noise) — if a passage looks garbled, paraphrase instead of quoting it.\n"
    "- If the material given doesn't really address the sub-question, say that plainly instead of stretching.\n\n"
    + llm.ACADEMIC_STYLE_NOTE
)


def _synthesis_system_prompt(words: int) -> str:
    return _SYNTHESIS_SYSTEM_PROMPT_TEMPLATE.format(words=words)


def _citation_marker_for(paper: Paper, style: str, ref_number_by_key: Dict[str, int]) -> str:
    """The exact in-text citation marker to hand the LLM (or use in the
    heuristic fallback) for this paper, in whatever style the student
    configured. IEEE numbers are assigned the first time a paper is seen,
    in the order sections are drafted — an approximation of "citation
    order of appearance" (the actual IEEE convention) without needing to
    parse which citations an LLM's free-text output actually used — and
    reused for every later mention of the same paper."""
    if style.lower() == "ieee":
        key = paper.key()
        if key not in ref_number_by_key:
            ref_number_by_key[key] = len(ref_number_by_key) + 1
        return in_text_citation(paper, style, ref_number=ref_number_by_key[key])
    return in_text_citation(paper, style)


# Title lines, author names and affiliations all come out of a PDF as short
# fragments; anything this short is structure, not argument.
_MIN_SNIPPET_CHUNK_CHARS = 40
MAX_FALLBACK_SNIPPET_CHARS = 320
_CHUNK_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _fallback_snippet(paper: Paper, question: str) -> str:
    """The most on-question passage of a paper, for the no-prose fallback.

    Not simply the first N characters: on a locally indexed PDF that is the
    title page and author affiliations, which is what made the fallback
    outline unreadable. Not extractive_summary() either — that splits on
    sentence punctuation, and extracted PDF text has line breaks where
    sentences end, so a title block comes back as one "sentence" and is
    returned whole.
    """
    source = paper.abstract or paper.full_text_excerpt or ""
    chunks = [c.strip() for c in _CHUNK_SPLIT_RE.split(source) if len(c.strip()) >= _MIN_SNIPPET_CHUNK_CHARS]
    if not chunks:
        return source.strip()[:MAX_FALLBACK_SNIPPET_CHARS]

    question_terms = set(tokenize(question))
    best = max(
        range(len(chunks)),
        key=lambda i: (len(question_terms & set(tokenize(chunks[i]))), -i),
    )
    snippet = " ".join(chunks[best : best + 2])
    return snippet[:MAX_FALLBACK_SNIPPET_CHARS].rstrip()


def _prompt_text_for(paper: Paper) -> str:
    return paper.full_text_excerpt or paper.abstract or ""


def _paper_block(paper: Paper, stance_label: str, citation_marker: str = "", text: Optional[str] = None) -> str:
    author = paper.authors[0].split()[-1] if paper.authors and paper.authors[0].split() else "Unknown"
    marker_note = f" Cite this paper in-text using exactly: {citation_marker}." if citation_marker else ""
    lines = [f"- {author} ({paper.year or 'n.d.'}), stance: {stance_label}.{marker_note} Title: {paper.title}."]
    if paper.abstract:
        lines.append(f'  Abstract (verbatim): "{paper.abstract}"')
    excerpt = paper.full_text_excerpt if text is None else (text if paper.full_text_excerpt else None)
    if excerpt:
        # The whole extracted document by default, not a fixed short prefix —
        # a section that weighs both sides needs each paper's actual
        # argument, not whatever fell in the first few thousand characters.
        # _fit_paper_texts only trims when a batch would not otherwise fit.
        lines.append(
            '  Excerpt from the original document, verbatim, "[Page N]" markers included where known '
            f'(quote this exact wording only, citing the nearest page marker): "{excerpt}"'
        )
    if not paper.abstract and not paper.full_text_excerpt:
        lines.append("  (no abstract or text available — do not make specific claims about this paper's findings)")
    return "\n".join(lines)


def _select_papers_for_synthesis(question: str, grouped: Dict[str, List[Paper]], cap: int) -> List[Tuple[str, Paper]]:
    """Pick up to `cap` papers for one synthesis call, balanced across
    stances rather than exhausting the cap on whichever stance happens to
    have the most papers. A sub-question with 15 supporting papers and 2
    challenging ones must still surface those 2 challengers — the debate
    the paragraph is asked to write needs both sides represented, not just
    the majority view. Within each stance, papers are ranked by relevance
    to THIS sub-question specifically (not just the library-wide research
    question), so whichever papers are kept are the most relevant available
    on each side."""
    groups = [
        ("supports", sorted(grouped["supports"], key=lambda p: score_relevance(question, p), reverse=True)),
        ("challenges", sorted(grouped["challenges"], key=lambda p: score_relevance(question, p), reverse=True)),
        ("mixed/ambiguous", sorted(grouped["mixed"], key=lambda p: score_relevance(question, p), reverse=True)),
    ]
    selected: List[Tuple[str, Paper]] = []
    round_idx = 0
    while len(selected) < cap and any(round_idx < len(g) for _, g in groups):
        for label, g in groups:
            if len(selected) >= cap:
                break
            if round_idx < len(g):
                selected.append((label, g[round_idx]))
        round_idx += 1
    return selected


def _draft_synthesis_section(
    question: str,
    grouped: Dict[str, List[Paper]],
    inputs: LiteratureReviewInputs,
    client,
    ref_number_by_key: Dict[str, int],
) -> Tuple[str, List[Paper], Optional[str]]:
    """Returns (section text, papers cited, failure reason).

    The failure reason is what makes a degraded section honest: the heuristic
    fallback is a bullet list of snippets, which is a categorically worse
    thing than a written section — shipping it silently under a header
    claiming "Claude-written prose" misrepresents the draft.
    """
    if not (grouped["supports"] or grouped["challenges"] or grouped["mixed"]):
        return (
            "_No paper in the current sources speaks directly to this sub-question — "
            "a potential gap worth targeting with a follow-up search._",
            [],
            None,
        )

    # Cap how many papers go into one call — keeps prompt size (and cost)
    # bounded regardless of library size — but balanced across stances (see
    # _select_papers_for_synthesis), not just a straight truncation that
    # could silently drop every challenging paper behind a wall of
    # supporting ones.
    labeled = _select_papers_for_synthesis(question, grouped, MAX_PAPERS_PER_SYNTHESIS_CALL)
    cited_papers = [p for _, p in labeled]

    failure: Optional[str] = None
    if client is not None:
        texts = [_prompt_text_for(p) for _, p in labeled]
        fitted, trimmed = _fit_paper_texts(texts)
        blocks = [
            _paper_block(p, label, _citation_marker_for(p, inputs.style, ref_number_by_key), text)
            for (label, p), text in zip(labeled, fitted)
        ]
        user_message = f"Sub-question: {question}\n\nPapers:\n" + "\n".join(blocks)
        # Generous headroom over the target: a word count is a target, not a
        # cap, and running long beats being cut off mid-sentence.
        errors: List[str] = []
        result = llm.ask(
            client,
            _synthesis_system_prompt(inputs.words_per_question),
            user_message,
            model=inputs.llm_model,
            max_tokens=max(int(inputs.words_per_question * 2.5), 1500),
            errors=errors,
        )
        if result:
            if trimmed:
                result += (
                    f"\n\n_Note: the full text of {trimmed} of these {len(labeled)} source(s) was too long "
                    "to send in full, so this section was written from as much of each as would fit._"
                )
            return result, cited_papers, None
        failure = errors[0] if errors else "the request returned nothing"

    # Heuristic fallback: an honest structured outline, not prose — still
    # using each paper's real citation marker so even this no-LLM path
    # respects whatever style was configured, and its own extractive summary
    # rather than the first 220 characters of a PDF, which on a locally
    # indexed paper is the title page and author affiliations.
    lines = []
    for label, p in labeled:
        marker = _citation_marker_for(p, inputs.style, ref_number_by_key)
        lines.append(f"- **{label.capitalize()}** — {marker}: {_fallback_snippet(p, question)}")
    return "\n".join(lines), cited_papers, failure


_CONCLUSION_SYSTEM_PROMPT = (
    "Write a closing 'Conclusion and areas for further research' section (120-200 words) for a "
    "literature review, given (1) sub-questions where the papers found disagree with each other, and "
    "(2) sub-questions with no supporting literature at all. First, briefly synthesize what the "
    "review as a whole suggests about the overall topic. Then end with a clearly labeled "
    "'**Areas for further research:**' bullet list, one bullet per gap/tension given, each phrased as "
    "a concrete direction for a follow-up study (e.g. what question it should ask, or what population/"
    "method might resolve a disagreement) rather than just restating the sub-question verbatim. Frame "
    "these as opportunities for the student's own thesis contribution. Invent nothing beyond what is "
    "given.\n\n" + llm.ACADEMIC_STYLE_NOTE
)


def _draft_conclusion_section(analysis: SubquestionAnalysis, no_coverage: List[str], inputs: LiteratureReviewInputs, client) -> str:
    tensions = analysis.tensions()
    if not tensions and not no_coverage:
        return "No major tensions or coverage gaps were identified among the sub-questions checked."

    if client is not None:
        parts = []
        if tensions:
            parts.append("Sub-questions where the papers found disagree with each other:\n" + "\n".join(f"- {q}" for q in tensions))
        if no_coverage:
            parts.append("Sub-questions with no supporting literature found at all:\n" + "\n".join(f"- {q}" for q in no_coverage))
        # Same headroom reasoning as the synthesis call above — 120-200 words
        # requested, generous budget so truncation is rare.
        result = llm.ask(client, _CONCLUSION_SYSTEM_PROMPT, "\n\n".join(parts), model=inputs.llm_model, max_tokens=500)
        if result:
            return result

    lines = ["**Areas for further research:**", ""]
    if tensions:
        lines.append("_Contested in the literature reviewed — the evidence itself disagrees:_")
        for q in tensions:
            lines.append(f"- {q}")
        lines.append("")
    if no_coverage:
        lines.append("_No literature found at all — a genuine gap worth a dedicated search:_")
        for q in no_coverage:
            lines.append(f"- {q}")
    return "\n".join(lines).strip()


def run_literature_review(inputs: LiteratureReviewInputs) -> str:
    """Run the full pipeline and return the path to the written draft."""
    if inputs.style.lower() not in STYLES:
        raise ValueError(f"Unknown citation style '{inputs.style}'. Choose from: {', '.join(STYLES)}")
    if not inputs.sub_questions:
        raise ValueError("No sub-questions to draft around. Run topic-finder first, or pass --sub-questions.")

    if inputs.use_llm:
        issue = llm.availability_issue()
        if issue:
            print(f"Claude requested but unavailable ({issue}) — using a heuristic outline for this run.", file=sys.stderr)

    papers = _load_all_papers(inputs.paper_sources)
    if not papers:
        raise ValueError(
            "No papers found in the given sources. Run topic-finder and/or index-library first, "
            "or pass --topic-cache/--library-index explicitly."
        )

    # Score against every question the review is actually asking, not just
    # the headline one, and keep a paper if it matches ANY of them. Scoring
    # on the research question alone silently dropped papers that were a
    # direct hit on a sub-question: "School start times and academic
    # outcomes" scores 0.00 against "Does sleep deprivation affect
    # adolescent decision-making?" while scoring 0.67 against the
    # sub-question it was indexed for.
    questions = [q for q in ([inputs.research_question or inputs.working_title] + list(inputs.sub_questions)) if q]
    scored = sorted(
        ((p, max(score_relevance(q, p) for q in questions)) for p in papers),
        key=lambda pair: pair[1],
        reverse=True,
    )
    relevant = [p for p, r in scored if r >= inputs.min_relevance]
    off_topic_count = len(papers) - len(relevant)
    used_fallback = False
    if not relevant:
        # An empty draft helps nobody, but silently reviewing the wrong
        # literature is worse — fall back loudly, and say so in the draft
        # itself rather than only on stderr.
        used_fallback = True
        relevant = [p for p, _ in scored]
        print(
            f"None of the {len(papers)} paper(s) scored at least {inputs.min_relevance} against your "
            "question or sub-questions — drafting from all of them anyway. Treat the result with "
            "suspicion: it may be a review of the wrong literature.",
            file=sys.stderr,
        )
    elif off_topic_count:
        print(
            f"Ignoring {off_topic_count} of {len(papers)} paper(s) that do not match your question or "
            f"sub-questions (relevance below {inputs.min_relevance}).",
            file=sys.stderr,
        )

    client = llm.get_client(quiet=True) if inputs.use_llm else None
    analysis = analyze_subquestions(
        inputs.sub_questions,
        relevant,
        use_llm=inputs.use_llm,
        model=inputs.extraction_llm_model,
        cache_path=inputs.stance_cache_path,
    )

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: List[str] = []
    lines.append("# Literature Review — Draft")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")
    lines.append(f"*Generated {now}*")
    lines.append("")
    lines.append(f"- **Field:** {inputs.field}")
    lines.append(f"- **Working title:** {inputs.working_title}")
    if inputs.research_question:
        lines.append(f"- **Research question:** {inputs.research_question}")
    # Counted over the papers actually in scope, not everything loaded — the
    # header claiming "drawing on 41 papers" when 33 were ignored as
    # off-topic overstates what the draft rests on.
    with_full_text = sum(1 for p in relevant if p.full_text_excerpt)
    ignored = (
        f" ({off_topic_count} ignored as not matching your question or sub-questions)"
        if off_topic_count and not used_fallback
        else ""
    )
    lines.append(
        f"- **Drawing on:** {len(relevant)} of {len(papers)} paper(s) from "
        f"{len(inputs.paper_sources)} source file(s){ignored}"
    )
    if used_fallback:
        lines.append(
            f"- ⚠️ **No paper matched your questions** (nothing scored at least {inputs.min_relevance}), "
            "so this draft was written from all of them anyway — it may be a review of the wrong "
            "literature. Check your sub-questions, or widen the library, before relying on it."
        )
    lines.append(
        f"- **Real text available for quoting:** {with_full_text} of {len(relevant)} paper(s) "
        f"(indexed by Part 2) — the rest have only an abstract, so claims about them are paraphrased, not quoted"
    )
    drafting_mode_index = len(lines)
    lines.append("")  # filled in below, once it is known how many sections actually got written
    lines.append("")

    lines.append("## Introduction")
    lines.append("")
    lines.append(_draft_intro(inputs, len(relevant), client))
    lines.append("")

    cited_papers_by_key: Dict[str, Paper] = {}
    no_coverage: List[str] = []
    degraded: List[Tuple[str, str]] = []
    # IEEE numbers a paper by order of first citation, not alphabetically —
    # populated as _draft_synthesis_paragraph hands out markers below, then
    # reused to number the reference list the same way.
    ref_number_by_key: Dict[str, int] = {}

    for i, question in enumerate(inputs.sub_questions, start=1):
        grouped = analysis.grouped_papers(question, relevant)
        lines.append(f"## {i}. {question}")
        lines.append("")
        section, cited, failure = _draft_synthesis_section(question, grouped, inputs, client, ref_number_by_key)
        if failure:
            degraded.append((question, failure))
            lines.append(
                f"> ⚠️ **This section is a fallback outline, not a written review.** The request to Claude "
                f"failed ({failure}), so what follows is a bullet list of the relevant sources instead of "
                "prose. Re-run to try again."
            )
            lines.append("")
        lines.append(section)
        lines.append("")
        if not cited:
            no_coverage.append(question)
        for paper in cited:
            cited_papers_by_key[paper.key()] = paper

    lines.append("## Conclusion and Areas for Further Research")
    lines.append("")
    lines.append(_draft_conclusion_section(analysis, no_coverage, inputs, client))
    lines.append("")

    lines.append("## References")
    lines.append("")
    lines.append(f"*(Only papers actually cited above, in {inputs.style.upper()} style — verify before submitting.)*")
    lines.append("")
    if inputs.style.lower() == "ieee":
        # Citation order (matching the in-text [n] markers already handed
        # out), not alphabetical — the IEEE convention.
        cited_list = sorted(cited_papers_by_key.values(), key=lambda p: ref_number_by_key.get(p.key(), 10**9))
    else:
        cited_list = sorted(cited_papers_by_key.values(), key=lambda p: (p.authors[0] if p.authors else p.title))
    if not cited_list:
        lines.append("_No papers were cited in the drafted sections above._")
    for i, paper in enumerate(cited_list, start=1):
        ref_number = ref_number_by_key.get(paper.key(), i) if inputs.style.lower() == "ieee" else i
        lines.append(format_citation(paper, inputs.style, ref_number=ref_number))
        lines.append("")

    # Now that every section has been attempted, the header can say what
    # actually happened rather than what was intended.
    if not client:
        mode = "heuristic structured outline (no ANTHROPIC_API_KEY, or --no-llm)"
    elif degraded:
        mode = (
            f"⚠️ **partially failed** — {len(degraded)} of {len(inputs.sub_questions)} section(s) fell back "
            "to a bullet outline because the request to Claude failed; see the warnings below"
        )
    else:
        mode = f"Claude-written prose, targeting ~{inputs.words_per_question} words per sub-question"
    lines[drafting_mode_index] = f"- **Drafting mode:** {mode}"

    report_text = "\n".join(lines)

    output_path = Path(inputs.output_path) if inputs.output_path else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")

    if inputs.write_html:
        # Rendered from the same Markdown that was just written, so the two
        # can never drift apart.
        html_path = Path(inputs.html_output_path) if inputs.html_output_path else output_path.with_suffix(".html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_review_html(report_text), encoding="utf-8")
        print(f"HTML version: {html_path}", file=sys.stderr)

    return str(output_path)


def _default_output_path() -> Path:
    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("output") / f"literature-review-{timestamp}.md"
