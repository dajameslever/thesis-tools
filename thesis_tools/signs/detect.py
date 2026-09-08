"""Running the two passes over a folder of photos, and turning what comes
back into sightings.

The unit a person cares about is the sign, not the frame. Approaching a 40
roundel at 30mph puts it in fifty consecutive frames; a table with fifty rows
in it has not found fifty signs, and any count taken from that table is
wrong by a factor that changes with the frame rate. So consecutive frames
that agree — same drive, same sign type, no contradicting number, close
together — collapse into one `Sighting`, which keeps the frame that saw it
best and the span it was visible for. The per-frame record survives alongside
it in `frames.csv`, because the collapse is a judgement and a reader has to
be able to check it.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .. import llm
from . import prefilter as _prefilter
from . import vision as _vision
from .frames import Frame, discover_frames
from .prefilter import DEFAULT_MIN_SCORE, PrefilterScore
from .vision import FrameVerdict, SignHit, VerdictCache

# Below this, a sign is the model hedging rather than reporting. Frames keep
# their low-confidence hits in the per-frame table; sightings do not, because
# a sighting is a claim.
DEFAULT_MIN_CONFIDENCE = 0.4

# How far apart two frames can be and still be the same sign. At 30fps this
# is a second and a half — long enough to ride out a sign passing behind a
# lamp post, short enough that two roundels on the same road stay two
# sightings. Measured in original frame positions, so `--every` does not
# quietly change what it means.
DEFAULT_MAX_GAP = 45


@dataclass
class FrameResult:
    """One photo, and everything that was decided about it."""

    frame: Frame
    score: Optional[PrefilterScore] = None
    verdict: Optional[FrameVerdict] = None
    #: Why the photo never reached the model: "below threshold", "unreadable",
    #: "Claude unavailable", "budget reached". Empty when it did.
    skipped: str = ""

    @property
    def examined(self) -> bool:
        return self.verdict is not None

    @property
    def hits(self) -> List[SignHit]:
        return list(self.verdict.signs) if self.verdict else []


@dataclass
class Sighting:
    """One physical sign, seen across one or more consecutive frames."""

    sequence: str
    type: str
    limit_mph: Optional[int] = None
    first_index: int = 0
    last_index: int = 0
    frame_count: int = 1
    confidence: float = 0.0
    best_frame: Optional[Path] = None
    positions: List[str] = field(default_factory=list)
    legible: bool = False
    #: Set when nothing confirmed the sign — the cheap pass flagged the frame
    #: and no model was available to say what it was. Kept in the same table
    #: as confirmed sightings, clearly marked, rather than in a second table
    #: nobody opens.
    unconfirmed: bool = False

    @property
    def is_enforcement(self) -> bool:
        return self.type in _vision.ENFORCEMENT_TYPES

    @property
    def label(self) -> str:
        if self.type == "speed_limit" and self.limit_mph:
            return f"{self.limit_mph} mph limit"
        return self.type.replace("_", " ")


@dataclass
class SignDetectionInputs:
    photos_dir: str
    out_dir: str = "output/speed-signs"
    recursive: bool = True
    every: int = 1
    min_score: float = DEFAULT_MIN_SCORE
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    max_gap: int = DEFAULT_MAX_GAP
    use_llm: bool = True
    llm_model: str = llm.DEFAULT_EXTRACTION_MODEL
    types: Optional[List[str]] = None
    #: Stop after sending this many frames to the model. A ceiling on the
    #: bill, not on the scan: everything is still prefiltered and reported,
    #: the frames past the ceiling are simply marked unconfirmed.
    max_calls: Optional[int] = None
    send_max_dim: int = _vision.SEND_MAX_DIM
    quiet: bool = False


@dataclass
class DetectionRun:
    inputs: SignDetectionInputs
    results: List[FrameResult] = field(default_factory=list)
    sightings: List[Sighting] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    calls: int = 0
    cache_hits: int = 0
    errors: List[str] = field(default_factory=list)
    llm_note: str = ""
    seconds: float = 0.0

    @property
    def frames_scanned(self) -> int:
        return len(self.results)

    @property
    def candidates(self) -> int:
        return sum(1 for r in self.results if r.score and r.score.passes(self.inputs.min_score))

    @property
    def frames_with_signs(self) -> int:
        return sum(1 for r in self.results if r.verdict and r.verdict.has_sign)

    @property
    def enforcement_sightings(self) -> List[Sighting]:
        return [s for s in self.sightings if s.is_enforcement]


def _merges(sighting: Sighting, frame: Frame, hit: SignHit, max_gap: int) -> bool:
    """Is this hit the same physical sign as one already open?

    Same drive and same type, close enough in the footage, and not
    contradicted by a readable number: a 30 followed six frames later by a 40
    is two signs, however close together, while a 30 followed by an
    unreadable roundel is the same sign seen twice.
    """
    if sighting.sequence != frame.sequence or sighting.type != hit.type:
        return False
    if frame.position - sighting.last_index > max_gap:
        return False
    if sighting.limit_mph and hit.limit_mph and sighting.limit_mph != hit.limit_mph:
        return False
    return True


def group_sightings(
    results: List[FrameResult],
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    max_gap: int = DEFAULT_MAX_GAP,
) -> List[Sighting]:
    """Collapse per-frame hits into one entry per physical sign.

    Frames are walked in capture order and each hit either extends the most
    recent open sighting of its type or starts a new one. "Most recent" is
    what makes this a single pass: a sign that has fallen further behind than
    `max_gap` can never be extended again, so nothing needs revisiting.
    """
    open_by_type: Dict[str, Sighting] = {}
    sightings: List[Sighting] = []

    for result in sorted(results, key=lambda r: (r.frame.sequence, r.frame.position)):
        frame = result.frame
        for hit in result.hits:
            if hit.confidence < min_confidence:
                continue
            key = f"{frame.sequence}|{hit.type}"
            current = open_by_type.get(key)
            if current is not None and _merges(current, frame, hit, max_gap):
                current.last_index = frame.position
                current.frame_count += 1
                if hit.limit_mph and not current.limit_mph:
                    current.limit_mph = hit.limit_mph
                if hit.legible:
                    current.legible = True
                if hit.position and hit.position not in current.positions:
                    current.positions.append(hit.position)
                if hit.confidence > current.confidence:
                    current.confidence = hit.confidence
                    current.best_frame = frame.path
                continue
            sighting = Sighting(
                sequence=frame.sequence,
                type=hit.type,
                limit_mph=hit.limit_mph,
                first_index=frame.position,
                last_index=frame.position,
                confidence=hit.confidence,
                best_frame=frame.path,
                positions=[hit.position] if hit.position else [],
                legible=hit.legible,
            )
            open_by_type[key] = sighting
            sightings.append(sighting)

    return sorted(sightings, key=lambda s: (s.sequence, s.first_index))


def unconfirmed_candidates(
    results: List[FrameResult],
    min_score: float,
    max_gap: int = DEFAULT_MAX_GAP,
) -> List[Sighting]:
    """What the cheap pass flagged and nothing ever confirmed.

    Only meaningful when the run had no model to ask — offline, out of
    budget, or the call failed. Grouped the same way so a burst of thirty
    flagged frames reads as one thing to go and look at rather than thirty.
    """
    flagged = [
        r
        for r in results
        if not r.examined and r.score is not None and r.score.passes(min_score)
    ]
    out: List[Sighting] = []
    for result in sorted(flagged, key=lambda r: (r.frame.sequence, r.frame.position)):
        frame = result.frame
        if out and out[-1].sequence == frame.sequence and frame.position - out[-1].last_index <= max_gap:
            out[-1].last_index = frame.position
            out[-1].frame_count += 1
            if result.score.score > out[-1].confidence:
                out[-1].confidence = result.score.score
                out[-1].best_frame = frame.path
            continue
        out.append(
            Sighting(
                sequence=frame.sequence,
                type="unconfirmed_candidate",
                first_index=frame.position,
                last_index=frame.position,
                confidence=result.score.score,
                best_frame=frame.path,
                positions=[result.score.leading_cue or ""],
                unconfirmed=True,
            )
        )
    return out


def run_detection(inputs: SignDetectionInputs) -> DetectionRun:
    """Scan a folder of photos and report the speed signs in it."""
    started = time.time()
    run = DetectionRun(inputs=inputs)
    root = Path(inputs.photos_dir)
    if not root.exists():
        run.errors.append(f"{root} does not exist")
        return run

    frames = discover_frames(root, recursive=inputs.recursive, every=inputs.every)
    if not frames:
        run.errors.append(f"no photos found under {root}")
        return run

    client = None
    if inputs.use_llm:
        issue = llm.availability_issue()
        if issue:
            run.llm_note = f"{issue} — frames were scored locally but nothing was identified"
            if not inputs.quiet:
                print(f"  [signs] {issue}; reporting unconfirmed candidates only", file=sys.stderr)
        else:
            client = llm.get_client(quiet=True)
    else:
        run.llm_note = "Claude was switched off for this run (--no-llm)"

    cache = VerdictCache(Path(inputs.out_dir) / "verdict-cache.json") if client else None

    if not inputs.quiet:
        print(f"Scanning {len(frames):,} photo(s) from {root}...")

    for number, frame in enumerate(frames, start=1):
        score = _prefilter.score_image(frame.path)
        result = FrameResult(frame=frame, score=score)
        run.results.append(result)

        if score is None:
            result.skipped = "unreadable"
            run.errors.append(f"{frame.path} could not be read")
        elif not score.passes(inputs.min_score):
            result.skipped = "below threshold"
        elif client is None:
            result.skipped = "Claude unavailable"
        elif inputs.max_calls is not None and run.calls >= inputs.max_calls:
            result.skipped = "call budget reached"
        else:
            verdict = _vision.identify(
                client,
                frame.path,
                model=inputs.llm_model,
                types=inputs.types,
                cache=cache,
                usage_totals=run.usage,
                max_dim=inputs.send_max_dim,
            )
            result.verdict = verdict
            if verdict.cached:
                run.cache_hits += 1
            else:
                run.calls += 1
            if verdict.error:
                run.errors.append(f"{frame.path.name}: {verdict.error}")

        if not inputs.quiet and (number % 100 == 0 or number == len(frames)):
            print(
                f"  {number:,}/{len(frames):,} scanned — {run.candidates:,} candidate(s), "
                f"{run.calls:,} call(s), {run.cache_hits:,} from cache",
                file=sys.stderr,
            )

    if cache is not None:
        cache.save()

    run.sightings = group_sightings(
        run.results, min_confidence=inputs.min_confidence, max_gap=inputs.max_gap
    )
    run.sightings.extend(
        unconfirmed_candidates(run.results, min_score=inputs.min_score, max_gap=inputs.max_gap)
    )
    run.sightings.sort(key=lambda s: (s.sequence, s.first_index))
    run.seconds = time.time() - started
    return run
