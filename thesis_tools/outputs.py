"""Never overwrite a deliverable you have already produced.

Some outputs are timestamped and so accumulate naturally (Part 1's report,
Part 3's draft). Others are written to a fixed, predictable name — the
library visualization, the Excel matrix, the library report — because that
name is what a bookmark, a browser tab and the page's own download link all
point at. Those used to be silently replaced on every run, which meant
re-running to change one flag destroyed the version you were comparing
against.

Rotating solves both halves: the canonical path stays exactly where it was,
and the previous file is moved into a `previous/` folder beside it, stamped
with its own modification time (when it was produced, not when it was
displaced). Nothing this toolkit produces is ever lost to a re-run.

Applies to reports and deliverables only. The index, the stance cache, the
extracted `.txt` files and the downloaded PDFs are state and caches, not
outputs — they are meant to be rewritten in place, and archiving every
version of them would bury the actual history in noise.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import sys
from pathlib import Path
from typing import Optional

PREVIOUS_DIR_NAME = "previous"


def _stamp(path: Path) -> str:
    """The file's own modification time. Naming the archived copy by when it
    was WRITTEN, rather than by when it was pushed aside, is what makes the
    folder readable as a history: the timestamps line up with the runs that
    produced them."""
    try:
        when = _dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        when = _dt.datetime.now()
    return when.strftime("%Y%m%d-%H%M%S")


def archive_existing(path: Path, quiet: bool = False) -> Optional[Path]:
    """Move an existing file at `path` into `previous/` beside it, so the
    caller can write to `path` without destroying what was there.

    Returns where the old file went, or None if there was nothing to keep.
    Call this immediately before writing — it deliberately does not do the
    writing itself, so it works the same for text written directly and for
    a file some library (openpyxl, say) insists on opening by path.

    A failure here is reported and swallowed: refusing to produce this run's
    output because last run's could not be filed away would be a worse
    outcome than losing the old copy.
    """
    path = Path(path)
    if not path.is_file():
        return None

    archive_dir = path.parent / PREVIOUS_DIR_NAME
    target = archive_dir / f"{path.stem}-{_stamp(path)}{path.suffix}"
    # A second run inside the same second would otherwise land on the same
    # name and lose the first one — the exact thing this function exists to
    # prevent.
    counter = 2
    while target.exists():
        target = archive_dir / f"{path.stem}-{_stamp(path)}-{counter}{path.suffix}"
        counter += 1

    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    except OSError as exc:
        print(f"  [outputs] couldn't keep the previous {path.name} ({exc})", file=sys.stderr)
        return None

    if not quiet:
        print(f"  previous {path.name} kept as {target}", file=sys.stderr)
    return target


def write_output(path: Path, content: str, quiet: bool = False) -> Optional[Path]:
    """Write text to `path`, keeping whatever was there. Returns where the
    previous version went, or None."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    archived = archive_existing(path, quiet=quiet)
    path.write_text(content, encoding="utf-8")
    return archived
