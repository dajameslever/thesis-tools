"""The exemplar measurer's input paths.

`scripts/measure_exemplar.py` is a standalone script rather than part of the
package, so it is loaded here by path. What is worth testing about it is not
the arithmetic — that is visible in its output — but that a chapter reaches
it at all: as a PDF, as a text file, or pasted on stdin, which is how most
exemplars actually arrive.
"""

import importlib.util
import io
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_exemplar.py"
_spec = importlib.util.spec_from_file_location("measure_exemplar", _SCRIPT)
measure_exemplar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure_exemplar)


CHAPTER = """2. Literature Review

Recent work frames urban citizenship as a "performative act" (Lepofsky and
Fraser, 2003), enacted rather than conferred, and reads citizenship as
"what we owe, as much as what we expect", which relocates the argument from
entitlement to obligation (Smith, 2011). The "right to the city" travels
badly into instruments that assume a register of persons; the "right to the
city" is claimed by occupation rather than by paperwork; the "right to the
city" is a practice and not a status.

3. Methodology

This chapter sets out the case selection and the interview frame.
"""


def _run(argv, capsys):
    assert measure_exemplar.main(argv) == 0
    return capsys.readouterr().out


def test_reads_a_text_file(tmp_path, capsys):
    path = tmp_path / "chapter.txt"
    path.write_text(CHAPTER, encoding="utf-8")

    out = _run([str(path)], capsys)

    assert str(path) in out
    assert "pages" not in out  # nothing to page through
    assert "what we owe, as much as what we expect" not in out  # needs --show-quotes


def test_reads_pasted_text_from_stdin(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(CHAPTER))

    out = _run(["--show-quotes"], capsys)

    assert "pasted text" in out
    assert "what we owe, as much as what we expect" in out


def test_a_dash_also_means_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(CHAPTER))

    assert "pasted text" in _run(["-"], capsys)


def test_empty_paste_says_so(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))

    with pytest.raises(SystemExit) as caught:
        measure_exemplar.main([])

    assert "stdin" in str(caught.value)


def test_find_slices_within_pasted_text(capsys, monkeypatch):
    """Page granularity would take the whole paste, methodology included."""
    monkeypatch.setattr("sys.stdin", io.StringIO(CHAPTER))

    out = _run(["--find", "Literature Review"], capsys)
    words = int(out.split("section length        : ")[1].split()[0].replace(",", ""))

    assert "(Literature Review)" in out
    assert words < len(CHAPTER.split())  # the next chapter was left out


def test_find_reports_a_heading_it_cannot_locate(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(CHAPTER))

    with pytest.raises(SystemExit) as caught:
        measure_exemplar.main(["--find", "Discussion"])

    assert "Discussion" in str(caught.value)


def test_pages_needs_page_breaks(tmp_path):
    path = tmp_path / "chapter.txt"
    path.write_text(CHAPTER, encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        measure_exemplar.main([str(path), "--pages", "1-2"])

    assert "--pages" in str(caught.value)


def test_form_feeds_in_text_count_as_pages(tmp_path, capsys):
    path = tmp_path / "chapter.txt"
    path.write_text(CHAPTER.replace("3. Methodology", "\f3. Methodology"), encoding="utf-8")

    out = _run([str(path), "--pages", "1"], capsys)

    assert "(pages 1-1)" in out
    assert "Methodology" not in out


def test_missing_file_is_not_a_traceback(tmp_path):
    with pytest.raises(SystemExit) as caught:
        measure_exemplar.main([str(tmp_path / "nope.txt")])

    assert "Couldn't read" in str(caught.value)


def test_a_repeated_phrase_is_vocabulary_not_quotation(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(CHAPTER))

    out = _run(["--show-quotes"], capsys)

    assert "counted as vocabulary" in out
    assert "'right to the city'" in out
