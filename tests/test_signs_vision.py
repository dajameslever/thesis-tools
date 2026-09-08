from unittest.mock import MagicMock

from PIL import Image

from thesis_tools import llm
from thesis_tools.signs import vision
from thesis_tools.signs.vision import (
    PROMPT_VERSION,
    FrameVerdict,
    VerdictCache,
    build_prompt,
    encode_frame,
    frame_fingerprint,
    identify,
    parse_verdict,
)


def _photo(path, colour=(120, 120, 120), size=(64, 48)):
    Image.new("RGB", size, colour).save(path, quality=90)
    return path


def _replying(text):
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    client.messages.create.return_value = response
    return client


def test_a_fenced_reply_is_still_read():
    """Models wrap JSON in prose and code fences. Refusing those would throw
    away answers that were already paid for."""
    verdict = parse_verdict('Here you go:\n```json\n{"signs": [], "scene": "empty road"}\n```')

    assert verdict.error is None
    assert verdict.scene == "empty road"


def test_an_unknown_type_becomes_the_residue_category_not_a_new_one():
    """A count of sign types is only tabulatable if the vocabulary is closed.
    An invented label must land somewhere visible instead of quietly becoming
    an eleventh column."""
    verdict = parse_verdict('{"signs": [{"type": "speed cam", "confidence": 0.9}]}')

    assert [hit.type for hit in verdict.signs] == ["other_speed_sign"]


def test_a_known_type_written_loosely_is_recognised():
    verdict = parse_verdict('{"signs": [{"type": "Speed Limit", "confidence": 0.8, "limit_mph": "40"}]}')

    assert verdict.signs[0].type == "speed_limit"
    assert verdict.signs[0].limit_mph == 40


def test_a_missing_confidence_is_zero_not_a_default_pass():
    """Anything else lets an unscored guess through every downstream
    threshold untouched."""
    verdict = parse_verdict('{"signs": [{"type": "camera_housing"}]}')

    assert verdict.signs[0].confidence == 0.0


def test_confidence_is_clamped():
    verdict = parse_verdict('{"signs": [{"type": "camera_housing", "confidence": 4}]}')

    assert verdict.signs[0].confidence == 1.0


def test_an_unreadable_reply_is_an_error_not_an_empty_frame():
    """"No JSON came back" and "there is no sign in this photo" are opposite
    findings, and collapsing them would report a broken run as a clean one."""
    assert parse_verdict("the image shows a road").error == "no JSON in response"
    assert parse_verdict("").error == "empty response"


def test_the_prompt_lists_only_the_requested_types():
    """--types narrows what is looked for, so the catalogue the model is
    shown has to narrow with it."""
    prompt = build_prompt(["camera_housing"])

    assert "camera_housing" in prompt
    assert "speed_limit" not in prompt


def test_the_prompt_says_that_finding_nothing_is_normal():
    """Most candidate frames are false alarms from the cheap pass, and a
    model that feels obliged to find something will find it."""
    assert "common case" in build_prompt()


def test_the_cache_is_keyed_on_the_photo_not_its_path(tmp_path):
    """Frames get re-exported and folders get renamed. Re-running over the
    same pixels in a new folder must not pay for them twice."""
    first = _photo(tmp_path / "a.jpg")
    elsewhere = tmp_path / "renamed"
    elsewhere.mkdir()
    copy = elsewhere / "b.jpg"
    copy.write_bytes(first.read_bytes())

    assert frame_fingerprint(first) == frame_fingerprint(copy)


def test_the_cache_misses_when_the_model_changes(tmp_path):
    """Two models' answers are two different measurements. Mixing them in
    one table would be undetectable after the fact."""
    cache = VerdictCache(tmp_path / "cache.json")
    cache.put("abc", "claude-haiku-4-5", FrameVerdict(scene="a road"))

    assert cache.get("abc", "claude-haiku-4-5") is not None
    assert cache.get("abc", "claude-sonnet-5") is None


def test_a_failed_call_is_never_cached(tmp_path):
    """Caching a failure would make the retry that fixes it impossible
    without deleting the file."""
    cache = VerdictCache(tmp_path / "cache.json")
    cache.put("abc", "m", FrameVerdict(error="Overloaded"))

    assert cache.get("abc", "m") is None
    assert len(cache) == 0


def test_the_cache_survives_a_reload(tmp_path):
    path = tmp_path / "cache.json"
    cache = VerdictCache(path)
    cache.put("abc", "m", FrameVerdict(scene="a road"))
    cache.save()

    reloaded = VerdictCache(path)

    assert reloaded.get("abc", "m").scene == "a road"
    assert reloaded.get("abc", "m").cached is True


def test_a_corrupt_cache_file_is_ignored_rather_than_fatal(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")

    assert len(VerdictCache(path)) == 0


def test_identify_answers_from_the_cache_without_calling(tmp_path):
    photo = _photo(tmp_path / "frame.jpg")
    cache = VerdictCache(tmp_path / "cache.json")
    client = _replying('{"signs": [], "scene": "unused"}')
    identify(client, photo, model="m", cache=cache)
    assert client.messages.create.call_count == 1

    again = identify(client, photo, model="m", cache=cache)

    assert client.messages.create.call_count == 1
    assert again.cached is True


def test_identify_sends_the_image_as_base64(tmp_path):
    photo = _photo(tmp_path / "frame.jpg")
    client = _replying('{"signs": [{"type": "speed_limit", "confidence": 0.9, "limit_mph": 30}], "scene": "a street"}')

    verdict = identify(client, photo, model="m")

    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert sent[0]["type"] == "image"
    assert sent[0]["source"]["media_type"] == "image/jpeg"
    assert sent[0]["source"]["data"]
    assert verdict.signs[0].limit_mph == 30


def test_a_frame_that_will_not_open_is_reported_not_raised(tmp_path):
    broken = tmp_path / "frame.jpg"
    broken.write_bytes(b"this is not an image")

    verdict = identify(_replying("{}"), broken, model="m")

    assert verdict.error == "could not be opened"


def test_large_frames_are_shrunk_before_sending(tmp_path):
    """An image is billed by its area, and a 4K frame costs several times a
    1024px one to say the same thing about."""
    big = _photo(tmp_path / "big.jpg", size=(3840, 2160))

    data, _ = encode_frame(big, max_dim=1024)

    import base64, io

    with Image.open(io.BytesIO(base64.b64decode(data))) as sent:
        assert max(sent.size) == 1024


def test_enforcement_types_are_a_subset_of_the_vocabulary():
    """The two lists are edited by hand and read together; a typo in one
    would silently drop a category out of the enforcement count."""
    assert vision.ENFORCEMENT_TYPES <= set(vision.SIGN_TYPES)


def test_identify_defaults_to_the_bulk_model_tier():
    """One call per candidate frame over a whole drive is exactly the shape
    the cheap tier exists for."""
    import inspect

    assert inspect.signature(identify).parameters["model"].default == llm.DEFAULT_EXTRACTION_MODEL
