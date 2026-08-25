"""Two kinds of file, two different rules.

**Living views** — `library/visualization.html`, `library/literature_matrix.xlsx`,
`library/library.md`. These describe your library *as it stands right now*.
Re-running after adding papers is meant to replace them: an old snapshot of
a library you have since changed is not history, it is a stale picture of
something that no longer exists. They are written straight over, and their
fixed names are what your bookmark, your open browser tab and the page's own
download link all point at.

**Documents** — everything `literature-review` produces (the review, the
executive summary, the detailed summary, and the HTML beside each) plus Part
1's report. These are things you made at a moment in time, and you will want
to compare what today's draft says against last week's. They are kept
wherever they are written, not only under `output/` — a document pointed
somewhere else is still a document.

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

Which rule applies is decided by WHERE the file lands, not by which command
wrote it. `output/` means kept — so pointing the visualization at
`output/visualization.html` versions it, exactly as it would any other file
there, instead of quietly overwriting it because a view happened to write
it. A living view is only living in its own folder.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import sys
from pathlib import Path
from typing import Optional

PREVIOUS_DIR_NAME = "previous"

# Landing anywhere under a folder with this name means "keep every version",
# whichever command did the writing.
KEPT_DIR_NAME = "output"


def is_kept_location(path: Path) -> bool:
    """Whether files here are versioned rather than overwritten.

    Deliberately about the destination, not the caller. "Anything in output
    is kept" is a rule a person can hold in their head and predict from the
    path alone; "the review is kept and the visualization is not" is a rule
    they have to remember per command, and it breaks the moment they point
    one command at the other's folder.
    """
    return any(parent.name == KEPT_DIR_NAME for parent in Path(path).resolve().parents)


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


def archive_if_kept(path: Path, quiet: bool = False) -> Optional[Path]:
    """Keep the existing file only if it sits somewhere versions are kept.

    For writers that cannot go through write_output() because a library
    insists on opening the path itself (openpyxl saving a workbook).
    """
    return archive_existing(path, quiet=quiet) if is_kept_location(path) else None


def write_output(path: Path, content: str, quiet: bool = False) -> Optional[Path]:
    """Write a document, keeping whatever was there. Returns where the
    previous version went, or None."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    archived = archive_existing(path, quiet=quiet)
    path.write_text(content, encoding="utf-8")
    return archived


def write_view(path: Path, content: str, quiet: bool = False) -> Optional[Path]:
    """Write a living view — overwritten in place, because it describes the
    library as it stands right now and an old copy is a stale picture rather
    than history.

    Unless it lands under `output/`, where the rule is the destination's, not
    the writer's: put a view there and it is kept like everything else there.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    archived = archive_if_kept(path, quiet=quiet)
    path.write_text(content, encoding="utf-8")
    return archived
