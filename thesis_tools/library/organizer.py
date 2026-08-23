"""Optional "organize" step: copy (never move) indexed files into a folder
laid out as Author_Year_Title.ext. Originals are never touched — this only
ever writes new copies, so it's fully safe to try and easy to undo (just
delete the destination folder).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Tuple

from .index_store import LibraryEntry

_UNSAFE_CHARS_RE = re.compile(r"[^\w\s-]")
_WHITESPACE_RE = re.compile(r"\s+")


def _slug_component(text: str, max_len: int = 60) -> str:
    text = _UNSAFE_CHARS_RE.sub("", text or "")
    text = _WHITESPACE_RE.sub("_", text.strip())
    return text[:max_len].strip("_") or "untitled"


def organized_filename(entry: LibraryEntry) -> str:
    paper = entry.paper
    author = paper.authors[0].split()[-1] if paper.authors and paper.authors[0].split() else "Unknown"
    year = paper.year if paper.year else "nd"
    title = _slug_component(paper.title)
    ext = Path(entry.file_path).suffix
    return f"{_slug_component(author)}_{year}_{title}{ext}"


def organize_entries(entries: List[LibraryEntry], destination: Path, dry_run: bool = False) -> List[Tuple[str, str]]:
    """Copy each entry's source file into `destination` with a clean name.

    Returns a list of (source_path, destination_path) for every file
    actually copied (or that would be copied, if dry_run). Skips entries
    whose source file no longer exists.
    """
    destination = Path(destination)
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    results: List[Tuple[str, str]] = []
    used_names = set()

    for entry in entries:
        source = Path(entry.file_path)
        if not source.exists():
            continue

        name = organized_filename(entry)
        stem, ext = Path(name).stem, Path(name).suffix
        candidate = name
        suffix_n = 2
        while candidate in used_names or (destination / candidate).exists():
            candidate = f"{stem}_{suffix_n}{ext}"
            suffix_n += 1
        used_names.add(candidate)

        dest_path = destination / candidate
        if not dry_run:
            shutil.copy2(source, dest_path)
        results.append((str(source), str(dest_path)))

    return results
