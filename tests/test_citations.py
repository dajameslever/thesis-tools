from thesis_tools.citations import format_citation
from thesis_tools.sources.base import Paper


def make_paper(**overrides) -> Paper:
    defaults = dict(
        title="Deep Learning for Sleep Stage Classification",
        authors=["Jane A. Doe", "John B. Smith"],
        year=2021,
        venue="Journal of Sleep Research",
        doi="10.1234/jsr.2021.001",
        volume="30",
        issue="2",
        pages="100-110",
    )
    defaults.update(overrides)
    return Paper(**defaults)


def test_apa_contains_key_fields():
    citation = format_citation(make_paper(), "apa")
    assert "Doe, J." in citation
    assert "(2021)" in citation
    assert "Deep Learning for Sleep Stage Classification" in citation
    assert "Journal of Sleep Research" in citation
    assert "https://doi.org/10.1234/jsr.2021.001" in citation


def test_mla_quotes_title_and_uses_full_first_author_name():
    citation = format_citation(make_paper(), "mla")
    assert '"Deep Learning for Sleep Stage Classification."' in citation
    assert "Doe, Jane A." in citation
    assert "vol. 30" in citation
    assert "no. 2" in citation


def test_chicago_author_date_format():
    citation = format_citation(make_paper(), "chicago")
    assert citation.startswith("Doe, J.")
    assert "2021." in citation
    assert '"Deep Learning for Sleep Stage Classification."' in citation


def test_harvard_format():
    citation = format_citation(make_paper(), "harvard")
    assert "Doe, J." in citation
    assert "2021." in citation
    assert "pp.100-110" in citation


def test_ieee_format_with_ref_number():
    citation = format_citation(make_paper(), "ieee", ref_number=3)
    assert citation.startswith("[3]")
    assert "J. A. Doe" in citation
    assert '"Deep Learning for Sleep Stage Classification,"' in citation


def test_missing_metadata_does_not_crash():
    sparse = Paper(title="A Paper With No Metadata", authors=[])
    for style in ("apa", "mla", "chicago", "harvard", "ieee"):
        citation = format_citation(sparse, style)
        assert "A Paper With No Metadata" in citation
        assert "n.a." in citation  # no authors


def test_unknown_style_raises():
    import pytest

    with pytest.raises(ValueError):
        format_citation(make_paper(), "vancouver")
