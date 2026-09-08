from pathlib import Path

from thesis_tools.signs.detect import (
    DEFAULT_MAX_GAP,
    FrameResult,
    group_sightings,
    unconfirmed_candidates,
)
from thesis_tools.signs.frames import Frame
from thesis_tools.signs.prefilter import PrefilterScore
from thesis_tools.signs.vision import FrameVerdict, SignHit


def _seen(position, *hits, sequence="a12"):
    return FrameResult(
        frame=Frame(path=Path(f"{sequence}/frame_{position:05d}.jpg"), sequence=sequence, index=position, position=position),
        score=PrefilterScore(score=0.5),
        verdict=FrameVerdict(signs=list(hits)),
    )


def _hit(kind="speed_limit", confidence=0.9, limit=None, legible=True, position=""):
    return SignHit(type=kind, confidence=confidence, limit_mph=limit, legible=legible, position=position)


def test_one_sign_across_many_frames_is_one_sighting():
    """The whole point. Approaching a roundel puts it in fifty frames, and a
    count taken from the frames would be wrong by whatever the frame rate
    happens to be."""
    results = [_seen(i, _hit(limit=40)) for i in range(20)]

    sightings = group_sightings(results)

    assert len(sightings) == 1
    assert sightings[0].frame_count == 20
    assert sightings[0].first_index == 0
    assert sightings[0].last_index == 19


def test_the_same_sign_before_and_after_an_occlusion_stays_one_sighting():
    """A lamp post between the camera and the sign is not a second sign."""
    results = [_seen(0, _hit()), _seen(20, _hit())]

    assert len(group_sightings(results, max_gap=DEFAULT_MAX_GAP)) == 1


def test_two_signs_far_enough_apart_are_two_sightings():
    results = [_seen(0, _hit()), _seen(500, _hit())]

    assert len(group_sightings(results)) == 2


def test_a_different_number_makes_it_a_different_sign_however_close():
    """A 30 six frames after a 40 is a limit change, not a re-reading."""
    results = [_seen(0, _hit(limit=40)), _seen(6, _hit(limit=30))]

    sightings = group_sightings(results)

    assert [s.limit_mph for s in sightings] == [40, 30]


def test_an_unreadable_roundel_beside_a_readable_one_is_the_same_sign():
    """Approach frames often cannot resolve the number. Splitting on that
    would double-count every sign that was ever seen from a distance."""
    results = [_seen(0, _hit(limit=None, legible=False)), _seen(4, _hit(limit=30))]

    sightings = group_sightings(results)

    assert len(sightings) == 1
    assert sightings[0].limit_mph == 30
    assert sightings[0].legible is True


def test_two_different_sign_types_in_one_frame_are_two_sightings():
    """A camera warning sign is usually mounted with a limit roundel."""
    results = [_seen(0, _hit("speed_camera_warning"), _hit("speed_limit", limit=50))]

    assert {s.type for s in group_sightings(results)} == {"speed_camera_warning", "speed_limit"}


def test_frames_from_different_videos_never_merge():
    """Two drives are two roads, whatever their frame numbers happen to be."""
    results = [_seen(0, _hit(), sequence="a12"), _seen(1, _hit(), sequence="m1")]

    assert len(group_sightings(results)) == 2


def test_the_best_frame_is_the_most_confident_one():
    """It is the picture a reader is shown to check the claim, so it has to
    be the frame the sign was clearest in — not the first one it appeared
    in, which is the smallest and furthest away."""
    results = [_seen(0, _hit(confidence=0.5)), _seen(1, _hit(confidence=0.95)), _seen(2, _hit(confidence=0.6))]

    sighting = group_sightings(results)[0]

    assert sighting.best_frame.name == "frame_00001.jpg"
    assert sighting.confidence == 0.95


def test_low_confidence_hits_do_not_become_sightings():
    """A sighting is a claim. The model's own hedging belongs in the
    per-frame audit table, not in the count a chapter quotes."""
    results = [_seen(0, _hit(confidence=0.2))]

    assert group_sightings(results, min_confidence=0.4) == []


def test_enforcement_is_distinguished_from_regulation():
    """"How many cameras are on this route" and "how often does the limit
    change" are different questions; one number answers neither."""
    results = [_seen(0, _hit("camera_housing")), _seen(400, _hit("speed_limit", limit=30))]

    sightings = group_sightings(results)

    assert [s.is_enforcement for s in sightings] == [True, False]


def test_a_speed_limit_sighting_is_labelled_with_its_number():
    results = [_seen(0, _hit(limit=40))]

    assert group_sightings(results)[0].label == "40 mph limit"


def test_flagged_but_unidentified_frames_are_grouped_too():
    """Offline, or out of budget: thirty flagged frames of one approach are
    one thing to go and look at, not thirty."""
    results = [
        FrameResult(
            frame=Frame(path=Path(f"f{i}.jpg"), sequence="a12", index=i, position=i),
            score=PrefilterScore(score=0.4, cues={"red": 0.4}),
            skipped="Claude unavailable",
        )
        for i in range(10)
    ]

    candidates = unconfirmed_candidates(results, min_score=0.18)

    assert len(candidates) == 1
    assert candidates[0].unconfirmed is True
    assert candidates[0].frame_count == 10


def test_frames_below_the_threshold_are_not_candidates():
    results = [
        FrameResult(
            frame=Frame(path=Path("f.jpg"), sequence="a12", index=0, position=0),
            score=PrefilterScore(score=0.02),
            skipped="below threshold",
        )
    ]

    assert unconfirmed_candidates(results, min_score=0.18) == []


def test_an_examined_frame_is_never_reported_as_unconfirmed():
    """It was identified — as nothing. Listing it as "worth a look" would put
    every empty road the model checked into the report."""
    results = [_seen(0)]

    assert unconfirmed_candidates(results, min_score=0.18) == []
