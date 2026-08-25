"""Shared helper for the optional Claude-powered features (nicer paper
summaries, sub-question generation, stance classification).

Everything that uses this is optional: if `anthropic` isn't installed or
ANTHROPIC_API_KEY isn't set, callers fall back to their non-LLM heuristics
rather than failing.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional

from . import env as _env

# Two model tiers, centralized here so every part of the toolkit picks from
# the same defaults instead of scattering literal model strings:
#   * DEFAULT_MODEL — one-shot, quality-sensitive calls: sub-question
#     generation, literature-review drafting. Worth the extra cost since
#     there's only ever one (or a handful) of these per run.
#   * DEFAULT_EXTRACTION_MODEL — bulk, per-paper calls: "what it's about"
#     summaries, sub-question stance classification. These run once per
#     paper (so N or N-times-the-sub-question-count calls per run) and are
#     closer to classification/extraction than to writing — Haiku's
#     speed/cost profile fits that far better than Sonnet or Opus, and is
#     the actual majority of a typical run's token spend.
# An explicit --llm-model always overrides both — these are just the
# automatic choice when the user hasn't named one.
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EXTRACTION_MODEL = "claude-haiku-4-5"

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


_SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*\s")


def _trim_to_last_sentence(text: str) -> str:
    """If a response got cut off mid-sentence by hitting max_tokens, trim it
    back to the last complete sentence rather than shipping a fragment like
    '...this apparent absence of disagreement should' straight into a draft.
    Falls back to the untrimmed text if no sentence boundary is found in a
    reasonable trailing portion — a short truncated answer is still better
    than an empty one."""
    matches = list(_SENTENCE_END_RE.finditer(text))
    if not matches:
        return text
    cutoff = matches[-1].end()
    # Only trim if it actually removes a trailing fragment, and doesn't
    # throw away most of the response (e.g. one long run-on sentence).
    if cutoff < len(text) and cutoff >= len(text) * 0.4:
        return text[:cutoff].rstrip()
    return text


# Past this, a non-streaming request risks an HTTP timeout waiting for the
# whole response to be generated before a single byte comes back, so the
# request is streamed and reassembled instead. Streaming costs nothing extra
# and behaves identically for short answers, so the threshold is only about
# not paying the timeout risk when there is no need.
STREAMING_MAX_TOKENS_THRESHOLD = 1500


# Prompt caching is a prefix match, and the minimum cacheable prefix is
# model-dependent — 1024 tokens on Sonnet 5, but 4096 on Haiku 4.5. A prefix
# under the minimum silently does not cache: no error, just no entry. Every
# system prompt in this toolkit is well under 1024 tokens on its own, so
# caching is only worth requesting where the *whole* prompt is large — which
# in practice means the literature-review drafting calls, whose prompts carry
# entire papers. See ask()'s `cache` argument.
def _usage_of(message) -> dict:
    usage = getattr(message, "usage", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def format_usage(totals: Dict[str, int]) -> Optional[str]:
    """One line describing what a run actually spent, or None if nothing was
    sent. Cache reads are the number that matters: a cache that only ever
    writes is 1.25x overhead paid for nothing, and the only way to tell the
    two apart is to look at the counters.
    """
    if not totals or not any(totals.values()):
        return None
    parts = [
        f"{totals.get('input_tokens', 0):,} input",
        f"{totals.get('output_tokens', 0):,} output",
    ]
    written = totals.get("cache_creation_input_tokens", 0)
    read = totals.get("cache_read_input_tokens", 0)
    if written or read:
        parts.append(f"{written:,} cache-write, {read:,} cache-read")
    return ", ".join(parts) + " tokens"


def ask(
    client,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 300,
    errors: Optional[List[str]] = None,
    cache: bool = False,
    cache_suffix: Optional[str] = None,
    usage_totals: Optional[Dict[str, int]] = None,
    meta: Optional[Dict[str, object]] = None,
) -> Optional[str]:
    """Single-turn request. Returns the text response, or None on any failure.

    Pass `errors` to have the reason for a failure appended to it. Returning
    a bare None is fine where the caller has a real fallback (a heuristic
    summary is a legitimate substitute for a Claude-written one), but where
    the fallback is markedly worse the caller needs to be able to say what
    went wrong rather than silently shipping the lesser output as though
    nothing had happened.

    `cache=True` asks the API to cache this prompt. That pays when the *same*
    prefix is sent again inside the five-minute TTL: re-running a draft while
    tuning it, which is the normal way this tool is used. It does not pay
    within a single run, where every call's prompt differs — a cache write
    costs 1.25x and is only recouped on a read — so callers should request it
    only where a repeat is likely and the prompt is big enough to matter.

    `cache_suffix` is text sent *after* the cache breakpoint. Caching is a
    prefix match, so anything that varies between otherwise-identical runs
    (a word-count target, a tweaked instruction) invalidates the entry if it
    sits inside the cached part. Putting those bits in `cache_suffix` keeps
    the expensive, stable part of the prompt — the papers — cacheable across
    a re-run that only changed a knob. With no suffix, a top-level
    `cache_control` places the breakpoint at the end of the whole prompt,
    which only ever hits on a byte-identical repeat.

    `usage_totals` accumulates token counts across calls so a caller can
    report whether the cache is actually being hit. A cache that never reads
    is pure overhead, and the only way to know is to look.

    `meta` receives the response's `stop_reason`. A caller that assembles a
    document needs it: a reply that ended because it ran out of room is a
    different thing from one the model chose to end, and trimming the ragged
    edge off the first (see _trim_to_last_sentence) makes them look
    identical on the page.
    """
    try:
        if cache_suffix and cache:
            content = [
                {"type": "text", "text": user, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": cache_suffix},
            ]
        elif cache_suffix:
            content = f"{user}\n\n{cache_suffix}"
        else:
            content = user
        request = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        if cache and not cache_suffix:
            request["cache_control"] = {"type": "ephemeral"}
        if max_tokens >= STREAMING_MAX_TOKENS_THRESHOLD:
            with client.messages.stream(**request) as stream:
                message = stream.get_final_message()
        else:
            message = client.messages.create(**request)
        if usage_totals is not None:
            for key, value in _usage_of(message).items():
                usage_totals[key] = usage_totals.get(key, 0) + value
        text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text").strip()
        if not text:
            if errors is not None:
                errors.append("the model returned an empty response")
            return None
        stop_reason = getattr(message, "stop_reason", None)
        if meta is not None:
            meta["stop_reason"] = stop_reason
            meta["truncated"] = stop_reason == "max_tokens"
        if stop_reason == "max_tokens":
            text = _trim_to_last_sentence(text)
        return text or None
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        print(f"  [llm] request failed ({reason})", file=sys.stderr)
        if errors is not None:
            errors.append(reason)
        return None
