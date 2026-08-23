"""Minimal local .env support — just enough to let ANTHROPIC_API_KEY be set
once and reused across runs, without a new dependency.

Deliberately NOT the same file as the shared project state
(thesis_tools_project.json): that file is meant to be inspected, diffed, and
potentially committed/shared; a secret has no business in it. `.env` is
already listed in .gitignore, so it's the right place for this instead.
"""

from __future__ import annotations

import os
from pathlib import Path

_loaded = False


def load_dotenv_once(path: str = ".env") -> None:
    """Read KEY=VALUE lines from `path` into os.environ, without overriding
    anything already set there. Safe to call repeatedly — only reads the
    file once per process."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    p = Path(path)
    if not p.is_file():
        return
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def save_to_dotenv(key: str, value: str, path: str = ".env") -> None:
    """Write/replace a single KEY=VALUE line in `path`, preserving everything
    else already there."""
    p = Path(path)
    existing = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []

    lines = []
    replaced = False
    for line in existing:
        if line.strip().startswith(f"{key}="):
            lines.append(f"{key}={value}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append(f"{key}={value}")

    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
