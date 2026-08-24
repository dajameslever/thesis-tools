"""Best-effort citation formatting for APA 7, MLA 9, Chicago (author-date),
Harvard, and IEEE.

Important: these are heuristic formatters built from whatever metadata the
free APIs return (which is sometimes incomplete or messily capitalized).
Always double-check the final bibliography against your university's exact
style guide before submitting — treat this as a strong first draft, not a
guarantee of a compliant reference list.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .sources.base import Paper

STYLES = ["apa", "mla", "chicago", "harvard", "ieee"]


def _split_name(full_name: str) -> tuple[str, str]:
    """Best-effort split of "Given Middle Family" -> (given, family).

    Sources vary in how they format names; this assumes the common
    "given(s) family" order used by Semantic Scholar/OpenAlex/arXiv, and
    Crossref's given+family join (see sources/crossref.py).
    """
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _initials(given: str) -> str:
    return " ".join(f"{p[0].upper()}." for p in given.split() if p)


def _apa_author(full_name: str) -> str:
    given, family = _split_name(full_name)
    return f"{family}, {_initials(given)}" if given else family


def _mla_author(full_name: str, first: bool) -> str:
    given, family = _split_name(full_name)
    if not given:
        return family
    return f"{family}, {given}" if first else f"{given} {family}"


def _ieee_author(full_name: str) -> str:
    given, family = _split_name(full_name)
    return f"{_initials(given)} {family}" if given else family


def _harvard_author(full_name: str) -> str:
    given, family = _split_name(full_name)
    return f"{family}, {_initials(given)}" if given else family


def _join_authors_apa_harvard(authors: List[str], style_author_fn) -> str:
    formatted = [style_author_fn(a) for a in authors if a]
    if not formatted:
        return "n.a."
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) <= 20:
        return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"
    # APA 7 style for 21+ authors: list the first 19, an ellipsis, then the last.
    # Uses a single ellipsis character (not three periods) so it survives the
    # double-period cleanup in format_citation() unscathed.
    return ", ".join(formatted[:19]) + ", … " + formatted[-1]


def _join_authors_ieee(authors: List[str]) -> str:
    formatted = [_ieee_author(a) for a in authors if a]
    if not formatted:
        return "n.a."
    if len(formatted) == 1:
        return formatted[0]
    return ", ".join(formatted[:-1]) + f", and {formatted[-1]}"


def _join_authors_mla(authors: List[str]) -> str:
    names = [a for a in authors if a]
    if not names:
        return "n.a."
    if len(names) == 1:
        return _mla_author(names[0], first=True)
    if len(names) == 2:
        return f"{_mla_author(names[0], first=True)}, and {_mla_author(names[1], first=False)}"
    return f"{_mla_author(names[0], first=True)}, et al."


def _year(paper: Paper) -> str:
    return str(paper.year) if paper.year else "n.d."


def _vol_issue(paper: Paper) -> str:
    vol_issue = paper.volume or ""
    if paper.issue:
        vol_issue += f"({paper.issue})"
    return vol_issue


def format_apa(paper: Paper) -> str:
    authors = _join_authors_apa_harvard(paper.authors, _apa_author)
    year = _year(paper)
    title = paper.title.rstrip(".")

    parts = [p for p in [paper.venue, _vol_issue(paper), paper.pages] if p]
    tail = f" {', '.join(parts)}." if parts else ""

    link = f" https://doi.org/{paper.doi}" if paper.doi else (f" {paper.url}" if paper.url else "")
    return f"{authors} ({year}). {title}.{tail}{link}".strip()


def format_harvard(paper: Paper) -> str:
    authors = _join_authors_apa_harvard(paper.authors, _harvard_author)
    year = _year(paper)
    title = paper.title.rstrip(".")

    pages = f"pp.{paper.pages}" if paper.pages else ""
    parts = [p for p in [paper.venue, _vol_issue(paper), pages] if p]
    tail = f" {', '.join(parts)}." if parts else ""

    link = f" doi:{paper.doi}" if paper.doi else (f" Available at: {paper.url}" if paper.url else "")
    return f"{authors}, {year}. {title}.{tail}{link}".strip()


def format_mla(paper: Paper) -> str:
    authors = _join_authors_mla(paper.authors)
    title = paper.title.rstrip(".")
    parts = []
    if paper.venue:
        parts.append(paper.venue)
    if paper.volume:
        parts.append(f"vol. {paper.volume}")
    if paper.issue:
        parts.append(f"no. {paper.issue}")
    if paper.year:
        parts.append(str(paper.year))
    if paper.pages:
        parts.append(f"pp. {paper.pages}")
    tail = f" {', '.join(parts)}." if parts else ""
    return f'{authors}. "{title}."{tail}'.strip()


def format_chicago(paper: Paper) -> str:
    authors = _join_authors_apa_harvard(paper.authors, _apa_author)
    year = _year(paper)
    title = paper.title.rstrip(".")
    vol_issue = paper.volume or ""
    if paper.issue:
        vol_issue = f"{vol_issue}, no. {paper.issue}" if vol_issue else f"no. {paper.issue}"
    parts = [p for p in [paper.venue, vol_issue] if p]
    tail = " ".join(parts)
    if paper.pages:
        tail = f"{tail}: {paper.pages}" if tail else f"pp. {paper.pages}"
    result = f'{authors}. {year}. "{title}."'
    if tail:
        result += f" {tail}."
    if paper.doi:
        result += f" https://doi.org/{paper.doi}"
    elif paper.url:
        result += f" {paper.url}"
    return result.strip()


def format_ieee(paper: Paper, ref_number: Optional[int] = None) -> str:
    authors = _join_authors_ieee(paper.authors)
    title = paper.title.rstrip(".")
    venue = f" {paper.venue}," if paper.venue else ""
    vol = f" vol. {paper.volume}," if paper.volume else ""
    issue = f" no. {paper.issue}," if paper.issue else ""
    pages = f" pp. {paper.pages}," if paper.pages else ""
    year = f" {_year(paper)}." if paper.year else " n.d."
    prefix = f"[{ref_number}] " if ref_number is not None else ""
    return f'{prefix}{authors}, "{title},"{venue}{vol}{issue}{pages}{year}'.strip()


_FORMATTERS = {
    "apa": format_apa,
    "mla": format_mla,
    "chicago": format_chicago,
    "harvard": format_harvard,
    "ieee": format_ieee,
}


_DOUBLE_PERIOD_RE = re.compile(r"\.{2,}")


def _clean(text: str) -> str:
    """Collapse the run of adjacent periods that shows up when a metadata
    field (venue/volume/pages/etc.) is missing and two formatting fragments
    that each assumed they'd be sentence-final end up back to back."""
    return _DOUBLE_PERIOD_RE.sub(".", text)


def format_citation(paper: Paper, style: str, ref_number: Optional[int] = None) -> str:
    style = style.lower()
    if style not in _FORMATTERS:
        raise ValueError(f"Unknown citation style '{style}'. Choose from: {', '.join(STYLES)}")
    if style == "ieee":
        return _clean(format_ieee(paper, ref_number=ref_number))
    return _clean(_FORMATTERS[style](paper))


def _lastname(full_name: str) -> str:
    return _split_name(full_name)[1] or "n.a."


def reference_sort_key(paper: Paper) -> tuple:
    """Sort key for an alphabetical reference list.

    Every author-date style here (APA, MLA, Chicago, Harvard) orders the
    bibliography by the first author's SURNAME. Names are stored
    "Given Family", so sorting on the raw author string orders by first
    name — putting "Ada Lovelace" before "Grace Hopper". Falls back to the
    title for a paper with no authors, which is also the convention.
    """
    if paper.authors and paper.authors[0]:
        return (0, _lastname(paper.authors[0]).lower(), str(paper.year or ""))
    return (1, (paper.title or "").lower(), "")


def _author_group_for_in_text(paper: Paper) -> str:
    """'Smith', 'Smith & Jones', or 'Smith et al.' — the shared author-
    grouping convention every parenthetical (non-IEEE) style below uses,
    differing only in punctuation/year placement around it."""
    names = [_lastname(a) for a in paper.authors if a]
    if not names:
        return "n.a."
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{names[0]} et al."


def in_text_citation(paper: Paper, style: str, ref_number: Optional[int] = None) -> str:
    """The parenthetical marker to actually place inline in running prose —
    distinct from format_citation()'s full reference-list entry. Used by
    Part 3's literature review so a drafted paragraph's in-text citations
    match whatever style the student configured, not one style hardcoded
    regardless of --style:
      * apa / harvard: "(Smith, 2020)" / "(Smith & Jones, 2020)" /
        "(Smith et al., 2020)" — both are parenthetical author-date styles
        with a comma before the year.
      * chicago (author-date): the same author grouping, but no comma
        before the year — "(Smith 2020)".
      * mla: no year at all in-text (MLA cites by author, and page number
        when known) — "(Smith)" or "(Smith 15)".
      * ieee: a numbered bracket, "[3]" — ref_number must be supplied by
        the caller (IEEE numbers reflect order of first citation, which
        only the caller tracking a whole document can know).
    """
    style = style.lower()
    if style not in _FORMATTERS:
        raise ValueError(f"Unknown citation style '{style}'. Choose from: {', '.join(STYLES)}")

    if style == "ieee":
        return f"[{ref_number}]" if ref_number is not None else "[?]"

    year = _year(paper)
    authors = _author_group_for_in_text(paper)

    if style == "mla":
        page = (paper.pages or "").split("-")[0].strip()
        return f"({authors} {page})" if page else f"({authors})"
    if style == "chicago":
        return f"({authors} {year})"
    # apa / harvard
    return f"({authors}, {year})"
