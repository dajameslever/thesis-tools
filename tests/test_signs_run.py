"""The whole pipeline, from a folder of photos to the files it leaves."""

import csv
import json
from unittest.mock import MagicMock

from PIL import Image, ImageDraw

from thesis_tools.cli import main
from thesis_tools.signs.detect import SignDetectionInputs, run_detection
from thesis_tools.signs.report import render_html, write_reports

ROAD = (105, 112, 120)


def _frame(path, roundel_radius=None):
    image = Image.new("RGB", (480, 270), ROAD)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 480, 115], fill=(150, 175, 210))
    if roundel_radius:
        cx, cy = 340, 100
        draw.ellipse(
            [cx - roundel_radius, cy - roundel_radius, cx + roundel_radius, cy + roundel_radius],
            fill=(240, 240, 238),
            outline=(198, 26, 32),
            width=max(2, roundel_radius // 3),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=90)
    return path


def _drive(root, name="drive-a12", frames=12, sign_from=6):
    for i in range(1, frames + 1):
        radius = 6 + (i - sign_from) * 4 if i >= sign_from else None
        _frame(root / name / f"frame_{i:05d}.jpg", radius)
    return root / name


def _replying(text):
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.usage = MagicMock(input_tokens=900, output_tokens=40, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    client.messages.create.return_value = response
    return client


def test_only_candidate_frames_reach_the_model(tmp_path, monkeypatch):
    """The reason the tool is affordable at all: an empty road costs nothing
    but arithmetic, and only what the cheap pass flags is ever sent."""
    photos = tmp_path / "photos"
    _drive(photos)
    client = _replying('{"signs": [{"type": "speed_limit", "confidence": 0.9, "limit_mph": 30}], "scene": "a road"}')
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: None)
    monkeypatch.setattr("thesis_tools.llm.get_client", lambda quiet=False: client)

    run = run_detection(SignDetectionInputs(photos_dir=str(photos), out_dir=str(tmp_path / "out"), quiet=True))

    assert run.frames_scanned == 12
    assert 0 < run.candidates < run.frames_scanned
    assert client.messages.create.call_count == run.candidates
    assert len(run.sightings) == 1


def test_a_rerun_costs_nothing(tmp_path, monkeypatch):
    """The cache is keyed on the photos' own bytes, so re-running to tune a
    threshold does not pay for the identifications a second time."""
    photos = tmp_path / "photos"
    _drive(photos)
    client = _replying('{"signs": [], "scene": "a road"}')
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: None)
    monkeypatch.setattr("thesis_tools.llm.get_client", lambda quiet=False: client)
    inputs = SignDetectionInputs(photos_dir=str(photos), out_dir=str(tmp_path / "out"), quiet=True)

    first = run_detection(inputs)
    calls_after_first = client.messages.create.call_count
    second = run_detection(inputs)

    assert first.calls == calls_after_first > 0
    assert second.calls == 0
    assert second.cache_hits == calls_after_first


def test_the_call_budget_caps_the_bill_not_the_scan(tmp_path, monkeypatch):
    """Every frame is still scored and still reported; the ones past the
    ceiling are marked unconfirmed rather than dropped."""
    photos = tmp_path / "photos"
    _drive(photos)
    client = _replying('{"signs": [], "scene": "a road"}')
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: None)
    monkeypatch.setattr("thesis_tools.llm.get_client", lambda quiet=False: client)

    run = run_detection(
        SignDetectionInputs(photos_dir=str(photos), out_dir=str(tmp_path / "out"), max_calls=1, quiet=True)
    )

    assert run.calls == 1
    assert run.frames_scanned == 12
    assert any(r.skipped == "call budget reached" for r in run.results)


def test_without_a_key_the_run_still_flags_candidates(tmp_path, monkeypatch):
    """Offline the tool is a triage rather than an identifier — which is
    worth having, and worth saying plainly rather than reporting zero signs
    as though the road were empty."""
    photos = tmp_path / "photos"
    _drive(photos)
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: "ANTHROPIC_API_KEY not set")

    run = run_detection(SignDetectionInputs(photos_dir=str(photos), out_dir=str(tmp_path / "out"), quiet=True))

    assert run.calls == 0
    assert run.sightings and all(s.unconfirmed for s in run.sightings)
    assert "ANTHROPIC_API_KEY not set" in run.llm_note


def test_a_missing_folder_is_an_error_not_an_empty_report(tmp_path):
    run = run_detection(SignDetectionInputs(photos_dir=str(tmp_path / "nope"), quiet=True))

    assert run.results == []
    assert "does not exist" in run.errors[0]


def test_an_unreadable_photo_does_not_stop_the_run(tmp_path, monkeypatch):
    """A truncated frame at the end of an export is common enough that it
    must not cost the other nine hundred."""
    photos = tmp_path / "photos"
    _drive(photos, frames=4, sign_from=99)
    (photos / "drive-a12" / "frame_00005.jpg").write_bytes(b"truncated")
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: "no key")

    run = run_detection(SignDetectionInputs(photos_dir=str(photos), out_dir=str(tmp_path / "out"), quiet=True))

    assert run.frames_scanned == 5
    assert any("could not be read" in e for e in run.errors)


def test_the_reports_carry_both_the_sightings_and_the_audit_trail(tmp_path, monkeypatch):
    """The sighting table is what gets quoted; the frame table is what makes
    a disagreement about the threshold settleable."""
    photos = tmp_path / "photos"
    _drive(photos)
    client = _replying('{"signs": [{"type": "camera_housing", "confidence": 0.8}], "scene": "a dual carriageway"}')
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: None)
    monkeypatch.setattr("thesis_tools.llm.get_client", lambda quiet=False: client)
    out = tmp_path / "out"

    run = run_detection(SignDetectionInputs(photos_dir=str(photos), out_dir=str(out), quiet=True))
    written = write_reports(run, out, quiet=True)

    sightings = list(csv.DictReader(written["sightings"].open(encoding="utf-8")))
    frames = list(csv.DictReader(written["frames"].open(encoding="utf-8")))
    payload = json.loads(written["json"].read_text(encoding="utf-8"))

    assert sightings and sightings[0]["sign_type"] == "camera_housing"
    assert sightings[0]["enforcement"] == "yes"
    assert len(frames) == 12, "every photo scanned needs a row, not just the ones that were sent"
    assert {r["examined"] for r in frames} == {"yes", "no"}
    assert payload["counts_by_type"]["camera_housing"] == 1
    assert payload["totals"]["frames_scanned"] == 12


def test_the_html_embeds_its_pictures(tmp_path, monkeypatch):
    """A page that points at file paths breaks the moment it is emailed to a
    supervisor, which is most of what it is for."""
    photos = tmp_path / "photos"
    _drive(photos)
    client = _replying('{"signs": [{"type": "speed_limit", "confidence": 0.9, "limit_mph": 30}], "scene": "a road"}')
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: None)
    monkeypatch.setattr("thesis_tools.llm.get_client", lambda quiet=False: client)

    run = run_detection(SignDetectionInputs(photos_dir=str(photos), out_dir=str(tmp_path / "out"), quiet=True))
    html = render_html(run)

    assert "data:image/jpeg;base64," in html
    assert "30 mph limit" in html
    assert "http://" not in html and "https://" not in html


def test_the_html_says_when_nothing_identified_anything(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    _drive(photos)
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: "ANTHROPIC_API_KEY not set")

    run = run_detection(SignDetectionInputs(photos_dir=str(photos), out_dir=str(tmp_path / "out"), quiet=True))

    assert "ANTHROPIC_API_KEY not set" in render_html(run)


def test_cli_detect_signs_writes_a_report(tmp_path, capsys):
    photos = tmp_path / "photos"
    _drive(photos)
    out = tmp_path / "out"

    rc = main(
        [
            "detect-signs",
            "--photos", str(photos),
            "--out", str(out),
            "--no-llm",
            "--quiet",
            "--non-interactive",
            "--project-file", str(tmp_path / "project.json"),
        ]
    )

    assert rc == 0
    assert (out / "report.html").is_file()
    assert (out / "sightings.csv").is_file()
    assert "candidate(s) flagged but never identified" in capsys.readouterr().out


def test_cli_rejects_an_unknown_sign_type(tmp_path, capsys):
    """--types is a filter on a closed vocabulary; a typo in it would
    otherwise silently narrow the search to nothing."""
    rc = main(
        [
            "detect-signs",
            "--photos", str(tmp_path),
            "--types", "speed_limit,speed_cameras",
            "--non-interactive",
            "--project-file", str(tmp_path / "project.json"),
        ]
    )

    assert rc == 2
    assert "unknown sign type" in capsys.readouterr().err


def test_cli_reports_a_missing_folder(tmp_path, capsys):
    rc = main(
        [
            "detect-signs",
            "--photos", str(tmp_path / "nope"),
            "--non-interactive",
            "--project-file", str(tmp_path / "project.json"),
        ]
    )

    assert rc == 2
    assert "doesn't exist" in capsys.readouterr().err


def test_cli_needs_photos_when_not_prompting(tmp_path, capsys):
    rc = main(["detect-signs", "--non-interactive", "--project-file", str(tmp_path / "project.json")])

    assert rc == 2
    assert "requires --photos" in capsys.readouterr().err


def test_a_second_run_under_output_keeps_the_first_ones_tables(tmp_path, monkeypatch):
    """The destination decides, not the writer: re-running a scan into
    `output/` must not destroy the table an earlier run's numbers were quoted
    from. See outputs.py."""
    photos = tmp_path / "photos"
    _drive(photos, frames=3, sign_from=99)
    monkeypatch.setattr("thesis_tools.llm.availability_issue", lambda: "no key")
    out = tmp_path / "output" / "speed-signs"
    inputs = SignDetectionInputs(photos_dir=str(photos), out_dir=str(out), quiet=True)

    write_reports(run_detection(inputs), out, quiet=True)
    write_reports(run_detection(inputs), out, quiet=True)

    kept = sorted((out / "previous").glob("*"))
    assert [p.name.split("-")[0] for p in kept] == ["detections", "frames", "report", "sightings"]
    assert not (out / "previous" / "verdict").exists()
