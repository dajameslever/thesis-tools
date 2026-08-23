"""Shared helper for the optional Claude-powered features (nicer paper
summaries, sub-question generation, stance classification).

Everything that uses this is optional: if `anthropic` isn't installed or
ANTHROPIC_API_KEY isn't set, callers fall back to their non-LLM heuristics
rather than failing.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from . import env as _env

# Shared register instruction for every prompt that produces text destined
# for a report or draft a student might paste into their thesis. Appended
# (not prepended) to each system prompt so the task-specific rules are read
# first and this reads as a closing style constraint.
ACADEMIC_STYLE_NOTE = (
    "Style: formal academic register throughout. Third person only — never "
    "'I', 'you', or 'we' (an exception: 'we' is fine when quoting or "
    "paraphrasing what a paper's own authors say about their own study). No "
    "contractions. No casual connectives ('So,', 'Also,', 'Basically,'). "
    "Hedge claims the way published research does ('suggests', 'indicates', "
    "'appears to') rather than asserting them as settled fact."
)


def availability_issue() -> Optional[str]:
    """None if Claude is ready to use right now; otherwise a short, human
    reason it isn't. Callers that loop over many items (papers, sub-
    questions) should check this ONCE up front and print a single notice,
    rather than letting get_client() print the same warning on every item.
    """
    _env.load_dotenv_once()  # picks up a local .env's ANTHROPIC_API_KEY, if any
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY not set"
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return "the `anthropic` package isn't installed (pip install anthropic)"
    return None


def get_client(quiet: bool = False):
    """Return an `anthropic.Anthropic` client, or None if unavailable.

    Prints a one-line reason to stderr (unless quiet=True) so individual
    callers don't need to duplicate that messaging. Pass quiet=True when
    calling this per-item in a loop — pair it with a single upfront
    availability_issue() check instead, so the user sees one clear notice
    instead of the same warning repeated for every paper.
    """
    issue = availability_issue()
    if issue:
        if not quiet:
            print(f"  [llm] {issue}, falling back to non-LLM behavior", file=sys.stderr)
        return None
    import anthropic

    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def ask(client, system: str, user: str, model: str = "claude-sonnet-5", max_tokens: int = 300) -> Optional[str]:
    """Single-turn request. Returns the text response, or None on any failure."""
    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text").strip()
        return text or None
    except Exception as exc:
        print(f"  [llm] request failed ({exc})", file=sys.stderr)
        return None
