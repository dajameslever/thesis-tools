"""Turning a folder of photos back into the drives they came from.

A frame on its own is not very interesting: one sign is photographed by
twenty or thirty consecutive frames as the car approaches it, and counting
those as thirty sightings would badly overstate how many cameras a route
carries. Everything downstream needs to know which frames came from the same
video and in what order, and that information survives only in the file
names and folder layout — the two shapes people actually export into:

    photos/                        photos/
      drive-a12/                     a12_000123.jpg
        frame_00001.jpg              a12_000124.jpg
        frame_00002.jpg              m25_000001.jpg

Both are handled the same way: the sequence is the containing folder plus the
non-numeric part of the file name, and the frame's position is the number at
the end of its name. A name with no number in it keeps its alphabetical
position, which is the best available guess and is at least stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

# Whatever ffmpeg, VLC, QuickTime or a phone is likely to have written.
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"})

_TRAILING_NUMBER_RE = re.compile(r"(\d+)(?!.*\d)")
_DIGIT_RUN_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Frame:
    """One photo, placed in its drive."""

    path: Path
    sequence: str
    index: int
    #: Position within its sequence once sorted — what "consecutive" means
    #: downstream, and what a frame with no number in its name falls back to.
    position: int = 0

    @property
    def name(self) -> str:
        return self.path.name


def _natural_key(path: Path):
    """Sort frame_2 before frame_10, which plain string sorting does not."""
    parts = _DIGIT_RUN_RE.split(path.name)
    return tuple(int(part) if part.isdigit() else part.lower() for part in parts)


def frame_number(name: str) -> Optional[int]:
    """The number ffmpeg put at the end of the name, if there is one.

    Deliberately the LAST run of digits rather than the first: `a12_000123`
    and `2024-05-01_frame_000123` both mean frame 123, and only the trailing
    run is the counter in both.
    """
    match = _TRAILING_NUMBER_RE.search(Path(name).stem)
    return int(match.group(1)) if match else None


def sequence_key(path: Path, root: Path) -> str:
    """Which drive this frame belongs to.

    The folder below the root, if the export made one per video; otherwise
    the file-name stem with its counter (and any separator before it)
    stripped, which is what a flat export leaves to go on. Falls back to the
    root's own name so a single flat folder of unnumbered photos is still one
    named sequence rather than an empty string.
    """
    try:
        relative = path.resolve().parent.relative_to(root.resolve())
    except ValueError:  # pragma: no cover - only if a caller mixes roots
        relative = Path()
    folder = relative.as_posix().strip(".")
    if folder:
        return folder

    stem = path.stem
    match = _TRAILING_NUMBER_RE.search(stem)
    if match:
        prefix = stem[: match.start()].rstrip("-_. ")
        if prefix:
            return prefix
    return root.resolve().name or "frames"


def discover_frames(
    root: Path,
    recursive: bool = True,
    suffixes: Iterable[str] = IMAGE_SUFFIXES,
    every: int = 1,
) -> List[Frame]:
    """Every photo under `root`, grouped into sequences and put in order.

    `every=n` keeps one frame in n *within each sequence*. Adjacent frames of
    a 30fps dashcam differ by a few centimetres of road, so a sign that is
    legible at all is legible across a dozen of them; sampling one in five
    cuts the work by 80% and, at typical speeds, still gives any sign several
    chances to be seen. It is applied per sequence so a short video does not
    lose its frames to a long one's counting.
    """
    root = Path(root)
    if root.is_file():
        paths = [root]
        root = root.parent
    else:
        pattern = "**/*" if recursive else "*"
        wanted = {s.lower() for s in suffixes}
        paths = [p for p in root.glob(pattern) if p.is_file() and p.suffix.lower() in wanted]

    by_sequence = {}
    for path in sorted(paths, key=lambda p: (p.parent.as_posix().lower(), _natural_key(p))):
        by_sequence.setdefault(sequence_key(path, root), []).append(path)

    step = max(1, int(every or 1))
    frames: List[Frame] = []
    for sequence in sorted(by_sequence):
        for position, path in enumerate(by_sequence[sequence]):
            if position % step:
                continue
            number = frame_number(path.name)
            frames.append(
                Frame(
                    path=path,
                    sequence=sequence,
                    index=number if number is not None else position,
                    position=position,
                )
            )
    return frames


def sequences_of(frames: Sequence[Frame]) -> List[str]:
    """The distinct drives present, in the order they were discovered."""
    seen: List[str] = []
    for frame in frames:
        if frame.sequence not in seen:
            seen.append(frame.sequence)
    return seen
