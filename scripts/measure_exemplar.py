#!/usr/bin/env python3
"""Measure a dissertation's literature review, to calibrate this toolkit's
drafting defaults against real examples rather than against taste.

Every number in the README's quoting guidance came from running this over a
published exemplar. Run it on your own examples and the defaults can be
argued with using evidence:

    python scripts/measure_exemplar.py thesis.pdf --pages 11-19
    python scripts/measure_exemplar.py thesis.pdf --find "Literature Review"

Most exemplars never arrive as a PDF you can hand to a script — they are
read in a browser, or come one file at a time. So it also takes the text
itself: paste the chapter on stdin, or point it at a .txt saved from
anywhere.

    python scripts/measure_exemplar.py chapter.txt --total-words 11955
    pbpaste | python scripts/measure_exemplar.py --total-words 11955
    python scripts/measure_exemplar.py            # paste, then Ctrl-D

Pasted text counts as one page, so --pages needs a PDF (or text that kept
its form feeds); paste only the section instead. --find works on either.

What it reports, and why each one:

  * Section length, and its share of the dissertation — a literature review
    that is 5% of the whole is a different animal from one that is 30%.
  * Quotation SHARE and quotation SIZE, separately. Across the exemplars
    measured so far the share varies fourfold (0.9%-3.5%) while the size
    barely moves (median five words, none over nine). Size is the constraint
    worth copying; share is not.
  * Citation density — how often a claim is attributed at all.
  * Paragraph length, since a review written in 200-word paragraphs is
    listing sources and one written in 80-word paragraphs is arguing.

A phrase the dissertation repeats three or more times is counted as its own
vocabulary — a named concept — and not as a quotation. Without that,
'right to the city' alone put one exemplar's quotation rate at 7.8% instead
of the real 3.5%.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from typing import List, Optional, Sequence, Tuple

MIN_QUOTATION_WORDS = 4
RECURRING_TERM_USES = 3

_QUOTE_RE = re.compile(r"[“\"‘']([^“”\"‘’']{2,400}?)[”\"’']")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_CITATION_RE = re.compile(r"\([A-Za-z][A-Za-z\-’'. ]+,?\s*(?:et al\.?,?)?\s*\d{4}")
_PAGE_NUMBER_LINE_RE = re.compile(r"\n\s*\d{1,3}\s*\n")


def _pdf_pages(path: str) -> List[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("This needs pypdf: pip install pypdf")
    return [(page.extract_text() or "") for page in PdfReader(path).pages]


def _text_pages(text: str) -> List[str]:
    """Text copied out of a PDF often keeps its form feeds; text pasted from
    a browser never does. Either way this is the whole of what we were given,
    so one page is the honest answer when there are no breaks to find."""
    return text.split("\f") if "\f" in text else [text]


def _read_source(source: Optional[str]) -> Tuple[List[str], str]:
    """Pages, and a label for the report, from a PDF, a text file, or stdin."""
    if source is None or source == "-":
        if sys.stdin.isatty():
            print("Paste the section, then Ctrl-D (Ctrl-Z then Enter on Windows).", file=sys.stderr)
        text = sys.stdin.read()
        if not text.strip():
            sys.exit("Nothing arrived on stdin. Paste the section, or pass a file.")
        return _text_pages(text), "pasted text"
    if source.lower().endswith(".pdf"):
        return _pdf_pages(source), source
    try:
        with open(source, encoding="utf-8", errors="replace") as handle:
            return _text_pages(handle.read()), source
    except OSError as exc:
        sys.exit(f"Couldn't read {source}: {exc}")


def _parse_range(spec: str, total: int) -> Sequence[int]:
    """"11-19" or "11" as 1-based printed page numbers -> 0-based indices."""
    start, _, end = spec.partition("-")
    first = int(start)
    last = int(end) if end else first
    if not 1 <= first <= last <= total:
        sys.exit(f"--pages {spec} is outside this document's 1-{total}")
    return range(first - 1, last)


_PEER_HEADING_RE = re.compile(r"(?im)^\s*(?:chapter\s+\w+|\d+\.?\s+[A-Z])")


def _heading_re(heading: str) -> re.Pattern:
    return re.compile(rf"(?im)^\s*(?:\d[.\d]*\s*)?{re.escape(heading)}\b")


def _missing(heading: str) -> None:
    sys.exit(f"Couldn't find a heading matching {heading!r}. Pass just the section instead.")


def _find_section(pages: List[str], heading: str) -> Sequence[int]:
    """Pages from the one where `heading` appears as a heading, up to the
    next heading that looks like a peer of it."""
    pattern = _heading_re(heading)
    starts = [i for i, text in enumerate(pages) if pattern.search(text)]
    if not starts:
        _missing(heading)
    # The last match, not the first: the first is usually the contents page.
    start = starts[-1]
    for i in range(start + 1, len(pages)):
        if _PEER_HEADING_RE.search(pages[i]):
            return range(start, i)
    return range(start, len(pages))


def _slice_section(text: str, heading: str) -> str:
    """The same search inside one unbroken blob of text, which is what pasted
    text is. Page granularity would take the whole paste."""
    starts = [match.start() for match in _heading_re(heading).finditer(text)]
    if not starts:
        _missing(heading)
    body = text[starts[-1]:]
    after_heading = body.find("\n") + 1 or len(body)
    peer = _PEER_HEADING_RE.search(body, after_heading)
    return body[: peer.start()] if peer else body


def measure(text: str) -> dict:
    body = _PAGE_NUMBER_LINE_RE.sub("\n", text)
    words = _WORD_RE.findall(body)
    if not words:
        sys.exit("No words in that — a scanned PDF, or an empty paste.")

    spans = [re.sub(r"\s+", " ", s).strip() for s in _QUOTE_RE.findall(body)]
    uses = Counter(s.lower() for s in spans)
    terms = {s for s, n in uses.items() if n >= RECURRING_TERM_USES}
    quotes = [s for s in spans if s.lower() not in terms and len(s.split()) >= MIN_QUOTATION_WORDS]
    lengths = sorted(len(q.split()) for q in quotes)
    paragraphs = [p for p in re.split(r"\n(?=\s*[A-Z])", body) if len(p.split()) > 25]

    return {
        "words": len(words),
        "quotations": quotes,
        "quoted_words": sum(lengths),
        "median_quotation": lengths[len(lengths) // 2] if lengths else 0,
        "longest_quotation": lengths[-1] if lengths else 0,
        "recurring_terms": sorted(terms),
        "citations": len(_CITATION_RE.findall(body)),
        "paragraphs": len(paragraphs),
        "median_paragraph": (
            sorted(len(p.split()) for p in paragraphs)[len(paragraphs) // 2] if paragraphs else 0
        ),
    }


def report(label: str, stats: dict, dissertation_words: Optional[int], show_quotes: bool) -> None:
    words = stats["words"]
    print(f"\n{label}")
    print(f"  section length        : {words:,} words")
    if dissertation_words:
        print(f"  share of dissertation : {words / dissertation_words * 100:.0f}%")
    share = stats["quoted_words"] / words * 100
    print(f"  quotations            : {len(stats['quotations'])} totalling {stats['quoted_words']} words = {share:.1f}%")
    if stats["quotations"]:
        print(f"  quotation size        : median {stats['median_quotation']}w, longest {stats['longest_quotation']}w")
    print(f"  citations             : ~{stats['citations']} = one per {words // max(stats['citations'], 1)} words")
    print(f"  paragraphs            : {stats['paragraphs']}, median {stats['median_paragraph']} words")
    if stats["recurring_terms"]:
        shown = ", ".join(f"'{t}'" for t in stats["recurring_terms"][:5])
        print(f"  counted as vocabulary : {len(stats['recurring_terms'])} recurring term(s) — {shown}")
    if show_quotes and stats["quotations"]:
        print("\n  every quotation found:")
        for q in stats["quotations"]:
            print(f"    ({len(q.split()):2}w) {q[:100]}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "source",
        nargs="?",
        help="A .pdf, or a text file of the section. Omit it (or pass -) to paste on stdin.",
    )
    parser.add_argument("--pages", help="Printed page range of the section, e.g. 11-19 (PDFs)")
    parser.add_argument("--find", help="Find the section by heading, e.g. 'Literature Review'")
    parser.add_argument("--total-words", type=int, help="The dissertation's stated word count, for the share")
    parser.add_argument("--show-quotes", action="store_true", help="Print every quotation found")
    args = parser.parse_args(argv)

    pages, label = _read_source(args.source)
    paged = len(pages) > 1
    if args.pages:
        if not paged:
            sys.exit(
                f"--pages needs a document with page breaks, and {label} has none. "
                "Paste just the section instead, or use --find."
            )
        span = _parse_range(args.pages, len(pages))
    elif args.find and paged:
        span = _find_section(pages, args.find)
        print(f"Found {args.find!r} on pages {span[0] + 1}-{span[-1] + 1}", file=sys.stderr)
    else:
        span = range(len(pages))

    text = "\n".join(pages[i] for i in span)
    if paged:
        label = f"{label} (pages {span[0] + 1}-{span[-1] + 1})"
    elif args.find:
        text = _slice_section(text, args.find)
        label = f"{label} ({args.find})"
    report(label, measure(text), args.total_words, args.show_quotes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
