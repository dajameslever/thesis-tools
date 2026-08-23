"""How old is a paper — on its own, and relative to its peers?

Deliberately simple/heuristic (no citation-half-life modeling): a paper is
"older" once it passes a fixed age threshold, and we separately note how far
behind it is from the newest paper in whatever set it's being shown with.
"""

from __future__ import annotations

import datetime as _dt
from typing import List, Optional

DEFAULT_OLD_THRESHOLD_YEARS = 10


def age_years(year: Optional[int], as_of: Optional[int] = None) -> Optional[int]:
    if not year:
        return None
    as_of = as_of if as_of is not None else _dt.date.today().year
    return max(as_of - year, 0)


def newest_year(years: List[Optional[int]]) -> Optional[int]:
    known = [y for y in years if y]
    return max(known) if known else None


def recency_label(
    year: Optional[int],
    newest_year_in_set: Optional[int] = None,
    old_threshold: int = DEFAULT_OLD_THRESHOLD_YEARS,
) -> str:
    """A short human label, e.g. '🆕 Recent (2023)' or '🕰️ Older (2009, 14y old)'."""
    if not year:
        return "❔ Year unknown"

    age = age_years(year)
    is_old = age is not None and age >= old_threshold
    tag = "🕰️ Older" if is_old else "🆕 Recent"

    behind = ""
    if newest_year_in_set and year < newest_year_in_set:
        gap = newest_year_in_set - year
        behind = f", {gap}y behind the newest source found"

    return f"{tag} ({year}, {age}y old{behind})"
