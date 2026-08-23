from thesis_tools.project import ProjectState


def test_load_missing_file_returns_defaults(tmp_path):
    state = ProjectState.load(str(tmp_path / "does-not-exist.json"))
    assert state.field is None
    assert state.sub_questions == []


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "project.json"
    state = ProjectState(field="Psychology", working_title="T", research_question="Q?", sub_questions=["A?", "B?"])
    state.save(str(path))

    loaded = ProjectState.load(str(path))
    assert loaded == state


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "project.json"
    path.write_text('{"field": "Psychology", "totally_unknown_key": 123}', encoding="utf-8")
    loaded = ProjectState.load(str(path))
    assert loaded.field == "Psychology"


def test_load_corrupt_json_returns_defaults(tmp_path):
    path = tmp_path / "project.json"
    path.write_text("not json at all", encoding="utf-8")
    loaded = ProjectState.load(str(path))
    assert loaded.field is None


def test_updated_applies_only_non_empty_values():
    state = ProjectState(field="Psychology", working_title="Old Title", sub_questions=["A?"])
    updated = state.updated(working_title="New Title", research_question=None, sub_questions=[])
    assert updated.working_title == "New Title"
    assert updated.field == "Psychology"  # untouched
    assert updated.research_question is None  # was already None, stays None
    assert updated.sub_questions == ["A?"]  # empty update doesn't wipe existing value


def test_updated_does_not_mutate_original():
    state = ProjectState(field="Psychology")
    state.updated(field="Sociology")
    assert state.field == "Psychology"
