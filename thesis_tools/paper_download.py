"""Download open-access PDFs for found papers and extract their text.

Opt-in (costs bandwidth and time) — never follows a paywalled or scraped
link, only a `pdf_url` that a source API itself reported as an open-access
copy (arXiv's own PDF endpoint, Semantic Scholar's openAccessPdf, OpenAlex's
best_oa_location). A paper with no known open-access copy is silently
skipped, not substituted with anything else.

Saves two files per paper under `dest_dir` (default: "processed"):
  - pdfs/<slug>.pdf   the raw downloaded file, untouched
  - text/<slug>.txt   the extracted excerpt (page-marked, via extract_pdf)

and sets `paper.full_text_excerpt` from the extracted text, so downstream
consumers (e.g. Part 3's literature review) can ground direct quotations in
text actually seen rather than an abstract alone.

Failures (404, timeout, oversized response, a landing page instead of a
PDF, a corrupt file) are skipped with a one-line stderr note — one bad
download never aborts the run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import requests

from .library.extract import extract_pdf
from .sources.base import Paper, slug_for_paper

DOWNLOAD_TIMEOUT = 30
MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB — a sane cap for a single paper


def download_and_extract(paper: Paper, dest_dir: str = "processed") -> Optional[str]:
    """Download `paper.pdf_url` (if any) and extract its text.

    Saves the raw PDF and the extracted excerpt under `dest_dir`, and sets
    `paper.full_text_excerpt` on success. Returns the path to the saved
    excerpt, or None if there was nothing to download or it failed.
    """
    if not paper.pdf_url:
        return None

    pdf_dir = Path(dest_dir) / "pdfs"
    text_dir = Path(dest_dir) / "text"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    slug = slug_for_paper(paper)
    pdf_path = pdf_dir / f"{slug}.pdf"
    text_path = text_dir / f"{slug}.txt"

    try:
        resp = requests.get(paper.pdf_url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [download] failed for {paper.title!r} ({exc})", file=sys.stderr)
        return None

    data = resp.content
    if len(data) > MAX_PDF_BYTES:
        print(f"  [download] skipped {paper.title!r} (too large: {len(data)} bytes)", file=sys.stderr)
        return None
    if not data.startswith(b"%PDF"):
        print(f"  [download] skipped {paper.title!r} (response wasn't a PDF — likely a landing page)", file=sys.stderr)
        return None

    pdf_path.write_bytes(data)

    try:
        extracted = extract_pdf(pdf_path)
    except Exception as exc:
        print(f"  [download] downloaded but couldn't extract text for {paper.title!r} ({exc})", file=sys.stderr)
        return None

    text_path.write_text(extracted.text, encoding="utf-8")
    paper.full_text_excerpt = extracted.text
    return str(text_path)


def download_papers(papers: List[Paper], dest_dir: str = "processed") -> int:
    """Download+extract every paper in `papers` that has a pdf_url.

    Returns how many succeeded. Papers without a known open-access copy are
    silently skipped — not every paper has one.
    """
    count = 0
    for paper in papers:
        if download_and_extract(paper, dest_dir=dest_dir):
            count += 1
    return count
