"""Two kinds of file, two different rules.

**Living views** — `library/visualization.html`, `library/literature_matrix.xlsx`,
`library/library.md`. These describe your library *as it stands right now*.
Re-running after adding papers is meant to replace them: an old snapshot of
a library you have since changed is not history, it is a stale picture of
something that no longer exists. They are written straight over, and their
fixed names are what your bookmark, your open browser tab and the page's own
download link all point at.

**Outputs** — everything under `output/`: Part 1's report, Part 3's review,
executive summary and detailed summary, and the HTML beside each. These are
documents you produced at a moment in time, and you will want to compare
what today's draft says against last week's. They are kept.

Most already carry a timestamp in their name and so accumulate on their own.
The one case that needs help is an explicit `-o path` reused across runs:
that names one fixed file, and writing it again would destroy the earlier
version. `write_output()` covers it by moving the existing file into a
`previous/` folder beside it, stamped with its own modification time — when
it was produced, not when it was displaced — so the folder reads as a
history of runs. The path you named keeps pointing at the newest.

Neither rule applies to state and caches: `index.json`, the stance cache,
the extracted `.txt` files, downloaded PDFs. Those are meant to be rewritten
in place, and versioning every one of them would bury the real history in
noise.
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
