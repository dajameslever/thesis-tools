"""Asking Claude what is actually in a candidate frame.

The prefilter can only say "something here is the right colour". Deciding
whether that is a 40 roundel, a Gatso housing, a warning sign or a red van is
what this does, and it is the only part of the pipeline that costs money —
which is why nothing reaches it that has not already survived the cheap pass,
why every answer is cached against the photo's own bytes, and why the sign
vocabulary is a closed list rather than free text.

The closed list matters more than it looks. A thesis that reports "312
speed-related signs" has to be able to say what was counted; a column of
model-invented labels ("speed camera sign", "speed cam", "camera warning")
cannot be tabulated, and silently splits one category into three. Anything
the model cannot place in the list comes back as `other_speed_sign` with its
own description preserved, so the residue is visible rather than absorbed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import llm

# Bumping this invalidates every cached verdict, because a changed prompt or
# vocabulary means the old answers were to a different question.
PROMPT_VERSION = 3

# The closed vocabulary. Values are what the prompt shows the model and what
# the reports group by; keep the two in step by changing only this.
SIGN_TYPES: Dict[str, str] = {
    "speed_limit": "a numeric speed limit roundel (a number in a red ring)",
    "national_speed_limit": "the national speed limit sign (white circle, black diagonal bar)",
    "variable_speed_limit": "an electronic/matrix speed limit, usually on a gantry or overhead sign",
    "advisory_speed": "an advisory or temporary speed plate (roadworks limits, bend advisories, 'SLOW')",
    "road_marking_speed": "a speed limit painted on the carriageway itself",
    "speed_camera_warning": "a sign warning that speed cameras are in use (camera pictogram)",
    "average_speed_check": "an average-speed-check / SPECS sign, usually naming a zone",
    "speed_indicator_device": "a 'your speed' feedback sign that displays the approaching vehicle's speed",
    "camera_housing": "an actual enforcement camera unit: a Gatso or Truvelo box, an average-speed camera on a gantry or pole, or a mobile enforcement van",
    "other_speed_sign": "anything else clearly about speed or speed enforcement that none of the above fits",
}

# Types that are enforcement rather than regulation. Reported separately
# because "how many cameras are on this route" and "how often does the limit
# change" are different questions, and a single count answers neither.
ENFORCEMENT_TYPES = frozenset(
    {"speed_camera_warning", "average_speed_check", "camera_housing", "speed_indicator_device"}
)

SYSTEM_PROMPT = (
    "You identify speed-related road signs in single frames of dashcam "
    "footage. You are precise and conservative: an unreadable smudge that "
    "might be a sign is not a sign, and a sign that is not about speed is "
    "not reported at all. You never guess a speed limit you cannot read — "
    "you report the sign without a number instead. You answer with JSON and "
    "nothing else."
)

# Sent below the image. Kept explicit about the negative case because the
# whole point of the prefilter is that most of what gets here is a false
# alarm, and a model that feels obliged to find something will find it.
def build_prompt(types: Optional[List[str]] = None) -> str:
    wanted = types or list(SIGN_TYPES)
    catalogue = "\n".join(f'  - "{name}": {SIGN_TYPES[name]}' for name in wanted if name in SIGN_TYPES)
    return f"""This is one frame from a dashcam video. List every speed-related sign or speed-enforcement device visible in it.

Use only these type values:
{catalogue}

Reply with JSON in exactly this shape and nothing else:

{{"signs": [{{"type": "<one of the values above>", "limit_mph": <number or null>, "confidence": <0.0-1.0>, "position": "<a few words on where in the frame>", "legible": <true|false>}}], "scene": "<one short clause describing the road>"}}

Rules:
  - If there is no speed-related sign or device in the frame, return {{"signs": [], "scene": "..."}}. This is the common case and is the right answer far more often than not.
  - "confidence" is how sure you are that the sign is there and is of that type, not how sure you are of the number.
  - "limit_mph" only when the number is actually readable; otherwise null.
  - "legible": false for a sign you can place but not read — a distant roundel whose number you cannot make out is still a sighting worth recording.
  - One entry per physical sign. Do not repeat the same sign twice."""


@dataclass
class SignHit:
    """One sign the model reports in one frame."""

    type: str
    confidence: float
    limit_mph: Optional[int] = None
    position: str = ""
    legible: bool = True

    @property
    def is_enforcement(self) -> bool:
        return self.type in ENFORCEMENT_TYPES


@dataclass
class FrameVerdict:
    """Everything the model said about one frame."""

    signs: List[SignHit] = field(default_factory=list)
    scene: str = ""
    error: Optional[str] = None
    #: True when this came out of the cache rather than off the wire — what
    #: makes a re-run's "0 calls" believable.
    cached: bool = False

    @property
    def has_sign(self) -> bool:
        return bool(self.signs)

    def to_json(self) -> dict:
        return {
            "signs": [asdict(hit) for hit in self.signs],
            "scene": self.scene,
            "error": self.error,
        }

    @classmethod
    def from_json(cls, data: dict) -> "FrameVerdict":
        return cls(
            signs=[
                SignHit(
                    type=hit.get("type", "other_speed_sign"),
                    confidence=float(hit.get("confidence") or 0.0),
                    limit_mph=hit.get("limit_mph"),
                    position=hit.get("position") or "",
                    legible=bool(hit.get("legible", True)),
                )
                for hit in data.get("signs") or []
            ],
            scene=data.get("scene") or "",
            error=data.get("error"),
        )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_verdict(text: str, allowed: Optional[List[str]] = None) -> FrameVerdict:
    """Read the model's reply into a verdict.

    Tolerant about the wrapping (a stray ```json fence, a sentence before the
    object) and strict about the contents: a sign whose type is not in the
    vocabulary becomes `other_speed_sign` rather than a new category, and a
    confidence that is missing or nonsense becomes 0.0 rather than a
    default-high number that would sail through any threshold.
    """
    if not text:
        return FrameVerdict(error="empty response")
    match = _JSON_RE.search(text)
    if not match:
        return FrameVerdict(error="no JSON in response")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return FrameVerdict(error=f"unreadable JSON ({exc.msg})")
    if not isinstance(data, dict):
        return FrameVerdict(error="JSON was not an object")

    vocabulary = set(allowed or SIGN_TYPES)
    hits: List[SignHit] = []
    for raw in data.get("signs") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if kind not in vocabulary:
            # Keep it, but visibly as the residue category — a label the
            # report can show and a person can go and look at, rather than a
            # new column nobody defined.
            kind = "other_speed_sign"
        try:
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        limit = raw.get("limit_mph")
        try:
            limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit = None
        hits.append(
            SignHit(
                type=kind,
                confidence=round(confidence, 3),
                limit_mph=limit,
                position=str(raw.get("position") or "")[:120],
                legible=bool(raw.get("legible", True)),
            )
        )
    return FrameVerdict(signs=hits, scene=str(data.get("scene") or "")[:200])


# An image is billed by its pixel area, and a 4K frame costs roughly six
# times a 1024px one to say the same thing about. 1024 is about where a sign
# that a person could pick out of the full-size frame is still legible here.
SEND_MAX_DIM = 1024
SEND_QUALITY = 80


def encode_frame(path: Path, max_dim: int = SEND_MAX_DIM) -> Optional[Tuple[str, str]]:
    """Shrink a photo and base64 it for sending. None if it will not open."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError("Pillow is needed to read photos (pip install pillow)") from exc

    try:
        with Image.open(path) as image:
            try:
                image.draft("RGB", (max_dim, max_dim))
            except Exception:
                pass
            image = ImageOps.exif_transpose(image)
            longest = max(image.width, image.height)
            if longest > max_dim:
                scale = max_dim / longest
                image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=SEND_QUALITY)
    except Exception:
        return None
    return base64.b64encode(buffer.getvalue()).decode("ascii"), "image/jpeg"


def frame_fingerprint(path: Path) -> str:
    """A cache key from the photo's own bytes.

    Not the path: frames get re-exported, renamed and moved between folders,
    and a run over the same footage in a new folder should not pay again. Not
    the mtime either, for the same reason.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:32]


class VerdictCache:
    """Verdicts already paid for, keyed by photo bytes, model and prompt.

    All three belong in the key. Re-running after a prompt change, or after
    pointing the run at a better model, has to ask again — reusing those
    answers would silently mix two different measurements in one table.
    """

    def __init__(self, path: Optional[Path]):
        self.path = Path(path) if path else None
        self._entries: Dict[str, dict] = {}
        self._dirty = False
        if self.path and self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._entries = loaded.get("verdicts") or {}
            except (OSError, json.JSONDecodeError):
                self._entries = {}

    @staticmethod
    def key(fingerprint: str, model: str) -> str:
        return f"{fingerprint}:{model}:v{PROMPT_VERSION}"

    def get(self, fingerprint: str, model: str) -> Optional[FrameVerdict]:
        entry = self._entries.get(self.key(fingerprint, model))
        if entry is None:
            return None
        verdict = FrameVerdict.from_json(entry)
        verdict.cached = True
        return verdict

    def put(self, fingerprint: str, model: str, verdict: FrameVerdict) -> None:
        # A failed call is not an answer. Caching it would make the retry that
        # would have fixed it impossible without deleting the file.
        if verdict.error:
            return
        self._entries[self.key(fingerprint, model)] = verdict.to_json()
        self._dirty = True

    def save(self) -> None:
        if not (self.path and self._dirty):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": self._entries}, indent=1),
            encoding="utf-8",
        )
        self._dirty = False

    def __len__(self) -> int:
        return len(self._entries)


def identify(
    client,
    path: Path,
    model: str = llm.DEFAULT_EXTRACTION_MODEL,
    types: Optional[List[str]] = None,
    cache: Optional[VerdictCache] = None,
    usage_totals: Optional[Dict[str, int]] = None,
    max_dim: int = SEND_MAX_DIM,
) -> FrameVerdict:
    """Identify the speed signs in one photo, cache included."""
    fingerprint = ""
    if cache is not None:
        try:
            fingerprint = frame_fingerprint(path)
        except OSError:
            fingerprint = ""
        if fingerprint:
            hit = cache.get(fingerprint, model)
            if hit is not None:
                return hit

    encoded = encode_frame(path, max_dim=max_dim)
    if encoded is None:
        return FrameVerdict(error="could not be opened")
    image_data, media_type = encoded

    errors: List[str] = []
    reply = llm.ask_image(
        client,
        system=SYSTEM_PROMPT,
        user=build_prompt(types),
        image_data=image_data,
        media_type=media_type,
        model=model,
        max_tokens=600,
        errors=errors,
        usage_totals=usage_totals,
    )
    if reply is None:
        return FrameVerdict(error=errors[0] if errors else "no response")

    verdict = parse_verdict(reply, allowed=types)
    if cache is not None and fingerprint:
        cache.put(fingerprint, model, verdict)
    return verdict
