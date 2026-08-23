from thesis_tools.links import doi_url, google_scholar_search_url, sciencedirect_search_url
from thesis_tools.recency import age_years, newest_year, recency_label


def test_google_scholar_search_url_encodes_query():
    url = google_scholar_search_url("sleep deprivation & cognition")
    assert url.startswith("https://scholar.google.com/scholar?q=")
    assert "sleep" in url and "%26" in url  # '&' is URL-encoded, not a param separator


def test_sciencedirect_search_url_encodes_query():
    url = sciencedirect_search_url("adolescent decision making")
    assert url.startswith("https://www.sciencedirect.com/search?qs=")
    assert "adolescent" in url


def test_doi_url():
    assert doi_url("10.1234/x") == "https://doi.org/10.1234/x"


def test_age_years():
    assert age_years(2015, as_of=2025) == 10
    assert age_years(None) is None
    assert age_years(2030, as_of=2025) == 0  # never negative


def test_newest_year():
    assert newest_year([2010, None, 2021, 2005]) == 2021
    assert newest_year([None, None]) is None


def test_recency_label_unknown_year():
    assert "unknown" in recency_label(None).lower()


def test_recency_label_recent_vs_older():
    recent = recency_label(2024, newest_year_in_set=2024)
    older = recency_label(2005, newest_year_in_set=2024, old_threshold=10)
    assert "🆕" in recent
    assert "🕰️" in older
    assert "behind" in older
