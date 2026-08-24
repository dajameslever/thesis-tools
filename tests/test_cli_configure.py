import json

from thesis_tools.cli import main
from thesis_tools.project import ProjectState


def test_configure_non_interactive_sets_style_and_field(tmp_path, capsys):
    project_file = tmp_path / "project.json"
    rc = main([
        "configure",
        "--field", "Psychology",
        "--style", "ieee",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0
    assert project_file.is_file()

    state = ProjectState.load(str(project_file))
    assert state.field == "Psychology"
    assert state.style == "ieee"
    assert state.working_title is None  # untouched

    out = capsys.readouterr().out
    assert "IEEE" in out


def test_configure_show_does_not_modify_file(tmp_path, capsys):
    project_file = tmp_path / "project.json"
    ProjectState(field="Psychology", style="apa").save(str(project_file))
    before = project_file.read_text()

    rc = main(["configure", "--show", "--project-file", str(project_file)])
    assert rc == 0
    assert project_file.read_text() == before

    out = capsys.readouterr().out
    assert "Psychology" in out
    assert "APA" in out


def test_configure_non_interactive_preserves_existing_unset_flags(tmp_path):
    project_file = tmp_path / "project.json"
    ProjectState(field="Psychology", working_title="Old Title", style="mla").save(str(project_file))

    rc = main([
        "configure",
        "--style", "ieee",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    state = ProjectState.load(str(project_file))
    assert state.style == "ieee"
    assert state.field == "Psychology"  # untouched
    assert state.working_title == "Old Title"  # untouched


def test_configure_llm_toggle_persists_explicit_false(tmp_path):
    project_file = tmp_path / "project.json"
    ProjectState(use_llm=True).save(str(project_file))

    rc = main([
        "configure",
        "--no-llm-summaries",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    state = ProjectState.load(str(project_file))
    assert state.use_llm is False


def test_configure_sub_questions_are_split_on_semicolons(tmp_path):
    project_file = tmp_path / "project.json"
    rc = main([
        "configure",
        "--sub-questions", "Does A happen?;Does B happen?",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    state = ProjectState.load(str(project_file))
    assert state.sub_questions == ["Does A happen?", "Does B happen?"]


def test_topic_finder_non_interactive_uses_configured_field_and_title(tmp_path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"

    rc = main([
        "configure",
        "--field", "Psychology",
        "--title", "Sleep and Memory",
        "--style", "ieee",
        "--project-file", str(project_file),
        "--non-interactive",
    ])
    assert rc == 0

    with patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search", return_value=[]), \
         patch("thesis_tools.sources.openalex.OpenAlexClient.search", return_value=[]), \
         patch("thesis_tools.sources.crossref.CrossrefClient.search", return_value=[]), \
         patch("thesis_tools.sources.arxiv.ArxivClient.search", return_value=[]):
        rc = main(["topic-finder", "--project-file", str(project_file), "--non-interactive"])
    assert rc == 0

    reports = list((tmp_path / "output").glob("*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert "**Field:** Psychology" in text
    assert "**Proposed working title:** Sleep and Memory" in text
    assert "**Citation style:** IEEE" in text


def test_topic_finder_explicit_llm_model_overrides_both_tiers(tmp_path, monkeypatch):
    """An explicit --llm-model must apply to sub-question generation AND the
    bulk per-paper work alike — the cheaper Haiku default for the latter is
    only the automatic choice when nothing was explicitly requested."""
    from unittest.mock import patch

    from thesis_tools.topic_finder import TopicFinderInputs

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"

    captured = {}
    original_init = TopicFinderInputs.__init__

    def _capture_init(self, *args, **kwargs):
        captured.update(kwargs)
        original_init(self, *args, **kwargs)

    with patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search", return_value=[]), \
         patch("thesis_tools.sources.openalex.OpenAlexClient.search", return_value=[]), \
         patch("thesis_tools.sources.crossref.CrossrefClient.search", return_value=[]), \
         patch("thesis_tools.sources.arxiv.ArxivClient.search", return_value=[]), \
         patch.object(TopicFinderInputs, "__init__", _capture_init):
        rc = main([
            "topic-finder",
            "--field", "Psychology",
            "--title", "Sleep and Memory",
            "--llm-model", "claude-opus-5",
            "--project-file", str(project_file),
        ])
    assert rc == 0
    assert captured["llm_model"] == "claude-opus-5"
    assert captured["extraction_llm_model"] == "claude-opus-5"


def test_topic_finder_default_model_tiers_without_explicit_override(tmp_path, monkeypatch):
    from unittest.mock import patch

    from thesis_tools.topic_finder import TopicFinderInputs

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"

    captured = {}
    original_init = TopicFinderInputs.__init__

    def _capture_init(self, *args, **kwargs):
        captured.update(kwargs)
        original_init(self, *args, **kwargs)

    with patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search", return_value=[]), \
         patch("thesis_tools.sources.openalex.OpenAlexClient.search", return_value=[]), \
         patch("thesis_tools.sources.crossref.CrossrefClient.search", return_value=[]), \
         patch("thesis_tools.sources.arxiv.ArxivClient.search", return_value=[]), \
         patch.object(TopicFinderInputs, "__init__", _capture_init):
        rc = main([
            "topic-finder",
            "--field", "Psychology",
            "--title", "Sleep and Memory",
            "--project-file", str(project_file),
        ])
    assert rc == 0
    assert captured["llm_model"] == "claude-sonnet-5"
    assert captured["extraction_llm_model"] == "claude-haiku-4-5"


def test_topic_finder_library_index_path_defaults_and_override(tmp_path, monkeypatch):
    """--download-papers's library indexing defaults to library/index.json,
    reuses whatever index-library last wrote to once that's known, and an
    explicit --library-index-path always wins over both."""
    from unittest.mock import patch

    from thesis_tools.topic_finder import TopicFinderInputs

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"

    captured = {}
    original_init = TopicFinderInputs.__init__

    def _capture_init(self, *args, **kwargs):
        captured.update(kwargs)
        original_init(self, *args, **kwargs)

    def _run(extra_args):
        with patch("thesis_tools.sources.semantic_scholar.SemanticScholarClient.search", return_value=[]), \
             patch("thesis_tools.sources.openalex.OpenAlexClient.search", return_value=[]), \
             patch("thesis_tools.sources.crossref.CrossrefClient.search", return_value=[]), \
             patch("thesis_tools.sources.arxiv.ArxivClient.search", return_value=[]), \
             patch.object(TopicFinderInputs, "__init__", _capture_init):
            return main([
                "topic-finder",
                "--field", "Psychology",
                "--title", "Sleep and Memory",
                "--project-file", str(project_file),
            ] + extra_args)

    # No prior project state, no explicit flag -> the plain default.
    assert _run([]) == 0
    assert captured["library_index_path"] == "library/index.json"

    # index-library already recorded where it wrote its index -> reuse that.
    project = ProjectState.load(str(project_file))
    project.updated(last_library_index="library/custom-index.json").save(str(project_file))
    assert _run([]) == 0
    assert captured["library_index_path"] == "library/custom-index.json"

    # An explicit --library-index-path always wins over both.
    assert _run(["--library-index-path", "elsewhere/index.json"]) == 0
    assert captured["library_index_path"] == "elsewhere/index.json"


def test_literature_review_defaults_stance_cache_next_to_the_library_index(tmp_path, monkeypatch):
    """Part 3 reads the same cache visualize-library writes, so the stance
    classification is not paid for twice."""
    import json
    from unittest.mock import patch

    from thesis_tools.literature_review import LiteratureReviewInputs

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"
    index_path = tmp_path / "library" / "index.json"
    index_path.parent.mkdir()
    index_path.write_text(
        json.dumps({"version": 1, "entries": [{
            "paper": {"title": "Sleep and decision-making", "authors": ["Jane Doe"], "year": 2020,
                      "doi": "10.1/a", "abstract": "A significant effect of sleep on decision-making."},
            "doi": "10.1/a", "confidence": "verified-doi", "file_path": "/x/a.pdf", "file_hash": "h",
            "file_type": "pdf", "size_bytes": 1, "indexed_at": "2026-01-01T00:00:00", "references": [],
        }]}),
        encoding="utf-8",
    )

    captured = {}
    real_run = None

    def _capture(inputs):
        captured["stance_cache_path"] = inputs.stance_cache_path
        captured["extraction_llm_model"] = inputs.extraction_llm_model
        return str(tmp_path / "review.md")

    with patch("thesis_tools.cli.run_literature_review", side_effect=_capture):
        rc = main([
            "literature-review",
            "--field", "Psychology",
            "--title", "Sleep and decision-making",
            "--question", "Does sleep affect decision-making?",
            "--sub-questions", "Does sleep affect decision-making?",
            "--library-index", str(index_path),
            "--project-file", str(project_file),
            "--non-interactive",
        ])

    assert rc == 0
    assert captured["stance_cache_path"] == str(tmp_path / "library" / "stance_cache.json")
    assert captured["extraction_llm_model"] == "claude-haiku-4-5"


def test_literature_review_no_stance_cache_disables_reuse(tmp_path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"
    cache_path = tmp_path / "report.md.papers.json"
    cache_path.write_text('{"sources_used": [], "papers": [{"title": "A", "authors": [], "year": 2020}]}', encoding="utf-8")

    captured = {}
    with patch("thesis_tools.cli.run_literature_review", side_effect=lambda i: (captured.update(p=i.stance_cache_path), "x.md")[1]):
        rc = main([
            "literature-review",
            "--field", "X", "--title", "Y",
            "--sub-questions", "Does X happen?",
            "--topic-cache", str(cache_path),
            "--project-file", str(project_file),
            "--no-stance-cache",
            "--non-interactive",
        ])

    assert rc == 0
    assert captured["p"] is None


def test_literature_review_explicit_llm_model_applies_to_classification_too(tmp_path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    project_file = tmp_path / "thesis_tools_project.json"
    cache_path = tmp_path / "report.md.papers.json"
    cache_path.write_text('{"sources_used": [], "papers": [{"title": "A", "authors": [], "year": 2020}]}', encoding="utf-8")

    captured = {}

    def _capture(inputs):
        captured["llm_model"] = inputs.llm_model
        captured["extraction_llm_model"] = inputs.extraction_llm_model
        return "x.md"

    with patch("thesis_tools.cli.run_literature_review", side_effect=_capture):
        rc = main([
            "literature-review",
            "--field", "X", "--title", "Y",
            "--sub-questions", "Does X happen?",
            "--topic-cache", str(cache_path),
            "--project-file", str(project_file),
            "--llm-model", "claude-opus-5",
            "--non-interactive",
        ])

    assert rc == 0
    assert captured["llm_model"] == "claude-opus-5"
    assert captured["extraction_llm_model"] == "claude-opus-5"


def test_literature_review_writes_html_alongside_markdown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cache_path = tmp_path / "report.md.papers.json"
    cache_path.write_text(json.dumps({"sources_used": [], "papers": [{
        "title": "Digital transformation reduces environmental impact", "authors": ["Ada Lovelace"],
        "year": 2023, "doi": "10.1/a",
        "abstract": "We find a significant effect of digital transformation on environmental impact, consistent with theory.",
    }]}), encoding="utf-8")

    rc = main([
        "literature-review",
        "--field", "Digital Transformation",
        "--title", "DT and sustainability",
        "--question", "Does digital transformation reduce environmental impact?",
        "--sub-questions", "Does digital transformation reduce environmental impact?",
        "--topic-cache", str(cache_path),
        "--project-file", str(tmp_path / "project.json"),
        "--output", str(tmp_path / "review.md"),
        "--no-llm", "--non-interactive",
    ])

    assert rc == 0
    assert (tmp_path / "review.md").is_file()
    assert (tmp_path / "review.html").is_file()


def test_literature_review_no_html_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cache_path = tmp_path / "report.md.papers.json"
    cache_path.write_text(json.dumps({"sources_used": [], "papers": [{
        "title": "A paper about X", "authors": ["Ada Lovelace"], "year": 2023, "doi": "10.1/a",
        "abstract": "A significant effect of X on Y, consistent with theory.",
    }]}), encoding="utf-8")

    rc = main([
        "literature-review",
        "--field", "X", "--title", "Y",
        "--question", "Does X affect Y?",
        "--sub-questions", "Does X affect Y?",
        "--topic-cache", str(cache_path),
        "--project-file", str(tmp_path / "project.json"),
        "--output", str(tmp_path / "review.md"),
        "--no-html", "--no-llm", "--non-interactive",
    ])

    assert rc == 0
    assert (tmp_path / "review.md").is_file()
    assert not (tmp_path / "review.html").exists()


def test_literature_review_words_per_question_flag(tmp_path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    cache_path = tmp_path / "report.md.papers.json"
    cache_path.write_text('{"sources_used": [], "papers": [{"title": "A", "authors": [], "year": 2020}]}', encoding="utf-8")

    captured = {}
    with patch("thesis_tools.cli.run_literature_review",
               side_effect=lambda i: (captured.update(w=i.words_per_question), "x.md")[1]):
        rc = main([
            "literature-review",
            "--field", "X", "--title", "Y",
            "--sub-questions", "Does X happen?",
            "--topic-cache", str(cache_path),
            "--project-file", str(tmp_path / "project.json"),
            "--words-per-question", "1800",
            "--non-interactive",
        ])

    assert rc == 0
    assert captured["w"] == 1800
