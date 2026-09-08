"""What the run leaves behind.

Four files, because four different things get done with this. `sightings.csv`
is the one that becomes a table in a chapter — one row per physical sign.
`frames.csv` is the audit trail: every photo, its score, and what happened to
it, which is what makes a threshold argument settleable. `detections.json`
carries the whole run for anything downstream. `report.html` is the one a
person actually opens, because a claim that a frame contains a 40 roundel is
worth exactly as much as the picture next to it.
"""

from __future__ import annotations

import base64
import csv
import datetime as _dt
import html as _html
import io
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from ..outputs import archive_if_kept, write_view
from .detect import DetectionRun, Sighting
from .vision import SIGN_TYPES

# Big enough to see the sign in, small enough that a few hundred of them
# still open as one page.
THUMB_WIDTH = 360

# Past this many pictures the page stops being a page. The cards are still
# written; they just carry the file path instead of the image.
MAX_THUMBNAILS = 400

SIGHTING_COLUMNS = [
    "sequence",
    "sign_type",
    "label",
    "limit_mph",
    "enforcement",
    "confidence",
    "frames_seen",
    "first_frame",
    "last_frame",
    "legible",
    "best_frame_file",
    "positions",
]

FRAME_COLUMNS = [
    "sequence",
    "frame_file",
    "frame_index",
    "position",
    "prefilter_score",
    "cue_red",
    "cue_yellow",
    "cue_sign_face",
    "examined",
    "outcome",
    "signs_found",
    "top_confidence",
    "scene",
]


def _sighting_row(sighting: Sighting) -> dict:
    return {
        "sequence": sighting.sequence,
        "sign_type": sighting.type,
        "label": sighting.label,
        "limit_mph": sighting.limit_mph if sighting.limit_mph else "",
        "enforcement": "yes" if sighting.is_enforcement else "no",
        "confidence": f"{sighting.confidence:.2f}",
        "frames_seen": sighting.frame_count,
        "first_frame": sighting.first_index,
        "last_frame": sighting.last_index,
        "legible": "yes" if sighting.legible else "no",
        "best_frame_file": str(sighting.best_frame) if sighting.best_frame else "",
        "positions": "; ".join(p for p in sighting.positions if p),
    }


def _frame_row(result) -> dict:
    score = result.score
    verdict = result.verdict
    hits = result.hits
    return {
        "sequence": result.frame.sequence,
        "frame_file": str(result.frame.path),
        "frame_index": result.frame.index,
        "position": result.frame.position,
        "prefilter_score": f"{score.score:.3f}" if score else "",
        "cue_red": f"{score.cues.get('red', 0):.3f}" if score else "",
        "cue_yellow": f"{score.cues.get('yellow', 0):.3f}" if score else "",
        "cue_sign_face": f"{score.cues.get('sign_face', 0):.3f}" if score else "",
        "examined": "yes" if result.examined else "no",
        "outcome": result.skipped or (verdict.error if verdict and verdict.error else "identified"),
        "signs_found": "; ".join(hit.type for hit in hits),
        "top_confidence": f"{max((hit.confidence for hit in hits), default=0):.2f}" if hits else "",
        "scene": verdict.scene if verdict else "",
    }


def _write_csv(path: Path, columns: List[str], rows: List[dict], quiet: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # csv writes through an open file handle rather than a string, so the
    # keep-or-overwrite decision has to be made here rather than by
    # write_output — same rule, applied by hand. See outputs.py.
    archive_if_kept(path, quiet=quiet)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def counts_by_type(sightings: List[Sighting]) -> Dict[str, int]:
    """How many of each kind of sign — the summary a chapter quotes."""
    return dict(Counter(s.type for s in sightings).most_common())


def counts_by_sequence(sightings: List[Sighting]) -> Dict[str, int]:
    return dict(Counter(s.sequence for s in sightings).most_common())


def limits_seen(sightings: List[Sighting]) -> Dict[int, int]:
    """Posted limits and how often each was read, lowest first."""
    counter = Counter(s.limit_mph for s in sightings if s.limit_mph)
    return {limit: counter[limit] for limit in sorted(counter)}


def _thumbnail(path: Optional[Path], width: int = THUMB_WIDTH) -> Optional[str]:
    """A data-URI thumbnail, so the page survives being emailed or moved off
    the machine that made it. None if the photo will not open."""
    if not path:
        return None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            try:
                image.draft("RGB", (width, width))
            except Exception:
                pass
            image = ImageOps.exif_transpose(image)
            if image.width > width:
                image = image.resize((width, max(1, round(image.height * width / image.width))))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=72)
    except Exception:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


_CSS = """
:root {
  --sd-page: #14161a;
  --sd-surface: #1c1f25;
  --sd-border: #2c313a;
  --sd-text: #e8e9ec;
  --sd-secondary: #a4a9b4;
  --sd-muted: #737a88;
  --sd-accent: #7fb2f0;
  --sd-enforce-bg: rgba(232,106,90,0.18);
  --sd-enforce-fg: #f2a89c;
  --sd-limit-bg: rgba(127,178,240,0.16);
  --sd-limit-fg: #a8cbf5;
  --sd-unconfirmed-bg: rgba(255,255,255,0.07);
  --sd-unconfirmed-fg: #c3c2b7;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--sd-page); color: var(--sd-text); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.6; }
.sd-wrap { max-width: 1180px; margin: 0 auto; padding: 40px 24px 96px; }
h1 { font-size: 1.7rem; margin: 0 0 6px; }
h2 { font-size: 1.15rem; margin: 44px 0 14px; padding-top: 18px; border-top: 1px solid var(--sd-border); }
.sd-sub { color: var(--sd-secondary); margin: 0 0 28px; }
.sd-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 28px; }
.sd-stat { background: var(--sd-surface); border: 1px solid var(--sd-border); border-radius: 10px; padding: 14px 16px; }
.sd-stat-value { font-size: 1.5rem; font-weight: 600; line-height: 1.2; }
.sd-stat-label { color: var(--sd-muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; margin-bottom: 20px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--sd-border); }
th { color: var(--sd-muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; }
.sd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 18px; }
.sd-card { background: var(--sd-surface); border: 1px solid var(--sd-border); border-radius: 12px; overflow: hidden; }
.sd-card img { display: block; width: 100%; height: auto; background: #000; }
.sd-card-body { padding: 12px 14px 14px; }
.sd-card-title { font-weight: 600; margin-bottom: 4px; }
.sd-card-meta { color: var(--sd-secondary); font-size: 0.83rem; margin: 0; }
.sd-card-file { color: var(--sd-muted); font-size: 0.75rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; margin-top: 8px; }
.sd-tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.68rem; font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase; margin-left: 6px; vertical-align: 2px; }
.sd-tag-enforcement { background: var(--sd-enforce-bg); color: var(--sd-enforce-fg); }
.sd-tag-limit { background: var(--sd-limit-bg); color: var(--sd-limit-fg); }
.sd-tag-unconfirmed { background: var(--sd-unconfirmed-bg); color: var(--sd-unconfirmed-fg); }
.sd-note { background: var(--sd-surface); border: 1px solid var(--sd-border); border-left: 3px solid var(--sd-accent); border-radius: 0 8px 8px 0; padding: 12px 16px; color: var(--sd-secondary); font-size: 0.9rem; margin-bottom: 24px; }
.sd-foot { color: var(--sd-muted); font-size: 0.8rem; margin-top: 48px; }
a { color: var(--sd-accent); }
"""


def _stat(value, label) -> str:
    return f'<div class="sd-stat"><div class="sd-stat-value">{_html.escape(str(value))}</div><div class="sd-stat-label">{_html.escape(label)}</div></div>'


def _card(sighting: Sighting, thumbnail: Optional[str]) -> str:
    if sighting.unconfirmed:
        tag = '<span class="sd-tag sd-tag-unconfirmed">unconfirmed</span>'
    elif sighting.is_enforcement:
        tag = '<span class="sd-tag sd-tag-enforcement">enforcement</span>'
    else:
        tag = '<span class="sd-tag sd-tag-limit">limit</span>'

    span = (
        f"frames {sighting.first_index}–{sighting.last_index}"
        if sighting.last_index != sighting.first_index
        else f"frame {sighting.first_index}"
    )
    meta = [f"{span} · seen in {sighting.frame_count}", f"confidence {sighting.confidence:.2f}"]
    if sighting.positions:
        meta.append(_html.escape(sighting.positions[0]))
    if not sighting.legible and not sighting.unconfirmed:
        meta.append("not legible")

    image = f'<img src="{thumbnail}" alt="">' if thumbnail else ""
    file_line = ""
    if sighting.best_frame:
        file_line = f'<div class="sd-card-file">{_html.escape(str(sighting.best_frame))}</div>'
    return (
        '<div class="sd-card">'
        f"{image}"
        '<div class="sd-card-body">'
        f'<div class="sd-card-title">{_html.escape(sighting.label)}{tag}</div>'
        f'<p class="sd-card-meta">{" · ".join(meta)}</p>'
        f"{file_line}"
        "</div></div>"
    )


def render_html(run: DetectionRun, thumbnails: bool = True) -> str:
    """A self-contained page: every picture is embedded, so it can be moved,
    emailed or attached to a supervision meeting without breaking."""
    inputs = run.inputs
    confirmed = [s for s in run.sightings if not s.unconfirmed]
    unconfirmed = [s for s in run.sightings if s.unconfirmed]
    enforcement = [s for s in confirmed if s.is_enforcement]

    stats = "".join(
        [
            _stat(f"{run.frames_scanned:,}", "photos scanned"),
            _stat(f"{run.candidates:,}", "candidate frames"),
            _stat(f"{len(confirmed):,}", "signs identified"),
            _stat(f"{len(enforcement):,}", "enforcement sightings"),
            _stat(f"{run.calls:,}", "Claude calls"),
        ]
    )

    by_type = counts_by_type(confirmed)
    type_rows = "".join(
        f"<tr><td>{_html.escape(SIGN_TYPES.get(name, name.replace('_', ' ')))}</td>"
        f"<td><code>{_html.escape(name)}</code></td><td>{count}</td></tr>"
        for name, count in by_type.items()
    )
    type_table = (
        f"<table><thead><tr><th>Sign</th><th>Type</th><th>Sightings</th></tr></thead><tbody>{type_rows}</tbody></table>"
        if type_rows
        else "<p class='sd-card-meta'>No signs were identified in this run.</p>"
    )

    limits = limits_seen(confirmed)
    limit_table = ""
    if limits:
        rows = "".join(f"<tr><td>{limit} mph</td><td>{count}</td></tr>" for limit, count in limits.items())
        limit_table = (
            "<h2>Posted limits read</h2>"
            f"<table><thead><tr><th>Limit</th><th>Times read</th></tr></thead><tbody>{rows}</tbody></table>"
        )

    note = ""
    if run.llm_note:
        note = f'<div class="sd-note">{_html.escape(run.llm_note)}.</div>'

    show_pictures = thumbnails and len(run.sightings) <= MAX_THUMBNAILS
    sections = []
    for sequence in sorted({s.sequence for s in run.sightings}):
        in_sequence = [s for s in run.sightings if s.sequence == sequence]
        cards = "".join(
            _card(s, _thumbnail(s.best_frame) if show_pictures else None) for s in in_sequence
        )
        sections.append(
            f"<h2>{_html.escape(sequence)} <span class='sd-card-meta'>— {len(in_sequence)} sighting(s)</span></h2>"
            f'<div class="sd-grid">{cards}</div>'
        )
    if not sections:
        sections.append("<h2>Sightings</h2><p class='sd-card-meta'>Nothing was flagged in these photos.</p>")

    when = _dt.datetime.now().strftime("%d %B %Y, %H:%M")
    thumb_note = (
        ""
        if show_pictures
        else f'<div class="sd-note">Over {MAX_THUMBNAILS} sightings, so the pictures are left out to keep the page openable — the file paths below point at the frames.</div>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Speed signs — {_html.escape(Path(inputs.photos_dir).name or inputs.photos_dir)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="sd-wrap">
  <h1>Speed signs in {_html.escape(Path(inputs.photos_dir).name or inputs.photos_dir)}</h1>
  <p class="sd-sub">{_html.escape(when)} · prefilter ≥ {inputs.min_score:.2f} · confidence ≥ {inputs.min_confidence:.2f} · model {_html.escape(inputs.llm_model)}</p>
  {note}
  {thumb_note}
  <div class="sd-stats">{stats}</div>
  <h2>What was found</h2>
  {type_table}
  {limit_table}
  {"".join(sections)}
  <p class="sd-foot">Generated by thesis-tools. Every sighting above is a claim about a photograph — the frame it was read from is named beside it, and sightings.csv carries the same rows for a table. {len(unconfirmed)} candidate(s) were flagged by the local pass but never identified.</p>
</div>
</body>
</html>"""


def write_reports(run: DetectionRun, out_dir: Path, quiet: bool = False) -> Dict[str, Path]:
    """Write all four files. Returns what was written, by kind."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sightings_path = out_dir / "sightings.csv"
    frames_path = out_dir / "frames.csv"
    json_path = out_dir / "detections.json"
    html_path = out_dir / "report.html"

    _write_csv(sightings_path, SIGHTING_COLUMNS, [_sighting_row(s) for s in run.sightings], quiet=quiet)
    _write_csv(frames_path, FRAME_COLUMNS, [_frame_row(r) for r in run.results], quiet=quiet)

    payload = {
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "photos": str(run.inputs.photos_dir),
        "settings": {
            "min_score": run.inputs.min_score,
            "min_confidence": run.inputs.min_confidence,
            "max_gap": run.inputs.max_gap,
            "every": run.inputs.every,
            "model": run.inputs.llm_model,
        },
        "totals": {
            "frames_scanned": run.frames_scanned,
            "candidates": run.candidates,
            "frames_with_signs": run.frames_with_signs,
            "calls": run.calls,
            "cache_hits": run.cache_hits,
            "seconds": round(run.seconds, 1),
        },
        "counts_by_type": counts_by_type([s for s in run.sightings if not s.unconfirmed]),
        "counts_by_sequence": counts_by_sequence(run.sightings),
        "limits_seen": {str(k): v for k, v in limits_seen(run.sightings).items()},
        "sightings": [_sighting_row(s) for s in run.sightings],
        "errors": run.errors[:50],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    archive_if_kept(json_path, quiet=quiet)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # The page is a living view of this folder of photos; under `output/` the
    # destination's rule takes over and every run is kept, exactly as it does
    # for the two CSVs above. The verdict cache is deliberately left out of
    # all this: it is state, and versioning it would bury the run history in
    # copies of itself.
    write_view(html_path, render_html(run), quiet=quiet)

    return {
        "sightings": sightings_path,
        "frames": frames_path,
        "json": json_path,
        "html": html_path,
    }
