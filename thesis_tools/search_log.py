"""A running record of every literature search this toolkit has run.

The dissertation bootcamp material recommends keeping a search log — date,
search term, where it was searched, how many results — as one of three
working documents, alongside the reading log and the criticality chart. Its
value is in accumulating: it shows a supervisor (and an examiner, and you in
four months when you have forgotten) that the search was systematic, which
terms had already been tried, and where a promising term came from.

Unlike every other output here, this one is APPEND-ONLY. A search log that
gets replaced on each run is not a log — the whole point is the rows that
came before. That also means it needs none of the versioning in outputs.py:
appending cannot destroy what is already there.

CSV rather than a workbook sheet, for the same reason: Part 2 regenerates
its workbook from scratch on every run, which would wipe the history each
time. A CSV opens in Excel, appends in one line, and survives.
"""

from __future__ import annotations

import csv
import datetime as _dt
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

DEFAULT_SEARCH_LOG_PATH = "output/search-log.csv"

# The four columns the taught log uses, plus one for traceability: which
# run's report a row belongs to, so a row can be followed back to the papers
# it actually produced.
COLUMNS = ["Date", "Search term", "Location searched", "Results", "Run output"]


def append_searches(
    rows: Sequence[Tuple[str, str, int]],
    log_path: Optional[str] = None,
    report_path: Optional[str] = None,
    when: Optional[_dt.datetime] = None,
    quiet: bool = False,
) -> Optional[Path]:
    """Add one row per (search term, source, result count) to the log.

    Returns the log's path, or None if there was nothing to record. Never
    raises: failing to write a log must not lose a search run that already
    happened and already cost API calls.
    """
    if not rows:
        return None

    path = Path(log_path or DEFAULT_SEARCH_LOG_PATH)
    stamp = (when or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(COLUMNS)
            for term, location, results in rows:
                writer.writerow([stamp, term, location, results, report_path or ""])
    except OSError as exc:
        print(f"  [search-log] couldn't write {path} ({exc})", file=sys.stderr)
        return None

    if not quiet:
        print(f"Search log: {len(rows)} row(s) appended to {path}", file=sys.stderr)
    return path


def read_log(log_path: Optional[str] = None) -> List[dict]:
    """Every row recorded so far, oldest first. Returns [] if no log exists
    yet — a first run is not an error."""
    path = Path(log_path or DEFAULT_SEARCH_LOG_PATH)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def terms_already_searched(log_path: Optional[str] = None) -> List[str]:
    """Distinct search terms tried before, most recent first. Knowing what
    has already been run is half of what a search log is for."""
    seen: List[str] = []
    for row in reversed(read_log(log_path)):
        term = (row.get("Search term") or "").strip()
        if term and term not in seen:
            seen.append(term)
    return seen
