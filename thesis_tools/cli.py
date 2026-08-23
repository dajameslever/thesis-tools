"""Command-line entry point for thesis-tools."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Optional

from . import env as _env
from . import llm
from .citations import STYLES
from .library.index_store import LibraryIndex
from .library.library_indexer import LibraryIndexerInputs, run_library_indexer
from .library.visualize import build_visualization_html
from .literature_review import LiteratureReviewInputs, run_literature_review
from .project import DEFAULT_PROJECT_PATH, ProjectState
from .sources import ALL_SOURCES
from .subquestions import generate_subquestions
from .topic_finder import TopicFinderInputs, cache_path_for, load_cache_metadata, run_topic_finder


def _prompt(question: str, default: Optional[str] = None, required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{question}{suffix}: ").strip()
        if not answer and default is not None:
            print()
            return default
        if not answer and required:
            print("  (this one's required — please enter something)")
            continue
        print()
        return answer


def _prompt_style(default: str = "apa") -> str:
    style = _prompt(f"Citation style ({'/'.join(STYLES)})", default=default)
    while style.lower() not in STYLES:
        print(f"  '{style}' isn't one of: {', '.join(STYLES)}")
        style = _prompt(f"Citation style ({'/'.join(STYLES)})", default=default)
    return style.lower()


def _split_semicolons(raw: Optional[str]) -> Optional[list]:
    if not raw:
        return None
    items = [q.strip() for q in raw.split(";") if q.strip()]
    return items or None


def _project_has_answers(project: ProjectState) -> bool:
    """Has an earlier part already answered the shared questions? If so,
    later commands reuse them silently instead of asking again."""
    return bool(project.research_question or project.sub_questions)


def _print_project_state(project: ProjectState, path: str) -> None:
    print(f"Project file: {path}")
    print(f"  Field: {project.field or '(not set)'}")
    print(f"  Working title: {project.working_title or '(not set)'}")
    print(f"  Research question: {project.research_question or '(not set)'}")
    print(f"  Sub-questions: {'; '.join(project.sub_questions) if project.sub_questions else '(not set)'}")
    print(f"  Citation style: {(project.style or 'apa').upper()}" + (" (default)" if not project.style else ""))
    print(f"  Contact email: {project.contact_email or '(not set)'}")
    print(f"  Use Claude by default: {'yes' if project.use_llm else 'no'}")
    print(f"  Claude model: {project.llm_model or '(not set — each part picks its own default)'}")
    print(f"  Last topic-finder cache: {project.last_topic_cache or '(none yet)'}")
    print(f"  Last library index: {project.last_library_index or '(none yet)'}")


def _default_use_llm(project: ProjectState) -> bool:
    """Default the 'use Claude' prompt to yes whenever it's actually usable
    (an API key is present) or a prior run already opted in — Claude
    suggesting sub-questions is the intended default experience, not an
    opt-in most people have to discover."""
    _env.load_dotenv_once()
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or project.use_llm


def _ensure_anthropic_key_interactive() -> bool:
    """If the user wants Claude's help, make sure it's actually usable right
    now — offering to collect a key if none is found — instead of silently
    degrading to heuristics for the whole run (with a confusing warning
    repeated for every paper). Returns True iff Claude ends up usable.

    The key is kept in-memory for this process; saving it to disk is a
    separate, explicit opt-in (to a local .env, which is gitignored — never
    to the shared project file, which is meant to be inspected/shared)."""
    issue = llm.availability_issue()
    if issue is None:
        return True

    if "ANTHROPIC_API_KEY" not in issue:
        # A key is already set; the package itself is the problem, and no
        # amount of prompting for a key fixes that.
        print(f"Claude isn't usable right now: {issue}. Continuing without it for this run.\n")
        return False

    print("No ANTHROPIC_API_KEY found (checked the environment and a local .env file).")
    key = getpass.getpass("Paste your Anthropic API key to use it for this run (input hidden, or press Enter to skip): ").strip()
    print()
    if not key:
        print("Skipping — continuing without Claude for this run.\n")
        return False

    os.environ["ANTHROPIC_API_KEY"] = key
    if _prompt("Save this key to a local .env file (gitignored, never sent anywhere) so you don't paste it again? (Y/n)", default="y").lower().startswith("y"):
        _env.save_to_dotenv("ANTHROPIC_API_KEY", key)
        print("Saved to .env — future runs will pick it up automatically.\n")

    issue = llm.availability_issue()
    if issue:
        print(f"Key saved, but Claude still isn't usable: {issue}. Continuing without it for this run.\n")
        return False
    return True


def _generate_and_confirm_subquestions(working_title: str, research_question: Optional[str], project: ProjectState):
    """Ask Claude for sub-questions, show them, and let the user confirm or
    replace them right here — before any search or per-paper analysis (and
    the API spend that comes with it) happens against an unconfirmed batch."""
    print("Asking Claude to suggest sub-questions...\n")
    topic_text = f"{working_title}. {research_question}" if research_question else working_title
    suggested = generate_subquestions(topic_text, model=project.llm_model or "claude-sonnet-5")

    if not suggested:
        print("Claude didn't return any sub-questions for this topic.\n")
        raw = _prompt("Type your own instead (semicolon-separated, optional — press Enter to skip)")
        return _split_semicolons(raw)

    print("Claude suggests:")
    for i, q in enumerate(suggested, start=1):
        print(f"  {i}. {q}")
    print()

    if _prompt("Use these sub-questions? (Y/n)", default="y").lower().startswith("y"):
        return suggested

    raw = _prompt("Type your own instead (semicolon-separated, optional — press Enter to proceed with none)")
    return _split_semicolons(raw)


def _interactive_topic_finder_inputs(project: ProjectState) -> TopicFinderInputs:
    print("=== Thesis Topic Finder ===")
    print("Answer a few questions and I'll scan free literature databases")
    print("(Semantic Scholar, OpenAlex, Crossref, arXiv) to check how novel")
    print("your proposed topic is, and build you a starter bibliography.\n")

    field = _prompt("What field/discipline is your thesis in? (e.g. 'clinical psychology', 'computer science', 'marketing')", default=project.field, required=True)
    working_title = _prompt("What's your working thesis title (or best guess at one)?", default=project.working_title, required=True)
    research_question = _prompt("What's the core research question, if you have one? (optional, press Enter to skip)", default=project.research_question)
    extra_keywords = _prompt("Any extra keywords to include in the search? (comma-separated, optional)")
    style = _prompt_style(default=project.style or "apa")

    default_use_llm = _default_use_llm(project)
    use_llm = _prompt(
        "Use Claude to write nicer paper summaries and suggest sub-questions? Requires ANTHROPIC_API_KEY. "
        + ("(Y/n)" if default_use_llm else "(y/N)"),
        default="y" if default_use_llm else "n",
    ).lower().startswith("y")
    if use_llm:
        use_llm = _ensure_anthropic_key_interactive()

    sub_questions = None
    if project.sub_questions:
        print("Sub-questions saved from a previous run:")
        for i, q in enumerate(project.sub_questions, start=1):
            print(f"  {i}. {q}")
        print()
        if use_llm:
            # Don't bury "get fresh Claude recommendations" behind declining
            # a keep/reuse default — someone who just opted into Claude
            # expects that choice to be on offer here, not implied by "no".
            choice = _prompt(
                "Keep these, or have Claude suggest fresh ones for this run? (keep/suggest)",
                default="keep",
            ).strip().lower()
            if choice.startswith("s"):
                sub_questions = _generate_and_confirm_subquestions(working_title, research_question, project)
            else:
                sub_questions = list(project.sub_questions)
        elif _prompt("Keep these sub-questions? (Y/n)", default="y").lower().startswith("y"):
            sub_questions = list(project.sub_questions)

    if not sub_questions:
        sub_questions_raw = _prompt(
            "Break this into 3-4 sub-questions yourself? (semicolon-separated, optional — "
            + ("press Enter to have Claude suggest some" if use_llm else "press Enter to skip, since Claude access is off")
        )
        sub_questions = _split_semicolons(sub_questions_raw)
        if not sub_questions and use_llm:
            sub_questions = _generate_and_confirm_subquestions(working_title, research_question, project)

    # Blank is a real, deliberate choice too — don't let it happen by
    # default just because every prompt above was skipped past. Confirm it
    # explicitly, and give one more chance to enter some, before proceeding
    # with a report that has no per-sub-question stance analysis at all.
    if not sub_questions:
        print("No sub-questions set — the report won't include stance/compare-and-contrast analysis.\n")
        if not _prompt("Continue without sub-questions? (y/N)", default="n").lower().startswith("y"):
            raw = _prompt("Sub-questions (semicolon-separated, 3-4 recommended)")
            sub_questions = _split_semicolons(raw)

    download_papers = _prompt(
        "Also download each shortlisted paper's open-access PDF (where one exists) and extract its "
        "text into a 'processed' folder? Skips papers with no open-access copy. (y/N)",
        default="n",
    ).lower().startswith("y")

    return TopicFinderInputs(
        field=field,
        working_title=working_title,
        research_question=research_question or None,
        extra_keywords=extra_keywords or None,
        style=style,
        use_llm_summaries=use_llm,
        sub_questions=sub_questions,
        # Already resolved (confirmed/edited/declined) above — don't let the
        # pipeline silently generate a fresh, unconfirmed batch later.
        auto_subquestions=False,
        contact_email=project.contact_email,
        download_papers=download_papers,
    )


def _interactive_library_indexer_inputs(project: ProjectState) -> LibraryIndexerInputs:
    print("=== Library Indexer ===")
    print("I'll scan a folder for downloaded papers (PDF/docx/txt/HTML), pull out")
    print("title/author/year/DOI where I can, verify it against Crossref/Semantic")
    print("Scholar, and build you a searchable index + bibliography.\n")

    folder = _prompt("Folder to scan (e.g. ~/Downloads)", required=True)
    recursive = _prompt("Scan subfolders too? (Y/n)", default="y").lower().startswith("y")

    if _project_has_answers(project):
        print("\nReusing the research question/sub-questions/style/Claude settings already set up")
        print("in Part 1 (pass --question/--sub-questions/--style/--llm-summaries to override):")
        print(f"  Research question: {project.research_question or '(none)'}")
        print(f"  Sub-questions: {'; '.join(project.sub_questions) if project.sub_questions else '(none)'}")
        print(f"  Style: {project.style or 'apa'}")
        print(f"  Claude assistance: {'on' if project.use_llm else 'off'}\n")
        research_question = project.research_question
        sub_questions = list(project.sub_questions) or None
        style = project.style or "apa"
        use_llm = project.use_llm
        if use_llm:
            use_llm = _ensure_anthropic_key_interactive()
    else:
        style = _prompt_style()
        research_question = _prompt(
            "Got a research question/topic? I'll score each paper's relevance to it and summarize "
            "it in that context. (optional, press Enter to skip)"
        ) or None
        default_use_llm = _default_use_llm(project)
        use_llm = _prompt(
            "Use Claude for nicer summaries and stance analysis? Requires ANTHROPIC_API_KEY. "
            + ("(Y/n)" if default_use_llm else "(y/N)"),
            default="y" if default_use_llm else "n",
        ).lower().startswith("y")
        if use_llm:
            use_llm = _ensure_anthropic_key_interactive()
        sub_questions_raw = _prompt("Sub-questions to check papers against? (semicolon-separated, optional, 3-4 recommended)")
        sub_questions = _split_semicolons(sub_questions_raw)

    organize = _prompt(
        "Also copy matched files into a clean Author_Year_Title folder? "
        "Originals are never touched or moved. (y/N)",
        default="n",
    ).lower().startswith("y")
    organize_to = "library/organized"
    if organize:
        organize_to = _prompt("Destination folder for the organized copies", default=organize_to)

    fetch_references = _prompt(
        "Also fetch each paper's own references, to see what's cited but missing from your library? "
        "Slower, more API calls. (y/N)",
        default="n",
    ).lower().startswith("y")

    return LibraryIndexerInputs(
        folder=folder,
        recursive=recursive,
        style=style,
        organize=organize,
        organize_to=organize_to,
        research_question=research_question,
        sub_questions=sub_questions,
        use_llm=use_llm,
        llm_model=project.llm_model or "claude-sonnet-5",
        fetch_references=fetch_references,
        contact_email=project.contact_email,
    )


def _interactive_literature_review_inputs(project: ProjectState) -> LiteratureReviewInputs:
    print("=== Literature Review Drafter ===")
    print("I'll draft a literature review structured around your sub-questions, using")
    print("whatever papers Part 1/Part 2 have already found — no new searching happens.\n")

    field = project.field or _prompt("What field/discipline is your thesis in?", required=True)
    working_title = project.working_title or _prompt("What's your working thesis title?", required=True)
    research_question = project.research_question or (_prompt("Research question? (optional)") or None)

    sub_questions = list(project.sub_questions)
    if not sub_questions:
        raw = _prompt("Sub-questions to structure the review around? (semicolon-separated, 3-4 recommended)")
        sub_questions = _split_semicolons(raw) or []

    style = project.style or _prompt_style()

    sources = []
    if project.last_topic_cache and Path(project.last_topic_cache).is_file():
        sources.append(project.last_topic_cache)
    if project.last_library_index and Path(project.last_library_index).is_file():
        sources.append(project.last_library_index)
    if not sources:
        raw = _prompt(
            "Path(s) to a Part 1 <report>.papers.json and/or Part 2 library/index.json (comma-separated)",
            required=True,
        )
        sources = [s.strip() for s in raw.split(",") if s.strip()]

    return LiteratureReviewInputs(
        field=field,
        working_title=working_title,
        research_question=research_question,
        sub_questions=sub_questions,
        paper_sources=sources,
        style=style,
        llm_model=project.llm_model or "claude-opus-5",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thesis-tools", description="A local toolkit for working through a thesis.")
    subparsers = parser.add_subparsers(dest="command")

    tf = subparsers.add_parser("topic-finder", help="Part 1: find/validate a thesis title and check it against existing literature")
    tf.add_argument("--field", help="Your field/discipline")
    tf.add_argument("--title", dest="working_title", help="Proposed working thesis title")
    tf.add_argument("--question", dest="research_question", help="Core research question (optional)")
    tf.add_argument("--keywords", dest="extra_keywords", help="Extra comma-separated keywords")
    tf.add_argument("--style", choices=STYLES, default=None, help="Citation style for the bibliography (default: apa, or your saved project style)")
    tf.add_argument(
        "--sources",
        help=f"Comma-separated sources to search (default: all). Available: {', '.join(ALL_SOURCES)}",
    )
    tf.add_argument("--limit", type=int, default=15, help="Max results to request per source (default: 15)")
    tf.add_argument("--top", type=int, default=20, help="Max papers to include in the final report (default: 20)")
    tf.add_argument("--min-relevance", type=float, default=0.12, help="Drop papers scoring below this relevance (0-1, default: 0.12)")
    tf.add_argument("--llm-summaries", action="store_true", help="Use Claude for paper summaries, sub-question generation, and stance analysis (needs ANTHROPIC_API_KEY)")
    tf.add_argument("--llm-model", default=None, help="Model to use for --llm-summaries (default: claude-sonnet-5, or your saved project model)")
    tf.add_argument(
        "--sub-questions",
        help="Semicolon-separated sub-questions to check found papers against (3-4 recommended). "
        "If omitted and --llm-summaries is on, Claude suggests some automatically.",
    )
    tf.add_argument("--no-auto-subquestions", dest="auto_subquestions", action="store_false", help="Don't auto-generate sub-questions via Claude when none are given")
    tf.set_defaults(auto_subquestions=True)
    tf.add_argument(
        "--download-papers",
        action="store_true",
        help="Download each shortlisted paper's open-access PDF (where one exists) and extract its text "
        "into --download-dir. Never follows a paywalled link — only what a source API reports as open access.",
    )
    tf.add_argument("--download-dir", default="processed", help="Where to save downloaded PDFs + extracted text (default: processed)")
    tf.add_argument("--contact-email", help="Optional email sent to OpenAlex/Crossref's 'polite pool' for faster, more reliable responses")
    tf.add_argument("-o", "--output", dest="output_path", help="Where to write the Markdown report (default: output/<slug>-<timestamp>.md)")
    tf.add_argument(
        "--reanalyze",
        dest="reanalyze_from",
        help="Path to a previous run's <report>.papers.json — skip searching and re-score/re-analyze "
        "those same papers against new --sub-questions/--style/etc.",
    )
    tf.add_argument("--project-file", default=DEFAULT_PROJECT_PATH, help=f"Where shared project state (field, questions, style, ...) lives (default: {DEFAULT_PROJECT_PATH})")
    tf.add_argument("--non-interactive", action="store_true", help="Don't prompt for missing values; fail instead if --field/--title are missing")

    il = subparsers.add_parser("index-library", help="Part 2: scan a local folder of downloaded papers and build a searchable, cited index")
    il.add_argument("--folder", help="Folder to scan (e.g. ~/Downloads)")
    il.add_argument("--no-recursive", dest="recursive", action="store_false", help="Only scan the top level of the folder (default: scan subfolders too)")
    il.set_defaults(recursive=True)
    il.add_argument("--extensions", help="Comma-separated file extensions to index (default: pdf,docx,txt,html,htm)")
    il.add_argument("--index-path", default="library/index.json", help="Where to store the JSON index (default: library/index.json)")
    il.add_argument("--style", choices=STYLES, default=None, help="Citation style for the bibliography (default: apa, or whatever Part 1 already used)")
    il.add_argument("-o", "--report", dest="report_path", help="Where to write the Markdown library report (default: alongside the index, as library.md)")
    il.add_argument("--rescan", action="store_true", help="Re-extract metadata even for files already in the index")
    il.add_argument("--prune", action="store_true", help="Remove index entries whose source file no longer exists")
    il.add_argument("--organize", action="store_true", help="Also copy (never move) indexed files into a clean Author_Year_Title structure")
    il.add_argument("--organize-to", default="library/organized", help="Destination folder for --organize (default: library/organized)")
    il.add_argument("--fetch-references", action="store_true", help="Also fetch each paper's own reference list from Semantic Scholar, to build the citation-coverage view (slower, more API calls)")
    il.add_argument("--question", dest="research_question", default=None, help="Your research question/topic (default: whatever Part 1 already used) — scores each indexed paper's relevance and summarizes it in that context")
    il.add_argument(
        "--sub-questions",
        default=None,
        help="Semicolon-separated sub-questions to check indexed papers against (default: whatever Part 1 already used). "
        "Re-running with different sub-questions updates relevance/stances without re-scanning files.",
    )
    il.add_argument("--llm-summaries", action="store_true", help="Use Claude for paper summaries and stance analysis (needs ANTHROPIC_API_KEY)")
    il.add_argument("--llm-model", default=None, help="Model to use for --llm-summaries")
    il.add_argument("--contact-email", help="Optional email sent to Crossref's 'polite pool' for faster, more reliable responses")
    il.add_argument("--project-file", default=DEFAULT_PROJECT_PATH, help=f"Where shared project state lives (default: {DEFAULT_PROJECT_PATH}) — read to reuse Part 1's question/sub-questions/style automatically")
    il.add_argument("--non-interactive", action="store_true", help="Don't prompt for missing values; fail instead if --folder is missing")

    vl = subparsers.add_parser(
        "visualize-library",
        help="Part 2 add-on: render an HTML visualization of what's indexed — sources, verification confidence, citation coverage, and weaknesses",
    )
    vl.add_argument("--index-path", default="library/index.json", help="Path to the index built by index-library (default: library/index.json)")
    vl.add_argument("-o", "--output", dest="output_path", default="library/visualization.html", help="Where to write the HTML page (default: library/visualization.html)")
    vl.add_argument(
        "--sub-questions",
        default=None,
        help="Semicolon-separated sub-questions to anchor the visualization around (default: whatever Part 1 already used). "
        "Each indexed paper is classified as supporting/challenging/mixed/unrelated to each one.",
    )
    vl.add_argument("--llm-summaries", action="store_true", help="Use Claude for stance classification against the sub-questions (needs ANTHROPIC_API_KEY; default: heuristic)")
    vl.add_argument("--llm-model", default=None, help="Model to use for --llm-summaries")
    vl.add_argument("--project-file", default=DEFAULT_PROJECT_PATH, help=f"Where shared project state lives (default: {DEFAULT_PROJECT_PATH}) — read to reuse Part 1's sub-questions/Claude settings automatically")

    lr = subparsers.add_parser("literature-review", help="Part 3: draft a literature review structured around your sub-questions, from what Part 1/2 already found")
    lr.add_argument("--field", help="Your field/discipline (default: whatever Part 1 already used)")
    lr.add_argument("--title", dest="working_title", help="Working thesis title (default: whatever Part 1 already used)")
    lr.add_argument("--question", dest="research_question", help="Research question (default: whatever Part 1 already used)")
    lr.add_argument("--sub-questions", help="Semicolon-separated sub-questions to structure the review around (default: whatever Part 1 already used)")
    lr.add_argument("--topic-cache", help="Path to a Part 1 <report>.papers.json (default: the most recent one, if any)")
    lr.add_argument("--library-index", help="Path to a Part 2 library/index.json (default: the most recent one, if any)")
    lr.add_argument("--style", choices=STYLES, default=None, help="Citation style for the reference list (default: apa, or whatever Part 1 already used)")
    lr.add_argument("--no-llm", action="store_true", help="Skip Claude entirely and produce a heuristic structured outline instead of drafted prose")
    lr.add_argument("--llm-model", default=None, help="Model to use for drafting")
    lr.add_argument("--min-relevance", type=float, default=0.1, help="Drop papers scoring below this relevance to the research question (0-1, default: 0.1)")
    lr.add_argument("-o", "--output", dest="output_path", help="Where to write the Markdown draft (default: output/literature-review-<timestamp>.md)")
    lr.add_argument("--project-file", default=DEFAULT_PROJECT_PATH, help=f"Where shared project state lives (default: {DEFAULT_PROJECT_PATH})")
    lr.add_argument("--non-interactive", action="store_true", help="Don't prompt for missing values; fail instead if --field/--title (and sub-questions) can't be resolved")

    cfg = subparsers.add_parser(
        "configure",
        help="Set (and remember) your field, title, research question, sub-questions, and citation style once — before running anything else",
    )
    cfg.add_argument("--field", help="Your field/discipline")
    cfg.add_argument("--title", dest="working_title", help="Working thesis title")
    cfg.add_argument("--question", dest="research_question", help="Core research question")
    cfg.add_argument("--sub-questions", help="Semicolon-separated sub-questions")
    cfg.add_argument("--style", choices=STYLES, help="Citation style — set this once here and every part reuses it")
    cfg.add_argument("--contact-email", help="Optional email sent to OpenAlex/Crossref's 'polite pool'")
    cfg.add_argument("--llm-model", help="Claude model to use where a part doesn't have its own better default")
    llm_toggle = cfg.add_mutually_exclusive_group()
    llm_toggle.add_argument("--llm-summaries", dest="llm_summaries", action="store_true", help="Use Claude by default across all parts")
    llm_toggle.add_argument("--no-llm-summaries", dest="no_llm_summaries", action="store_true", help="Don't use Claude by default across all parts")
    cfg.add_argument("--show", action="store_true", help="Print the current saved settings and exit, without changing anything")
    cfg.add_argument("--project-file", default=DEFAULT_PROJECT_PATH, help=f"Where shared project state lives (default: {DEFAULT_PROJECT_PATH})")
    cfg.add_argument("--non-interactive", action="store_true", help="Only apply the flags given; don't prompt for the rest")

    return parser


def _run_topic_finder_command(args: argparse.Namespace) -> int:
    project = ProjectState.load(args.project_file)
    # Explicit flag > a model the user has explicitly chosen before > this
    # part's own sensible default. Deliberately NOT persisted unless the user
    # actually passes --llm-model — see the project.updated() call below.
    llm_model = args.llm_model or project.llm_model or "claude-sonnet-5"

    # Only skip the interactive walkthrough when THIS invocation gives enough
    # to proceed without it: --field/--title passed directly (a scripting
    # shortcut), or --non-interactive explicitly opting out of prompts (in
    # which case falling back to saved project values is fine — the user
    # asked not to be asked). A bare `topic-finder` with no flags always goes
    # interactive, even once a project file exists from a previous run/
    # `configure` — otherwise things like sub-question confirmation would
    # only ever happen the first time, never again.
    if args.non_interactive:
        field = args.field or project.field
        working_title = args.working_title or project.working_title
        if not (field and working_title):
            print(
                "error: --non-interactive requires --field and --title (or run `thesis-tools configure` "
                "first to save them)",
                file=sys.stderr,
            )
            return 2
        skip_interactive = True
    elif args.field and args.working_title:
        field = args.field
        working_title = args.working_title
        skip_interactive = True
    else:
        skip_interactive = False

    if skip_interactive:
        inputs = TopicFinderInputs(
            field=field,
            working_title=working_title,
            research_question=args.research_question or project.research_question,
            extra_keywords=args.extra_keywords,
            style=args.style or project.style or "apa",
            sources=args.sources.split(",") if args.sources else None,
            limit_per_source=args.limit,
            top_n=args.top,
            min_relevance=args.min_relevance,
            use_llm_summaries=args.llm_summaries or project.use_llm,
            llm_model=llm_model,
            contact_email=args.contact_email or project.contact_email,
            output_path=args.output_path,
            sub_questions=_split_semicolons(args.sub_questions) or (project.sub_questions or None),
            auto_subquestions=args.auto_subquestions,
            reanalyze_from=args.reanalyze_from,
            download_papers=args.download_papers,
            download_dir=args.download_dir,
        )
    else:
        inputs = _interactive_topic_finder_inputs(project)
        # CLI flags still override/augment interactive answers where given.
        if args.sources:
            inputs.sources = args.sources.split(",")
        if args.sub_questions:
            inputs.sub_questions = _split_semicolons(args.sub_questions)
        inputs.limit_per_source = args.limit
        inputs.top_n = args.top
        inputs.min_relevance = args.min_relevance
        inputs.llm_model = llm_model
        inputs.contact_email = args.contact_email or inputs.contact_email
        inputs.output_path = args.output_path
        # The interactive flow above already resolved sub-questions (asked,
        # generated-and-confirmed, or deliberately left empty) — don't let
        # the flag's True default re-enable auto-generation over that;
        # an explicit --no-auto-subquestions still applies.
        inputs.auto_subquestions = inputs.auto_subquestions and args.auto_subquestions
        inputs.use_llm_summaries = inputs.use_llm_summaries or args.llm_summaries
        inputs.reanalyze_from = args.reanalyze_from
        inputs.download_papers = inputs.download_papers or args.download_papers
        inputs.download_dir = args.download_dir

    try:
        report_path = run_topic_finder(inputs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Read back the sub-questions actually used (they may have just been
    # auto-generated by Claude) so the shared project file stays accurate.
    metadata = load_cache_metadata(cache_path_for(Path(report_path)))
    resolved_sub_questions = metadata.get("sub_questions", inputs.sub_questions or [])

    project = project.updated(
        field=inputs.field,
        working_title=inputs.working_title,
        research_question=inputs.research_question,
        sub_questions=resolved_sub_questions,
        style=inputs.style,
        contact_email=inputs.contact_email,
        use_llm=inputs.use_llm_summaries,
        llm_model=args.llm_model,  # only an explicit --llm-model sticks; a part's own default never does
        last_topic_cache=str(cache_path_for(Path(report_path))),
    )
    project.save(args.project_file)

    print(f"\nReport written to {report_path}")
    return 0


def _run_index_library_command(args: argparse.Namespace) -> int:
    project = ProjectState.load(args.project_file)
    sub_questions = _split_semicolons(args.sub_questions)
    llm_model = args.llm_model or project.llm_model or "claude-sonnet-5"

    if args.folder:
        inputs = LibraryIndexerInputs(
            folder=args.folder,
            recursive=args.recursive,
            extensions=args.extensions.split(",") if args.extensions else None,
            index_path=args.index_path,
            style=args.style or project.style or "apa",
            report_path=args.report_path,
            rescan=args.rescan,
            prune=args.prune,
            organize=args.organize,
            organize_to=args.organize_to,
            contact_email=args.contact_email or project.contact_email,
            fetch_references=args.fetch_references,
            research_question=args.research_question or project.research_question,
            sub_questions=sub_questions or (project.sub_questions or None),
            use_llm=args.llm_summaries or project.use_llm,
            llm_model=llm_model,
        )
    elif args.non_interactive:
        print("error: --non-interactive requires --folder", file=sys.stderr)
        return 2
    else:
        inputs = _interactive_library_indexer_inputs(project)
        if args.extensions:
            inputs.extensions = args.extensions.split(",")
        inputs.index_path = args.index_path
        inputs.report_path = args.report_path
        inputs.rescan = args.rescan
        inputs.prune = args.prune
        inputs.organize = inputs.organize or args.organize
        if args.organize_to != "library/organized":
            inputs.organize_to = args.organize_to
        inputs.contact_email = args.contact_email or inputs.contact_email
        inputs.fetch_references = inputs.fetch_references or args.fetch_references
        inputs.research_question = args.research_question or inputs.research_question
        inputs.sub_questions = sub_questions or inputs.sub_questions
        inputs.llm_model = llm_model
        inputs.use_llm = inputs.use_llm or args.llm_summaries

    try:
        stats = run_library_indexer(inputs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    project = project.updated(
        research_question=inputs.research_question,
        sub_questions=inputs.sub_questions,
        style=inputs.style,
        contact_email=inputs.contact_email,
        use_llm=inputs.use_llm,
        llm_model=args.llm_model,  # only an explicit --llm-model sticks
        last_library_index=stats["index_path"],
    )
    project.save(args.project_file)

    print(f"\nIndexed {stats['new']} new file(s), skipped {stats['skipped']} unchanged, {stats['failed']} failed.")
    if stats["pruned"]:
        print(f"Pruned {stats['pruned']} missing file(s) from the index.")
    if stats["organized"]:
        print(f"Copied {stats['organized']} file(s) into {inputs.organize_to}")
    print(f"Index ({stats['total']} total entries): {stats['index_path']}")
    print(f"Report: {stats['report_path']}")
    return 0


def _run_visualize_library_command(args: argparse.Namespace) -> int:
    index_path = Path(args.index_path)
    if not index_path.is_file():
        print(f"error: no index found at {index_path} — run `index-library` first", file=sys.stderr)
        return 2

    project = ProjectState.load(args.project_file)
    sub_questions = _split_semicolons(args.sub_questions) or list(project.sub_questions)
    use_llm = args.llm_summaries or project.use_llm
    llm_model = args.llm_model or project.llm_model or "claude-sonnet-5"
    if use_llm:
        issue = llm.availability_issue()
        if issue:
            print(f"Claude requested but unavailable ({issue}) — using heuristic stance classification for this run.", file=sys.stderr)

    index = LibraryIndex.load(index_path)
    html = build_visualization_html(index, sub_questions=sub_questions, use_llm=use_llm, llm_model=llm_model)

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    print(f"Visualization ({len(index.entries)} file(s)) written to {output_path}")
    return 0


def _run_literature_review_command(args: argparse.Namespace) -> int:
    project = ProjectState.load(args.project_file)

    field = args.field or project.field
    working_title = args.working_title or project.working_title

    if field and working_title:
        research_question = args.research_question or project.research_question
        sub_questions = _split_semicolons(args.sub_questions) or list(project.sub_questions)
        style = args.style or project.style or "apa"
        llm_model = args.llm_model or project.llm_model or "claude-opus-5"
        use_llm = not args.no_llm

        sources = []
        if args.topic_cache or project.last_topic_cache:
            sources.append(args.topic_cache or project.last_topic_cache)
        if args.library_index or project.last_library_index:
            sources.append(args.library_index or project.last_library_index)

        if not sub_questions and use_llm:
            print("No sub-questions found — asking Claude to suggest some...", file=sys.stderr)
            sub_questions = generate_subquestions(research_question or working_title, model=llm_model)

        if not sub_questions:
            print("error: no sub-questions to draft around — run topic-finder first, or pass --sub-questions", file=sys.stderr)
            return 2

        inputs = LiteratureReviewInputs(
            field=field,
            working_title=working_title,
            research_question=research_question,
            sub_questions=sub_questions,
            paper_sources=sources,
            style=style,
            use_llm=use_llm,
            llm_model=llm_model,
            min_relevance=args.min_relevance,
            output_path=args.output_path,
        )
    elif args.non_interactive:
        print("error: --non-interactive requires --field and --title (or run topic-finder first to populate the project file)", file=sys.stderr)
        return 2
    else:
        inputs = _interactive_literature_review_inputs(project)
        if args.output_path:
            inputs.output_path = args.output_path
        inputs.min_relevance = args.min_relevance
        if args.no_llm:
            inputs.use_llm = False
        if args.llm_model:
            inputs.llm_model = args.llm_model

    if not inputs.paper_sources:
        print(
            "error: no paper sources to draw from — run topic-finder and/or index-library first, "
            "or pass --topic-cache/--library-index explicitly",
            file=sys.stderr,
        )
        return 2

    try:
        report_path = run_literature_review(inputs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    project = project.updated(
        field=inputs.field,
        working_title=inputs.working_title,
        research_question=inputs.research_question,
        sub_questions=inputs.sub_questions,
        style=inputs.style,
        llm_model=args.llm_model,  # only an explicit --llm-model sticks — Part 3's own default never does
    )
    project.save(args.project_file)

    print(f"\nDraft written to {report_path}")
    return 0


def _run_configure_command(args: argparse.Namespace) -> int:
    project = ProjectState.load(args.project_file)

    if args.show:
        _print_project_state(project, args.project_file)
        return 0

    # Tri-state: True/False if the user explicitly chose one, None (don't
    # touch the saved value) if neither flag was given.
    use_llm_choice = True if args.llm_summaries else (False if args.no_llm_summaries else None)

    if args.non_interactive:
        project = project.updated(
            field=args.field,
            working_title=args.working_title,
            research_question=args.research_question,
            sub_questions=_split_semicolons(args.sub_questions),
            style=args.style,
            contact_email=args.contact_email,
            llm_model=args.llm_model,
            use_llm=use_llm_choice,
        )
    else:
        print("=== Configure your thesis-tools project ===")
        print("Set these once — topic-finder, index-library, and literature-review will all")
        print("reuse them automatically from here on. Press Enter to keep the current value.\n")

        field = _prompt("Field/discipline", default=args.field or project.field or "")
        working_title = _prompt("Working thesis title", default=args.working_title or project.working_title or "")
        research_question = _prompt("Research question (optional)", default=args.research_question or project.research_question or "")
        sub_questions_default = args.sub_questions or ("; ".join(project.sub_questions) if project.sub_questions else "")
        sub_questions_raw = _prompt("Sub-questions, semicolon-separated (optional)", default=sub_questions_default)
        style = _prompt_style(default=args.style or project.style or "apa")
        contact_email = _prompt(
            "Contact email for OpenAlex/Crossref's 'polite pool' (optional)",
            default=args.contact_email or project.contact_email or "",
        )
        if use_llm_choice is None:
            default_use_llm = _default_use_llm(project)
            use_llm_choice = _prompt(
                "Use Claude by default for summaries/sub-questions/stance analysis? "
                + ("(Y/n)" if default_use_llm else "(y/N)"),
                default="y" if default_use_llm else "n",
            ).lower().startswith("y")
            if use_llm_choice:
                use_llm_choice = _ensure_anthropic_key_interactive()

        project = project.updated(
            field=field or None,
            working_title=working_title or None,
            research_question=research_question or None,
            sub_questions=_split_semicolons(sub_questions_raw),
            style=style,
            contact_email=contact_email or None,
            use_llm=use_llm_choice,
            llm_model=args.llm_model or project.llm_model,
        )

    project.save(args.project_file)
    print("\nSaved. Current settings:\n")
    _print_project_state(project, args.project_file)
    return 0


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "topic-finder":
        return _run_topic_finder_command(args)
    if args.command == "index-library":
        return _run_index_library_command(args)
    if args.command == "visualize-library":
        return _run_visualize_library_command(args)
    if args.command == "literature-review":
        return _run_literature_review_command(args)
    if args.command == "configure":
        return _run_configure_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
