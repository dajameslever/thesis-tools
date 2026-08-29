"""Part 3's second output: a McKinsey-style executive summary of the
literature, written from the sections the review just drafted.

The literature review answers each sub-question in turn. That is the right
shape for a thesis chapter and the wrong shape for anyone who needs to know
what the literature *says* in five minutes — a supervisor, a panel, or the
student themselves deciding where the contribution is. This module produces
the other document: answer first, themes across the questions rather than
one section per question, and the disagreements stated as disagreements
instead of averaged away.

Structure follows the Pyramid Principle as consulting practice uses it:

  * SCQA opening — Situation, Complication, Question, Answer — where the
    Answer IS the headline. A reader who stops after four sentences still
    knows what the literature concludes.
  * 2-5 key lines, each a complete assertion used as its own heading, so
    reading only the headings gives the whole argument. "Trust mediates
    adoption more strongly than perceived accuracy" is a key line;
    "Trust" is not.
  * Every key line tagged for the strength of what stands behind it. The
    consulting version tags Evidence / Assumption / Gap; the literature
    version tags [Evidence] / [Contested] / [Gap], because in a review the
    interesting middle case is not an untested assumption but a genuine
    disagreement between published studies.
  * A "so what" for the thesis at the end, as concrete next actions.

Every claim carries the same in-text citation markers the review already
handed out, so the two documents cite identically and the summary stands
on its own.
"""

from __future__ import annotations

import re
import sys
from typing import Dict, List, Optional, Tuple

from . import llm
from .citations import format_citation, reference_sort_key
from .sources.base import Paper

# The summary is written from the drafted sections, which are already
# condensed prose rather than raw papers — so this prompt is far smaller
# than the synthesis prompts, but a long review can still run past a
# sensible request size. Sections are trimmed evenly if the total exceeds
# this, and the summary says so rather than hiding it.
MAX_SECTION_CHARS = 120_000

# Scales with the evidence behind it, on the same principle as the review's
# own sections: a summary of four papers that runs to 1,400 words is padding,
# and a summary of sixty that runs to 800 has thrown most of the evidence
# away. The cap is deliberately high enough that a large library is not
# flattened to the same length as a small one.
WORDS_PER_SOURCE = 80
MIN_WORDS = 400
MAX_WORDS = 2500

# The detailed variant answers a different question — "what is actually in
# this literature?" rather than "what do I need to know?" — so it is scaled
# to carry each source's specifics (population, method, direction, size,
# period) rather than only the conclusions drawn from them.
DETAILED_WORDS_PER_SOURCE = 200
DETAILED_MIN_WORDS = 800
# High enough that the cap is not fighting the content. At 200 words per
# source, 34 sources want ~6,800 words; capping that at 4,000 asked for a
# document the evidence did not fit into, and the model wrote past the ask
# rather than dropping the detail — which is how a run hit the output limit
# with the closing section unwritten.
DETAILED_MAX_WORDS = 8000

# A word of English costs a bit over a token. Kept explicit because the
# request budget is set in tokens while every target here is set in words,
# and quietly conflating the two is what makes a budget look generous when
# it is not.
TOKENS_PER_WORD = 1.4
# How far past the target the model is allowed to run before the API cuts it
# off. A word count is a target, not a cap: the model routinely writes long,
# and being cut off mid-document is far worse than paying for a few hundred
# unused tokens of headroom.
OUTPUT_HEADROOM = 2.5
# Well inside what the drafting models allow, and far past anything this
# tool legitimately produces.
MAX_OUTPUT_TOKENS = 32_000


def max_tokens_for(target_words: int, extra_room: float = 1.0) -> int:
    """The output budget for a document of roughly `target_words`.

    `extra_room` widens it for a retry after the model ran out of room —
    retrying a truncation on the same budget just truncates again in the
    same place, which is a wasted request rather than a second chance.
    """
    budget = target_words * TOKENS_PER_WORD * OUTPUT_HEADROOM * extra_room
    return int(min(max(budget, 1500), MAX_OUTPUT_TOKENS))

VARIANTS = ("summary", "detailed")


def target_words_for(source_count: int, variant: str = "summary") -> int:
    if variant == "detailed":
        return max(DETAILED_MIN_WORDS, min(DETAILED_WORDS_PER_SOURCE * source_count, DETAILED_MAX_WORDS))
    return max(MIN_WORDS, min(WORDS_PER_SOURCE * source_count, MAX_WORDS))


# Length alone is not proportionality: a summary of forty sources that is
# long but still makes three points has padded three points. The number of
# findings and callouts scales too, so more evidence buys more distinct
# things said rather than more words about the same ones. Each band is
# (max sources, findings, callouts).
_STRUCTURE_BANDS = (
    (4, "two to three", "two"),
    (10, "three to four", "two to three"),
    (25, "four to five", "three to four"),
    (10**9, "five to seven", "four to six"),
)


def structure_for(source_count: int) -> Tuple[str, str]:
    """How many findings and callouts this much evidence supports, as words
    rather than digits — the count goes into the instruction, and a model
    follows "four to five" more reliably than "4-5"."""
    for ceiling, findings, callouts in _STRUCTURE_BANDS:
        if source_count <= ceiling:
            return findings, callouts
    return _STRUCTURE_BANDS[-1][1:]


_EXEC_SYSTEM_PROMPT = (
    "You write the EXECUTIVE SUMMARY of a literature review, for a reader who will not read the "
    "review itself. Work only from the drafted sections given to you — every claim must already be "
    "present in them. Invent no findings, no papers, and no citations.\n"
    "\n"
    "Structure, exactly, using these Markdown headings:\n"
    "\n"
    "## The short version\n"
    "Four sentences, each on its own line, labelled in bold: **Situation:** the settled context this "
    "literature takes for granted. **Complication:** what has changed, or what the literature cannot "
    "agree on, that makes the review worth reading. **Question:** the single question the review "
    "answers. **Answer:** what the literature as a whole indicates — stated plainly, as a claim "
    "someone could disagree with. The Answer is the headline of the whole document; a reader who "
    "stops here must still know what the literature concludes.\n"
    "\n"
    "## What the evidence shows\n"
    "Findings that cut ACROSS the sub-questions — themes, not a restatement of each section in "
    "turn. Two papers reaching the same conclusion by different routes is a theme; 'Section 3 "
    "discussed X' is not. How many to write is stated with the sub-questions at the end of the "
    "message; write that many distinct findings rather than padding fewer ones out to length. Each "
    "finding is a `### ` heading that states the finding as a complete assertion, so that reading "
    "only the headings gives the whole argument. End each heading with one tag in square "
    "brackets:\n"
    "  [Evidence] — several sources agree and none in the set contradicts it.\n"
    "  [Contested] — sources in the set disagree; say so in the heading itself.\n"
    "  [Gap] — the sources point toward it but none tests it directly.\n"
    "The tag is a claim about how much weight a finding will bear, so make it one: where the "
    "sections say what a finding rests on — how it was studied, on whom, when — let that decide "
    "the tag rather than how many papers happen to mention it. A single well-designed study can "
    "outweigh three that assume what they set out to show.\n"
    "Under each heading write one short paragraph: what the sources show and which sources show "
    "it, then a final sentence beginning 'So:' that states what this finding means the student "
    "should now do differently — a design choice, a scope decision, a claim they can now make or "
    "must now stop making. A finding with no 'So:' sentence is not finished. The implication must "
    "follow from the finding above it; do not reach for generic advice.\n"
    "\n"
    "## Where the literature disagrees\n"
    "The debate, stated as a debate. For each disagreement: what one side claims and who claims it, "
    "what the other side claims and who claims it, and what would settle it — a population, a "
    "measure, a method, a time period. Name the papers on each side. If the sources genuinely do "
    "not conflict anywhere, say that plainly and treat it as a finding in itself: an evidence base "
    "with no disagreement in it is either immature or narrowly selected, and the reader should be "
    "told which you think it is.\n"
    "\n"
    "## Worth calling out\n"
    "Things a careful reader would want flagged and would otherwise miss — how many is stated at "
    "the end of the message. Real "
    "candidates: a result that cuts against the rest of the set; an unusually strong or unusually "
    "weak study design carrying more weight than it should; a claim that rests on a single source; "
    "a concentration of the evidence in one country, sector, period or population; a definition "
    "used inconsistently between papers; a finding that has aged badly; a conclusion that outruns "
    "the evidence behind it. Be specific and cite. Do "
    "not pad this section to reach a count — three sharp callouts beat five obvious ones.\n"
    "\n"
    "## What this means for the thesis\n"
    "Three to six concrete next actions, ordered with the highest-value first, each a single line, "
    "verb first: the search to run, the gap to target, the disagreement to adjudicate, the method "
    "that would settle something. Each names what it would establish, and points back to the "
    "finding or callout it comes from. Reject any action that would read the same way for a "
    "different thesis in a different field ('read more widely', 'consider methodology') — if it "
    "does not name something specific to this evidence base, it does not belong here.\n"
    "\n"
    "Rules:\n"
    "- CITE EVERY CLAIM using the exact in-text citation markers as they already appear in the "
    "drafted sections — copy them character for character. Never invent a marker, a year, or an "
    "author name, and never cite a paper that is not in the sections given.\n"
    "- Paraphrase. Do not quote the sections back; this is a summary, not an extract.\n"
    "- No hedging as a substitute for a position. Where the evidence supports a claim, state it; "
    "where it does not, say what is missing. 'More research is needed' on its own is not a finding.\n"
    "- Every section earns its place by changing what the reader would do. A section that only "
    "describes what the literature contains, without saying what follows from it, has not been "
    "written yet.\n"
    "- Say each thing once. Findings must not restate the Answer, callouts must not restate "
    "findings, and next actions must not restate either — each names what to do, not what was "
    "already said. Never write the same point in two different wordings.\n"
    "- No bullet-point dumps of paper titles anywhere.\n"
    "\n" + llm.ACADEMIC_STYLE_NOTE
)


# Markdown joins consecutive lines into one paragraph, so an SCQA written
# as four lines renders as a single block of text — exactly the wall the
# opening is supposed to save the reader from. The labels are separated into
# their own paragraphs here rather than only being asked for in the prompt,
# because this is the one block of the document that has to land.
_SCQA_LABELS = ("**Complication:**", "**Question:**", "**Answer:**")


_NO_REPETITION_RULES = (
    "REPETITION IS THE FAILURE MODE OF THIS DOCUMENT. The same evidence reaches several "
    "sub-questions, and restating it under each one turns a detailed summary into a long one. "
    "Enforce all of these:\n"
    "- State each source's contribution ONCE, in full, under the sub-question it bears on most "
    "directly. Where it also bears on a later one, write only what is ADDITIONAL there and refer "
    "back with the citation alone — never restate the finding.\n"
    "- Never open a section by restating its own sub-question. The heading has already said it.\n"
    "- Never state a finding and then restate it as its own implication ('X found Y. This "
    "suggests Y.'). If the implication is not more than the finding, leave it out.\n"
    "- Never write the same point in two different wordings anywhere in the document.\n"
    "- Write no section that recaps the document. There is no closing summary: the reader has "
    "just read it.\n"
)

_DETAILED_SYSTEM_PROMPT = (
    "You write a DETAILED SUMMARY of a literature review: what is actually in this literature, "
    "sub-question by sub-question, for a reader who wants everything interesting the sources say "
    "without reading the full review. Work only from the drafted sections given to you — every "
    "claim must already be present in them. Invent no findings, no papers, no citations, and no "
    "specifics that the sections do not state.\n"
    "\n"
    "This is NOT an executive summary. Do not lead with an answer, do not compress to key lines, "
    "and do not drop a finding because it is minor. Detail is the point: what was studied, on "
    "whom and where, by what method, what was found, in which direction and how strongly, and "
    "when. Prefer the specific to the evaluative — 'significant', 'important' and 'robust' carry "
    "no information on their own. Where the sections do not give a detail, say what they do give "
    "rather than filling the gap.\n"
    "\n"
    "Structure, using these Markdown headings:\n"
    "\n"
    "## What this evidence base looks like\n"
    "Three or four sentences on the SHAPE of the evidence, not its findings: how much there is, "
    "where it clusters (period, setting, population, method), and where it is thin. No findings "
    "here — they belong to the sub-questions, and stating them twice is the one thing this "
    "document must not do.\n"
    "\n"
    "## (one heading per sub-question)\n"
    "The exact headings to use are listed for you at the end of the message. Copy each one "
    "verbatim, in the order given, and write a section under it \u2014 do not compose a heading of "
    "your own, and do not skip one. Open directly with what the "
    "sources establish — continuous prose, not a list of papers, each claim cited. Then, ONLY "
    "where there is something real to say, add any of these as their own short paragraph, "
    "starting with the bold lead-in exactly as written:\n"
    "  **Where they diverge:** who disagrees with whom, on what specifically, why they might "
    "reasonably differ (a different population, method, measure, setting or period usually "
    "explains more than one side being wrong), and what would settle it. Do not merely record "
    "that they differ.\n"
    "  **How good is the evidence:** what the claims above actually rest on — the design and "
    "method, the size and nature of the sample, the setting and period — and how far that carries "
    "them. Say where a conclusion outruns the evidence behind it, where an assumption is doing "
    "work the data does not, and where a study's own stated limitations qualify what it shows. "
    "Name real strengths as readily as weaknesses; a set of sources that only ever disappoints is "
    "a sign of the reviewer, not the field. Never invent a methodological detail the sections do "
    "not state.\n"
    "  **Notable:** what a careful reader would want flagged here — an outlier, a single-source "
    "claim, a definition used differently between papers, a theoretical starting point that "
    "changes what a finding means, a result that has aged badly.\n"
    "  **Not covered:** what this sub-question needs that no source in the set supplies.\n"
    "Omit any lead-in that would be empty. A heading followed by 'none' is noise.\n"
    "\n"
    "## Across the questions\n"
    "ONLY what no single sub-question above could carry: a pattern that becomes visible only when "
    "the questions are set side by side — a method or population common to all of them, a "
    "definition that shifts between them, a source that answers one question well and another "
    "badly. If a point already appears above, it is not eligible for this section. If nothing "
    "qualifies, write one sentence saying so and move on.\n"
    "\n"
    "## Where this leaves the thesis\n"
    "Three to six concrete next steps, each a single line, verb first, each naming what it would "
    "establish and which section above it comes from. Nothing that would read the same way for a "
    "different thesis in a different field.\n"
    "\n"
    + _NO_REPETITION_RULES
    + "\n"
    "Rules:\n"
    "- CITE EVERY CLAIM using the exact in-text citation markers as they already appear in the "
    "drafted sections — copy them character for character. Never invent a marker, a year, or an "
    "author name, and never cite a paper that is not in the sections given.\n"
    "- Paraphrase. Do not quote the sections back.\n"
    "- A sub-question with nothing behind it gets one honest sentence saying so, not a paragraph "
    "explaining that it has nothing behind it.\n"
    "\n" + llm.ACADEMIC_STYLE_NOTE
)


def _space_out_scqa(text: str) -> str:
    for label in _SCQA_LABELS:
        # Collapse whatever whitespace precedes the label — nothing, a single
        # newline, or an existing blank line — to exactly one blank line, so
        # the result is the same however the model chose to lay it out.
        text = re.sub(rf"\s*{re.escape(label)}", f"\n\n{label}", text)
    return text.lstrip("\n")


# What each variant must contain to be a document rather than a beginning.
_EXEC_REQUIRED_HEADINGS = (
    "## The short version",
    "## What the evidence shows",
    "## Where this leaves the thesis" ,
)


def _shortfall(text: str, variant: str, questions: List[str]) -> Optional[str]:
    """What is missing from a returned summary, or None if it is complete.

    A model that stops early does not announce it: the reply arrives with a
    normal stop reason, reads like the opening of the right document, and is
    written to disk as the deliverable. One run of this ended after the
    opening paragraph and a bare "## 1." heading. The only defence is to
    check that what came back is actually the document that was asked for.
    """
    stripped = text.strip()
    if not stripped:
        return "the model returned nothing"

    if variant == "detailed":
        missing = [
            _section_heading(i, question)
            for i, question in enumerate(questions, start=1)
            if _section_heading(i, question) not in text and f"## {i}." not in text
        ]
        if missing:
            return (
                f"{len(missing)} of {len(questions)} sub-question section(s) were never written "
                f"(first missing: \u201c{missing[0]}\u201d)"
            )
        if "## Where this leaves the thesis" not in text:
            return "the closing 'Where this leaves the thesis' section was never written"
    else:
        missing_headings = [h for h in _EXEC_REQUIRED_HEADINGS if h not in text]
        if missing_headings:
            return f"the '{missing_headings[0].lstrip('# ')}' section was never written"

    # A document that ends on a heading has stopped mid-sentence in the most
    # literal way: the section it just announced is not there.
    last = stripped.rsplit("\n", 1)[-1].strip()
    if last.startswith("#"):
        return f"it ends on the heading \u201c{last}\u201d with nothing under it"
    return None


def _section_heading(number: int, question: str) -> str:
    """The heading for one sub-question's section, generated in one place so
    the instruction that asks for it and the check that the model produced it
    can never disagree about what it looks like."""
    return f"## {number}. {question}"


def _fit_sections(sections: List[Tuple[str, str]], budget: int = MAX_SECTION_CHARS) -> Tuple[List[Tuple[str, str]], int]:
    """Trim section texts to fit `budget` total characters, sharing it evenly
    and letting short sections donate what they don't use — the same
    approach the synthesis prompt uses for paper texts, and for the same
    reason: dropping a whole sub-question silently is worse than shortening
    several. Returns (fitted, number trimmed)."""
    total = sum(len(text) for _, text in sections)
    if total <= budget or not sections:
        return sections, 0

    share = budget // len(sections)
    spare = sum(share - len(text) for _, text in sections if len(text) < share)
    over = [i for i, (_, text) in enumerate(sections) if len(text) > share]
    bonus = spare // len(over) if over else 0

    fitted: List[Tuple[str, str]] = []
    trimmed = 0
    for question, text in sections:
        allowance = share + bonus if len(text) > share else share
        if len(text) > allowance:
            fitted.append((question, text[:allowance].rstrip()))
            trimmed += 1
        else:
            fitted.append((question, text))
    return fitted, trimmed


def _evidence_base_note(paper_count: int, cited_count: int, tensions: List[str], no_coverage: List[str]) -> str:
    parts = [
        f"Written from {cited_count} paper(s) cited across {paper_count} judged relevant to the "
        "research question."
    ]
    if tensions:
        parts.append(f"{len(tensions)} sub-question(s) show disagreement between sources.")
    if no_coverage:
        parts.append(f"{len(no_coverage)} sub-question(s) have no supporting literature at all.")
    return " ".join(parts)


def build_summary(
    *,
    variant: str = "summary",
    research_question: str,
    field: str,
    sections: List[Tuple[str, str]],
    tensions: List[str],
    no_coverage: List[str],
    cited_papers: List[Paper],
    markers_by_key: Dict[str, str],
    style: str,
    client,
    model: str,
    relevant_paper_count: int,
    words: Optional[int] = None,
    cache: bool = True,
    usage_totals: Optional[Dict[str, int]] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Returns (markdown, failure reason, shortfall).

    The two are different problems and must not be reported as one. A
    *failure* means the request did not produce a document at all and what
    comes back is the skeleton. A *shortfall* means a real document came
    back but it is not the whole one — sections missing, or it ends on a
    heading with nothing under it. Both have to reach the reader; only the
    first makes the output a form to fill in.

    `variant` picks which document this is. "summary" is the executive
    summary: answer first, themed across the sub-questions, compressed to
    what a reader needs to know. "detailed" is the other half of the same
    coin — everything interesting the sources say, sub-question by
    sub-question, with the specifics that make a finding usable. They are
    built from identical inputs and differ only in what they are asked for.

    The failure reason matters for the same reason it does in the review: the
    fallback is a skeleton, not a summary, and shipping it silently under the
    same title would misrepresent it.
    """
    if variant not in VARIANTS:
        raise ValueError(f"Unknown summary variant '{variant}'. Choose from: {', '.join(VARIANTS)}")
    written = [(q, t) for q, t in sections if t.strip()]
    if not written:
        return (
            "_No sections were drafted, so there is nothing to summarize._",
            "the review produced no sections",
            None,
        )

    target = words or target_words_for(len(cited_papers), variant)
    failure: Optional[str] = None

    if client is not None:
        fitted, trimmed = _fit_sections(written)
        blocks = [f"### Sub-question: {q}\n{text}" for q, text in fitted]
        context = [
            f"Field: {field}",
            f"Research question: {research_question}",
            _evidence_base_note(relevant_paper_count, len(cited_papers), tensions, no_coverage),
        ]
        if tensions:
            context.append("Sub-questions where the sources disagree:\n" + "\n".join(f"- {q}" for q in tensions))
        if no_coverage:
            context.append("Sub-questions with no supporting literature:\n" + "\n".join(f"- {q}" for q in no_coverage))
        # Sections first so the bulk of the prompt sits in front of the cache
        # breakpoint; the instruction, which carries the varying word target,
        # goes after it. Same reasoning as the synthesis call.
        user_message = "\n\n".join(context) + "\n\nDrafted sections:\n\n" + "\n\n".join(blocks)
        if variant == "detailed":
            system_prompt = _DETAILED_SYSTEM_PROMPT
            # The headings are handed over ready to copy rather than
            # described as a template to fill in. Asking the model to
            # assemble "## <number>. <the sub-question, copied exactly>"
            # left it composing the heading itself, and a run of this was
            # seen to emit "## 1." and stop there — a two-paragraph document
            # written as though it were finished.
            headings = "\n".join(
                _section_heading(i, question) for i, (question, _) in enumerate(written, start=1)
            )
            instruction = (
                f"Write the detailed summary of the review above, aiming for about {target} words "
                f"across all {len(written)} sub-question(s) — a guide to the whole document, not a "
                "quota for each section: a sub-question with more behind it earns more room than "
                "one with less. Say each thing once.\n\n"
                "Use exactly these headings, copied verbatim, in this order, each followed by its "
                f"section:\n\n## What this evidence base looks like\n{headings}\n"
                "## Across the questions\n## Where this leaves the thesis"
            )
        else:
            system_prompt = _EXEC_SYSTEM_PROMPT
            findings, callouts = structure_for(len(cited_papers))
            instruction = (
                f"Write the executive summary of the review above, aiming for about {target} words. "
                f"This evidence base supports {findings} findings under 'What the evidence shows' "
                f"and {callouts} entries under 'Worth calling out' — write that many, each a "
                "distinct point, rather than padding fewer ones out to the word count."
            )
        errors: List[str] = []
        questions = [question for question, _ in written]
        result = shortfall = None
        extra_room = 1.0
        # One retry, because a model that stops early usually does not do it
        # twice, and because the prompt prefix is cached: the second attempt
        # re-reads it at a tenth of the input price rather than paying for
        # the papers again. More than one retry would be spending real money
        # on a pattern that is not converging.
        for attempt in (1, 2):
            meta: Dict[str, object] = {}
            result = llm.ask(
                client,
                system_prompt,
                user_message,
                model=model,
                max_tokens=max_tokens_for(target, extra_room),
                errors=errors,
                cache=cache,
                cache_suffix=instruction,
                usage_totals=usage_totals,
                meta=meta,
            )
            if result is None:
                break
            shortfall = _shortfall(result, variant, questions)
            if meta.get("truncated"):
                shortfall = (
                    "it ran out of room at the model's output limit"
                    + (f", and {shortfall}" if shortfall else "")
                )
                # The retry only helps if it has somewhere to go.
                extra_room = 2.0
            if not shortfall:
                break
            if attempt == 1:
                print(
                    f"  [summary] the draft came back incomplete ({shortfall}) — retrying once",
                    file=sys.stderr,
                )

        if result:
            if trimmed:
                result += (
                    f"\n\n_Note: {trimmed} of the {len(written)} drafted section(s) were too long to "
                    "send in full, so this summary was written from as much of each as would fit._"
                )
            return (
                _with_references(_space_out_scqa(result), cited_papers, markers_by_key, style),
                None,
                shortfall,
            )
        failure = errors[0] if errors else "the request returned nothing"

    return (
        _fallback_summary(
            research_question, written, tensions, no_coverage, cited_papers, markers_by_key, style, variant
        ),
        failure,
        None,
    )


def _cites(text: str, paper: Paper, marker: str, style: str) -> bool:
    """Whether this summary actually cites this paper.

    The exact marker is checked first, but it is not sufficient: prose
    routinely merges two citations into one bracket — "(Hopper, 2025;
    Turing, 2025)" contains neither "(Hopper, 2025)" nor "(Turing, 2025)" as
    a substring — and IEEE runs collapse to "[3], [4]" or "[3]-[5]". So the
    fallback looks for the paper's own signature instead of its punctuation:
    first-author surname close to the year, or the bare number for IEEE.
    """
    if marker and marker in text:
        return True
    if style.lower() == "ieee":
        number = _ieee_number(marker)
        return bool(number) and re.search(rf"\[\s*{number}\s*[\],-]", text) is not None
    surname = paper.authors[0].split()[-1] if paper.authors and paper.authors[0].split() else ""
    if not surname:
        return False
    if paper.year:
        # Anything between the two is an "et al." or a page number, not the
        # start of a different citation — hence no closing bracket allowed.
        return re.search(rf"{re.escape(surname)}[^)\]]{{0,30}}{re.escape(str(paper.year))}", text) is not None
    return surname in text


def _with_references(text: str, cited_papers: List[Paper], markers_by_key: Dict[str, str], style: str) -> str:
    """Append a reference list covering only the papers this summary actually
    cites, so it stands on its own without carrying the review's full list.
    Membership is decided by looking for each paper in the text (see _cites)
    rather than by assuming every paper the review cited made it in."""
    used = [p for p in cited_papers if _cites(text, p, markers_by_key.get(p.key(), ""), style)]
    if not used:
        return text

    if style.lower() == "ieee":
        used.sort(key=lambda p: _ieee_number(markers_by_key.get(p.key(), "")))
    else:
        used.sort(key=reference_sort_key)

    lines = [text, "", "## Sources cited in this summary", ""]
    for i, paper in enumerate(used, start=1):
        ref_number = _ieee_number(markers_by_key.get(paper.key(), "")) or i
        lines.append(format_citation(paper, style, ref_number=ref_number))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_IEEE_NUMBER_RE = re.compile(r"\[(\d+)\]")


def _ieee_number(marker: str) -> int:
    match = _IEEE_NUMBER_RE.search(marker or "")
    return int(match.group(1)) if match else 0


def _fallback_summary(
    research_question: str,
    sections: List[Tuple[str, str]],
    tensions: List[str],
    no_coverage: List[str],
    cited_papers: List[Paper],
    markers_by_key: Dict[str, str],
    style: str,
    variant: str = "summary",
) -> str:
    """A skeleton assembled from what is already known without asking Claude:
    which sub-questions have support, which are contested, which have none.
    It is deliberately not written as prose — a summary that nobody wrote is
    a form to fill in, and presenting it as anything more would be the same
    failure the review's own fallback guards against."""
    covered = [q for q, _ in sections if q not in no_coverage]
    lines = [
        "## What this evidence base looks like" if variant == "detailed" else "## The short version",
        "",
        f"**Situation:** {len(cited_papers)} source(s) were reviewed against the question "
        f"\"{research_question}\".",
        f"**Complication:** {len(tensions)} sub-question(s) are contested between sources and "
        f"{len(no_coverage)} have no supporting literature at all.",
        f"**Question:** {research_question}",
        "**Answer:** _Not written — this skeleton lists what the review found without interpreting "
        "it. Re-run with Claude available for the written summary._",
        "",
        "## What the evidence shows",
        "",
    ]
    if covered:
        lines.append("_Sub-questions with supporting literature, to be turned into cross-cutting findings:_")
        lines.extend(f"- {q}" for q in covered)
    else:
        lines.append("_No sub-question in this review has supporting literature._")
    lines += ["", "## Where the literature disagrees", ""]
    if tensions:
        lines.extend(f"- {q}" for q in tensions)
    else:
        lines.append(
            "_No sub-question shows sources disagreeing with each other. Worth checking whether the "
            "evidence base is genuinely settled or simply one-sided._"
        )
    lines += ["", "## What this means for the thesis", ""]
    if no_coverage:
        lines.append("_Gaps with no literature found — the most direct route to an original contribution:_")
        lines.extend(f"- {q}" for q in no_coverage)
    else:
        lines.append("- Every sub-question has at least one source; look to the contested ones for a contribution.")
    return "\n".join(lines)
