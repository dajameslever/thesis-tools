import os
import time
from pathlib import Path

from thesis_tools.outputs import (
    PREVIOUS_DIR_NAME,
    archive_existing,
    is_kept_location,
    write_output,
    write_view,
)


def test_first_write_has_nothing_to_keep(tmp_path):
    assert write_output(tmp_path / "viz.html", "v1") is None
    assert (tmp_path / "viz.html").read_text() == "v1"
    assert not (tmp_path / PREVIOUS_DIR_NAME).exists()


def test_the_previous_version_survives_the_next_run(tmp_path):
    """The reported problem: re-running to change one flag destroyed the
    version you were comparing against."""
    path = tmp_path / "viz.html"
    write_output(path, "v1")
    archived = write_output(path, "v2")

    assert path.read_text() == "v2"  # the canonical name still points at the new one
    assert archived is not None and archived.read_text() == "v1"
    assert archived.parent == tmp_path / PREVIOUS_DIR_NAME


def test_every_run_accumulates_rather_than_replacing_the_archive(tmp_path):
    path = tmp_path / "report.md"
    for i in range(4):
        write_output(path, f"v{i}")

    kept = sorted(p.read_text() for p in (tmp_path / PREVIOUS_DIR_NAME).iterdir())
    assert kept == ["v0", "v1", "v2"]
    assert path.read_text() == "v3"


def test_two_runs_in_the_same_second_do_not_collide(tmp_path):
    """Names come from the file's own timestamp, so back-to-back runs would
    otherwise land on the same name and lose the first — the exact thing
    this is here to prevent."""
    path = tmp_path / "viz.html"
    write_output(path, "v1")
    write_output(path, "v2")
    write_output(path, "v3")

    assert len(list((tmp_path / PREVIOUS_DIR_NAME).iterdir())) == 2


def test_the_archive_is_named_for_when_the_file_was_written(tmp_path):
    """Not for when it was pushed aside — that is what makes the folder
    readable as a history of runs."""
    path = tmp_path / "viz.html"
    path.write_text("old")
    old_mtime = time.time() - 86_400  # yesterday
    os.utime(path, (old_mtime, old_mtime))

    archived = archive_existing(path)

    stamp = time.strftime("%Y%m%d", time.localtime(old_mtime))
    assert stamp in archived.name
    assert time.strftime("%Y%m%d") not in archived.name


def test_archiving_a_missing_file_is_a_no_op(tmp_path):
    assert archive_existing(tmp_path / "never-written.html") is None


def test_a_failed_archive_does_not_block_this_run(tmp_path, monkeypatch, capsys):
    """Refusing to produce this run's output because last run's could not be
    filed away would be the worse outcome."""
    path = tmp_path / "viz.html"
    path.write_text("v1")

    def _boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr("thesis_tools.outputs.shutil.move", _boom)
    assert write_output(path, "v2") is None
    assert path.read_text() == "v2"
    assert "couldn't keep the previous" in capsys.readouterr().err


def test_write_output_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "review.md"
    write_output(path, "v1")
    assert path.read_text() == "v1"


def test_where_the_file_lands_decides_the_rule_not_who_wrote_it(tmp_path):
    """"Anything in output is kept" is a rule you can predict from the path.
    "The review is kept and the visualization is not" is one you have to
    remember per command — and it breaks the moment you point one command at
    the other's folder."""
    assert is_kept_location(tmp_path / "output" / "review.md")
    assert is_kept_location(tmp_path / "output" / "nested" / "review.md")
    assert not is_kept_location(tmp_path / "library" / "visualization.html")
    assert not is_kept_location(tmp_path / "outputs" / "review.md")  # not the same folder


def test_a_living_view_is_overwritten_in_its_own_folder(tmp_path):
    path = tmp_path / "library" / "visualization.html"
    write_view(path, "v1")
    assert write_view(path, "v2") is None

    assert path.read_text() == "v2"
    assert not (path.parent / PREVIOUS_DIR_NAME).exists()


def test_a_living_view_pointed_at_output_is_kept_like_everything_there(tmp_path):
    """The reported problem: a visualization written into output/ was
    silently overwritten, because the rule was implemented per command
    instead of per location."""
    path = tmp_path / "output" / "visualization.html"
    write_view(path, "v1")
    archived = write_view(path, "v2")

    assert path.read_text() == "v2"
    assert archived is not None and archived.read_text() == "v1"


def test_documents_are_kept_wherever_they_are_written(tmp_path):
    """The converse is not symmetric: a document is a document even outside
    output/, so -o pointing somewhere else must not silently lose one."""
    path = tmp_path / "elsewhere" / "draft.md"
    write_output(path, "v1")
    archived = write_output(path, "v2")

    assert archived is not None and archived.read_text() == "v1"
