import math
import random

from thesis_tools.signs.prefilter import (
    DEFAULT_MIN_SCORE,
    score_pixels,
)

WIDTH, HEIGHT = 200, 120
ROAD = (105, 112, 120)


def _scene(fill=ROAD):
    return [fill] * (WIDTH * HEIGHT)


def _paint(pixels, x0, y0, x1, y1, colour):
    for y in range(y0, y1):
        for x in range(x0, x1):
            pixels[y * WIDTH + x] = colour
    return pixels


def _roundel(pixels, cx, cy, radius, ring=(190, 25, 30), face=(238, 238, 235)):
    thickness = max(1.2, radius * 0.35)
    for y in range(cy - radius - 1, cy + radius + 2):
        for x in range(cx - radius - 1, cx + radius + 2):
            if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                continue
            distance = math.hypot(x - cx, y - cy)
            if radius - thickness <= distance <= radius:
                pixels[y * WIDTH + x] = ring
            elif distance < radius - thickness:
                pixels[y * WIDTH + x] = face
    return pixels


def test_an_empty_road_scores_nothing():
    """The common case, and the one that has to cost nothing."""
    assert score_pixels(_scene(), WIDTH, HEIGHT).score == 0.0


def test_plain_sky_scores_nothing():
    """Bright and uniform is not a sign — the plate cue needs dark legend on
    it before it counts, or every frame with sky in it would be a candidate."""
    assert score_pixels(_scene((150, 175, 215)), WIDTH, HEIGHT).score == 0.0


def test_a_speed_limit_roundel_is_flagged():
    scored = score_pixels(_roundel(_scene(), 100, 40, 10), WIDTH, HEIGHT)

    assert scored.passes(DEFAULT_MIN_SCORE)
    assert scored.leading_cue == "red"


def test_a_small_distant_roundel_still_clears_the_default_threshold():
    """A sign is at its most useful several frames before it fills the shot.
    Losing it until it is close costs the approach frames that are often the
    only unobstructed view of it."""
    scored = score_pixels(_roundel(_scene(), 100, 40, 4), WIDTH, HEIGHT)

    assert scored.passes(DEFAULT_MIN_SCORE)


def test_a_yellow_camera_housing_is_flagged_without_any_red():
    """Gatso boxes carry no red at all. A red-only filter would miss every
    one of them."""
    scored = score_pixels(_paint(_scene(), 150, 30, 168, 52, (225, 195, 40)), WIDTH, HEIGHT)

    assert scored.passes(DEFAULT_MIN_SCORE)
    assert scored.leading_cue == "yellow"
    assert scored.cues["red"] == 0.0


def test_a_white_plate_with_dark_legend_is_flagged():
    """Average-speed-check and camera-warning signs are mostly colourless."""
    pixels = _paint(_scene(), 120, 44, 146, 62, (228, 228, 224))
    _paint(pixels, 126, 50, 140, 56, (35, 35, 38))

    scored = score_pixels(pixels, WIDTH, HEIGHT)

    assert scored.passes(DEFAULT_MIN_SCORE)
    assert scored.leading_cue == "sign_face"


def test_a_bright_patch_with_no_legend_is_not_a_plate():
    """A white van is bright and colourless too. Requiring dark pixels beside
    the bright ones is the only thing separating the two."""
    scored = score_pixels(_paint(_scene(), 100, 40, 140, 70, (230, 230, 228)), WIDTH, HEIGHT)

    assert scored.cues["sign_face"] == 0.0


def test_the_bonnet_is_not_scored():
    """The bottom of a dashcam frame is the car's own bonnet: a permanent
    red or bright reflection there would flag every single frame of a drive."""
    pixels = _paint(_scene(), 40, 112, 120, 120, (200, 30, 30))

    assert score_pixels(pixels, WIDTH, HEIGHT).score == 0.0


def test_concentration_is_the_signal_not_the_amount_of_red():
    """Two frames with the same quantity of red in them: one sign, one
    sprinkle. Scoring the frame's overall red fraction would rank them the
    same, and brake lights would flag half a rush-hour drive."""
    sign = _paint(_scene(), 96, 36, 110, 50, (200, 30, 30))
    sign_red = sum(1 for p in sign if p == (200, 30, 30))

    random.seed(11)
    scattered = _scene()
    placed = 0
    while placed < sign_red:
        offset = random.randrange(WIDTH * HEIGHT)
        if scattered[offset] == ROAD:
            scattered[offset] = (200, 30, 30)
            placed += 1

    assert score_pixels(sign, WIDTH, HEIGHT).score > score_pixels(scattered, WIDTH, HEIGHT).score * 2


def test_peak_reports_where_the_cue_was():
    """Not used for the decision — it is there so a false positive can be
    traced to the part of the frame that caused it."""
    scored = score_pixels(_roundel(_scene(), 160, 24, 8), WIDTH, HEIGHT)

    x, y = scored.peak
    assert 0.7 < x < 0.9
    assert y < 0.35


def test_an_empty_frame_is_handled_rather_than_raising():
    assert score_pixels([], 0, 0).score == 0.0
