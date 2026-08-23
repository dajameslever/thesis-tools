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


def get_client(quiet: bool = False):
    """Return an `anthropic.Anthropic` client, or None if unavailable.

    Prints a one-line reason to stderr (unless quiet=True) so individual
    callers don't need to duplicate that messaging.
    """
    _env.load_dotenv_once()  # picks up a local .env's ANTHROPIC_API_KEY, if any
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        if not quiet:
            print("  [llm] ANTHROPIC_API_KEY not set, falling back to non-LLM behavior", file=sys.stderr)
        return None
    try:
        import anthropic
    except ImportError:
        if not quiet:
            print("  [llm] `anthropic` package not installed (pip install anthropic), falling back", file=sys.stderr)
        return None
    return anthropic.Anthropic(api_key=api_key)


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
