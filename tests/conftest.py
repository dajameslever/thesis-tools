"""Test-wide guards against writing into the working copy.

The search log defaults to a path relative to the current directory, so any
test that runs topic-finder without chdir-ing first appends to the repo's own
`output/search-log.csv` — and did, for 396 rows across two commits before it
was spotted. Ignoring the file in git stops it being committed; this stops it
being written at all, which is the part that matters when the "working copy"
belongs to a user with a real log in it.
"""

import pytest

from thesis_tools import search_log


@pytest.fixture(autouse=True)
def _isolate_search_log(tmp_path, monkeypatch):
    """Point the default search log somewhere disposable for every test.

    A test that cares about the log passes an explicit path and is unaffected;
    a test that does not care no longer scribbles on whatever is in the
    current directory.
    """
    monkeypatch.setattr(
        search_log, "DEFAULT_SEARCH_LOG_PATH", str(tmp_path / "search-log.csv")
    )
