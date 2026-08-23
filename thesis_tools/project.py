"""Shared project state.

Field, working title, research question, sub-questions, citation style, and
Claude preferences carry across Part 1 (Topic Finder), Part 2 (Library
Indexer), and Part 3 (Literature Review) via a small JSON file — so you
answer these once, and each part only asks again for whatever is still
missing. Each part also records where its own output lives (the topic
search's paper cache, the library index) so Part 3 can find them without
being told.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from dataclasses import field as _field
from pathlib import Path
from typing import List, Optional

DEFAULT_PROJECT_PATH = "thesis_tools_project.json"


@dataclass
class ProjectState:
    field: Optional[str] = None
    working_title: Optional[str] = None
    research_question: Optional[str] = None
    sub_questions: List[str] = _field(default_factory=list)
    style: Optional[str] = None
    contact_email: Optional[str] = None
    use_llm: bool = False
    llm_model: str = "claude-sonnet-5"
    # Where Part 1/2's own output landed, so Part 3 can find it unprompted.
    last_topic_cache: Optional[str] = None
    last_library_index: Optional[str] = None

    @classmethod
    def load(cls, path: str) -> "ProjectState":
        p = Path(path)
        if not p.is_file():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: str) -> None:
        p = Path(path)
        if p.parent != Path("."):
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    def updated(self, **changes) -> "ProjectState":
        """Return a new ProjectState with `changes` applied on top — but only
        for values that are actually present (not None/empty), so calling
        this with a command's resolved inputs never erases something the
        project already knew that this particular run didn't touch."""
        data = asdict(self)
        for key, value in changes.items():
            if value is None or value == "" or value == []:
                continue
            data[key] = value
        return ProjectState(**data)
