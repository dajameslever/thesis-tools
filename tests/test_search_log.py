import csv
import datetime as _dt

from thesis_tools.search_log import (
    COLUMNS,
    append_searches,
    read_log,
    terms_already_searched,
)

_ROWS = [("travel planning", "semanticscholar", 8), ("travel planning", "arxiv", 0)]


def test_a_first_run_writes_a_header_and_its_rows(tmp_path):
    path = tmp_path / "search-log.csv"
    assert append_searches(_ROWS, str(path), report_path="output/report.md") == path

    with path.open() as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == COLUMNS
    assert len(rows) == 3
    assert rows[1][1:] == ["travel planning", "semanticscholar", "8", "output/report.md"]


def test_the_log_accumulates_rather_than_being_replaced(tmp_path):
    """A search log that gets replaced on each run is not a log — the whole
    point is the rows that came before."""
    path = tmp_path / "search-log.csv"
    append_searches(_ROWS, str(path))
    append_searches([("agentic booking", "crossref", 3)], str(path))

    logged = read_log(str(path))
    assert len(logged) == 3
    assert [r["Search term"] for r in logged][-1] == "agentic booking"
    # One header, not one per run.
    assert path.read_text().count("Search term") == 1


def test_a_zero_result_search_is_still_recorded(tmp_path):
    """Knowing a term returned nothing is exactly the kind of thing a log
    exists to stop you rediscovering."""
    path = tmp_path / "search-log.csv"
    append_searches([("obscure term", "arxiv", 0)], str(path))
    assert read_log(str(path))[0]["Results"] == "0"


def test_nothing_searched_writes_nothing(tmp_path):
    """A reanalyze run searches nothing and must not leave a row saying it
    did."""
    path = tmp_path / "search-log.csv"
    assert append_searches([], str(path)) is None
    assert not path.exists()


def test_the_date_is_recorded_per_run(tmp_path):
    path = tmp_path / "search-log.csv"
    when = _dt.datetime(2026, 3, 4, 9, 30)
    append_searches(_ROWS, str(path), when=when)
    assert read_log(str(path))[0]["Date"] == "2026-03-04 09:30"


def test_terms_already_searched_is_distinct_and_most_recent_first(tmp_path):
    path = tmp_path / "search-log.csv"
    append_searches([("first term", "crossref", 1)], str(path))
    append_searches([("second term", "crossref", 1), ("second term", "arxiv", 0)], str(path))
    append_searches([("first term", "openalex", 2)], str(path))

    assert terms_already_searched(str(path)) == ["first term", "second term"]


def test_reading_a_log_that_does_not_exist_yet_is_not_an_error(tmp_path):
    assert read_log(str(tmp_path / "nothing.csv")) == []
    assert terms_already_searched(str(tmp_path / "nothing.csv")) == []


def test_a_failed_write_does_not_lose_the_run(tmp_path, monkeypatch, capsys):
    """The search already happened and already cost API calls; failing to
    log it must not raise."""
    path = tmp_path / "search-log.csv"

    def _boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr("thesis_tools.search_log.Path.mkdir", _boom)
    assert append_searches(_ROWS, str(path)) is None
    assert "couldn't write" in capsys.readouterr().err


def test_the_default_log_path_is_isolated_during_tests(tmp_path):
    """A test that runs topic-finder without chdir-ing first would otherwise
    append to the repo's own output/search-log.csv — and did, for 396 rows,
    before conftest.py started redirecting the default."""
    from thesis_tools import search_log

    assert "/tmp" in search_log.DEFAULT_SEARCH_LOG_PATH or "pytest" in search_log.DEFAULT_SEARCH_LOG_PATH
    assert search_log.DEFAULT_SEARCH_LOG_PATH != "output/search-log.csv"


def test_writing_with_no_path_given_lands_on_the_isolated_default():
    from pathlib import Path

    from thesis_tools import search_log

    written = append_searches([("a term", "crossref", 1)])
    assert written == Path(search_log.DEFAULT_SEARCH_LOG_PATH)
    assert not Path("output/search-log.csv").exists()
