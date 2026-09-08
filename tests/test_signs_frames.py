from pathlib import Path

from thesis_tools.signs.frames import discover_frames, frame_number, sequence_key


def _make(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not really a jpeg")


def test_frames_are_ordered_by_number_not_by_name(tmp_path):
    """frame_2 comes before frame_10. Plain string sorting says otherwise,
    and every sighting downstream depends on capture order being right."""
    _make(tmp_path, "frame_1.jpg", "frame_2.jpg", "frame_10.jpg", "frame_20.jpg")

    frames = discover_frames(tmp_path)

    assert [f.path.name for f in frames] == [
        "frame_1.jpg",
        "frame_2.jpg",
        "frame_10.jpg",
        "frame_20.jpg",
    ]
    assert [f.index for f in frames] == [1, 2, 10, 20]


def test_a_folder_per_video_becomes_a_sequence_per_video(tmp_path):
    """The export shape people get from ffmpeg run once per file."""
    _make(tmp_path, "a12/frame_00001.jpg", "a12/frame_00002.jpg", "m1/frame_00001.jpg")

    frames = discover_frames(tmp_path)

    assert {f.sequence for f in frames} == {"a12", "m1"}
    assert [f.position for f in frames if f.sequence == "a12"] == [0, 1]
    # Each video's frames are numbered from its own start, so position must
    # restart too — otherwise the second video's first frame looks like a
    # continuation of the first.
    assert [f.position for f in frames if f.sequence == "m1"] == [0]


def test_a_flat_folder_splits_on_the_name_before_the_counter(tmp_path):
    """The other export shape: everything in one folder, prefixed."""
    _make(tmp_path, "a12_000123.jpg", "a12_000124.jpg", "m25_000001.jpg")

    frames = discover_frames(tmp_path)

    assert {f.sequence for f in frames} == {"a12", "m25"}


def test_the_counter_is_the_last_number_in_the_name(tmp_path):
    """A date in the file name must not be mistaken for the frame number."""
    assert frame_number("2024-05-01_frame_000123.jpg") == 123
    assert frame_number("frame.jpg") is None


def test_unnumbered_photos_keep_their_alphabetical_position(tmp_path):
    """Phone photos have no counter. They still need a stable order."""
    _make(tmp_path, "beta.jpg", "alpha.jpg")

    frames = discover_frames(tmp_path)

    assert [f.path.name for f in frames] == ["alpha.jpg", "beta.jpg"]
    assert [f.index for f in frames] == [0, 1]


def test_sampling_counts_within_each_video_not_across_them(tmp_path):
    """One frame in three of a long drive must not consume the quota of a
    short one that follows it."""
    _make(tmp_path, *[f"a/frame_{i:03d}.jpg" for i in range(6)], "b/frame_000.jpg", "b/frame_001.jpg")

    frames = discover_frames(tmp_path, every=3)

    assert [(f.sequence, f.position) for f in frames] == [("a", 0), ("a", 3), ("b", 0)]


def test_non_images_are_ignored(tmp_path):
    _make(tmp_path, "frame_001.jpg", "notes.txt", "video.mp4")

    assert [f.path.name for f in discover_frames(tmp_path)] == ["frame_001.jpg"]


def test_sequence_key_falls_back_to_the_folder_name(tmp_path):
    """A flat folder of unnumbered photos is still one named drive, not an
    empty string that would print as a blank column."""
    photos = tmp_path / "sunday-drive"
    photos.mkdir()
    assert sequence_key(photos / "photo.jpg", photos) == "sunday-drive"
