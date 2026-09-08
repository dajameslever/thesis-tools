"""The free pass: which frames are even worth looking at properly.

A speed sign is a small, saturated, high-contrast object in a scene that is
mostly road, sky and hedge. That is not enough to identify one — plenty of
red things by a road are not signs — but it is more than enough to throw away
the frames that cannot possibly contain one, and on a drive that is most of
them. Everything here is arithmetic on pixels: no model, no network, no cost.

Three cues, because "any speed sign" spans three different appearances:

  * **red** — the ring of a speed limit roundel, the red border and camera
    symbol used on enforcement warning signs.
  * **yellow** — the housings themselves (Gatso, Truvelo, average-speed
    units, enforcement vans) and the yellow-backed signs often mounted with
    them.
  * **sign face** — a bright, colourless plate carrying dark legend. This is
    what an average-speed-check sign or a camera warning sign looks like when
    the colour has been washed out by distance or weather.

Each cue is measured per *cell* rather than over the whole frame, because
concentration is the whole signal. Two per cent of a frame being red means a
sign if it is one patch and means brake lights, a sunset or a red car if it
is scattered. The peak cell density is what is scored; the frame's overall
red fraction is not.

The thresholds below are set to favour recall: a frame wrongly kept costs one
cheap Claude call, a frame wrongly dropped is a camera that never appears in
the results at all. `--min-score` moves the line for a particular set of
footage, and `frames.csv` records every frame's score so it can be moved on
evidence rather than by feel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Frames are scored on a downscale, not at capture resolution. A 1080p frame
# is two million pixels of mostly tarmac; 200px across keeps a roadside sign
# several pixels wide — enough for the cell densities below to mean something
# — while making the pass fast enough to run over a whole drive.
WORK_WIDTH = 200

# Cells are a fixed number of pixels rather than a fixed grid, so a portrait
# frame and a landscape one get the same physical sensitivity. Density is then
# read over 2x2 blocks of cells sliding one cell at a time, for two reasons: a
# window twice the cell size averages away the scatter that makes a random
# sprinkle of red pixels look locally dense, and a half-window stride stops a
# sign that straddles a cell boundary from being split in half and lost.
CELL_PX = 6
WINDOW_CELLS = 2

# The bottom of a dashcam frame is bonnet, wiper and dashboard reflection —
# never a sign, and often a strong red or bright reflection that would score.
BONNET_FRACTION = 0.16

# A cell must be at least this dense in a cue before the cue counts at all.
# Below it, a "patch" is a handful of stray pixels.
RED_GATE = 0.10
YELLOW_GATE = 0.12
BRIGHT_GATE = 0.22
DARK_GATE = 0.06

# The density at which a cue is considered as strong as it usefully gets, so
# scores land on a 0–1 scale that means the same thing between cues.
RED_FULL = 0.45
YELLOW_FULL = 0.55
BRIGHT_FULL = 0.55

# Red is the most specific of the three and the sign face the least, so an
# equally dense patch is worth less when it is only brightness and contrast.
CUE_WEIGHTS = {"red": 1.0, "yellow": 0.82, "sign_face": 0.66}

# Chosen so a roundel or housing large enough to read survives, and so does a
# washed-out sign face, while empty road does not. See the module docstring
# on why this errs towards keeping frames.
DEFAULT_MIN_SCORE = 0.18


@dataclass
class PrefilterScore:
    """What the cheap pass thought, and why."""

    score: float
    cues: Dict[str, float] = field(default_factory=dict)
    #: Where in the frame the strongest cue sat, as fractions of width and
    #: height. Not used for the decision — it is there so a person auditing a
    #: false positive can see the tool was looking at the sky.
    peak: Optional[Tuple[float, float]] = None

    def passes(self, min_score: float = DEFAULT_MIN_SCORE) -> bool:
        return self.score >= min_score

    @property
    def leading_cue(self) -> Optional[str]:
        if not self.cues:
            return None
        return max(self.cues, key=lambda name: self.cues[name])

    def describe(self) -> str:
        if not self.score:
            return "nothing sign-like"
        parts = ", ".join(f"{name} {value:.2f}" for name, value in sorted(self.cues.items(), key=lambda kv: -kv[1]) if value)
        return parts or "nothing sign-like"


def _is_sign_red(r: int, g: int, b: int) -> bool:
    """Sign red, not brake-light red or brick red.

    The ratio tests are what separate a printed red from a red-ish surface:
    signal red is much stronger in red than in either other channel at once,
    whatever the exposure. The floor on `r` keeps deep shadow out, since at
    very low light the ratios are satisfied by noise.
    """
    return r >= 80 and r >= int(1.6 * g) and r >= int(1.6 * b)


def _is_sign_yellow(r: int, g: int, b: int) -> bool:
    """The yellow of a camera housing or a temporary sign face: red and green
    both high and close together, blue well below both."""
    if r < 110 or g < 90:
        return False
    if b > int(0.62 * min(r, g)):
        return False
    return abs(r - g) <= int(0.45 * r)


def _is_bright_neutral(r: int, g: int, b: int) -> bool:
    """White or near-white plate: bright in every channel and barely
    coloured."""
    return min(r, g, b) >= 140 and (max(r, g, b) - min(r, g, b)) <= 45


def _is_dark(r: int, g: int, b: int) -> bool:
    """Dark enough to be legend or a camera pictogram against a plate."""
    return max(r, g, b) <= 95


def score_pixels(pixels: Sequence[Tuple[int, int, int]], width: int, height: int) -> PrefilterScore:
    """Score an already-downscaled RGB frame.

    Kept separate from image loading so the scoring can be tested against
    exact pixels — the thresholds above are the whole behaviour of this
    module, and a test that has to encode a JPEG first cannot say precisely
    what they do.
    """
    if width <= 0 or height <= 0 or not pixels:
        return PrefilterScore(score=0.0)

    usable_rows = max(1, int(height * (1.0 - BONNET_FRACTION)))
    cols = max(1, (width + CELL_PX - 1) // CELL_PX)
    rows = max(1, (usable_rows + CELL_PX - 1) // CELL_PX)
    cell_count = cols * rows
    red = [0] * cell_count
    yellow = [0] * cell_count
    bright = [0] * cell_count
    dark = [0] * cell_count
    total = [0] * cell_count

    for offset in range(min(len(pixels), width * usable_rows)):
        pixel = pixels[offset]
        r, g, b = pixel[0], pixel[1], pixel[2]
        cell = (offset // width // CELL_PX) * cols + (offset % width) // CELL_PX
        total[cell] += 1
        if _is_sign_red(r, g, b):
            red[cell] += 1
        elif _is_sign_yellow(r, g, b):
            yellow[cell] += 1
        elif _is_bright_neutral(r, g, b):
            bright[cell] += 1
        elif _is_dark(r, g, b):
            dark[cell] += 1

    cues = {"red": 0.0, "yellow": 0.0, "sign_face": 0.0}
    peak_window: Optional[Tuple[int, int]] = None
    best = 0.0
    span = min(WINDOW_CELLS, cols), min(WINDOW_CELLS, rows)
    for top in range(rows - span[1] + 1):
        for left in range(cols - span[0] + 1):
            area = red_sum = yellow_sum = bright_sum = dark_sum = 0
            for row in range(top, top + span[1]):
                base = row * cols
                for col in range(left, left + span[0]):
                    cell = base + col
                    area += total[cell]
                    red_sum += red[cell]
                    yellow_sum += yellow[cell]
                    bright_sum += bright[cell]
                    dark_sum += dark[cell]
            if not area:
                continue
            red_density = red_sum / area
            yellow_density = yellow_sum / area
            bright_density = bright_sum / area
            dark_density = dark_sum / area

            scores = {
                "red": min(1.0, red_density / RED_FULL) if red_density >= RED_GATE else 0.0,
                "yellow": min(1.0, yellow_density / YELLOW_FULL) if yellow_density >= YELLOW_GATE else 0.0,
            }
            # A plate only counts when both halves of it are present: a bright
            # window alone is sky or a white van, a dark one alone is a hedge.
            if bright_density >= BRIGHT_GATE and dark_density >= DARK_GATE:
                scores["sign_face"] = min(1.0, bright_density / BRIGHT_FULL)
            else:
                scores["sign_face"] = 0.0

            for name, raw in scores.items():
                weighted = raw * CUE_WEIGHTS[name]
                if weighted > cues[name]:
                    cues[name] = weighted
                if weighted > best:
                    best = weighted
                    peak_window = (left, top)

    peak = None
    if peak_window is not None:
        left, top = peak_window
        peak = (
            min(1.0, (left + span[0] / 2) * CELL_PX / width),
            min(1.0, (top + span[1] / 2) * CELL_PX / height),
        )
    return PrefilterScore(score=round(best, 4), cues={k: round(v, 4) for k, v in cues.items()}, peak=peak)


def load_downscaled(path: Path, width: int = WORK_WIDTH):
    """Open a photo, correct its orientation and shrink it for scoring.

    Returns `(pixels, width, height)`, or None if the file will not open —
    a truncated frame at the end of an export is common enough that it must
    not stop a run.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError(
            "Pillow is needed to read photos (pip install pillow)"
        ) from exc

    try:
        with Image.open(path) as image:
            # JPEG can be decoded straight to a reduced size by the decoder
            # itself, which is several times faster than decoding two million
            # pixels and then throwing most of them away. It is a no-op for
            # every other format, and only ever undershoots the requested
            # size, so the resize below still runs.
            try:
                image.draft("RGB", (width, width))
            except Exception:
                pass
            image = ImageOps.exif_transpose(image)
            if image.width > width:
                height = max(1, round(image.height * width / image.width))
                image = image.resize((width, height))
            image = image.convert("RGB")
            # tobytes/zip rather than getdata(): it is the one way to get
            # pixels out that is neither deprecated in newer Pillow nor
            # missing from older, and the slicing happens in C.
            data = image.tobytes()
            return list(zip(data[0::3], data[1::3], data[2::3])), image.width, image.height
    except Exception:
        return None


def score_image(path: Path) -> Optional[PrefilterScore]:
    """Score a photo on disk. None if it could not be read."""
    loaded = load_downscaled(Path(path))
    if loaded is None:
        return None
    pixels, width, height = loaded
    return score_pixels(pixels, width, height)


def explain(score: PrefilterScore) -> List[str]:
    """Human sentences for the report, strongest cue first."""
    lines = []
    for name, value in sorted(score.cues.items(), key=lambda kv: -kv[1]):
        if value <= 0:
            continue
        label = {
            "red": "a concentrated patch of sign red",
            "yellow": "a concentrated patch of housing yellow",
            "sign_face": "a bright plate carrying dark legend",
        }[name]
        lines.append(f"{label} ({value:.2f})")
    return lines
