"""Command-line entry point for thesis-tools."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from .citations import STYLES
from .library.library_indexer import LibraryIndexerInputs, run_library_indexer
from .sources import ALL_SOURCES
from .topic_finder import TopicFinderInputs, run_topic_finder


def _prompt(question: str, default: Optional[str] = None, required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{question}{suffix}: ").strip()
        if not answer and default is not None:
            return default
        if not answer and required:
            print("  (this one's required — please enter something)")
            continue
        return answer


def _prompt_style(default: str = "apa") -> str:
    style = _prompt(f"Citation style ({'/'.join(STYLES)})", default=default)
    while style.lower() not in STYLES:
        print(f"  '{style}' isn't one of: {', '.join(STYLES)}")
        style = _prompt(f"Citation style ({'/'.join(STYLES)})", default=default)
    return style.lower()


def _interactive_topic_finder_inputs() -> TopicFinderInputs:
    print("=== Thesis Topic Finder ===")
    print("Answer a few questions and I'll scan free literature databases")
    print("(Semantic Scholar, OpenAlex, Crossref, arXiv) to check how novel")
    print("your proposed topic is, and build you a starter bibliography.\n")

    field = _prompt("What field/discipline is your thesis in? (e.g. 'clinical psychology', 'computer science', 'marketing')", required=True)
    working_title = _prompt("What's your working thesis title (or best guess at one)?", required=True)
    research_question = _prompt("What's the core research question, if you have one? (optional, press Enter to skip)")
    extra_keywords = _prompt("Any extra keywords to include in the search? (comma-separated, optional)")
    style = _prompt_style()

    use_llm = _prompt("Use Claude to write nicer paper summaries? Requires ANTHROPIC_API_KEY. (y/N)", default="n").lower().startswith("y")

    sub_questions_raw = _prompt(
        "Break this into 3-4 sub-questions yourself? (semicolon-separated, optional — "
        + ("press Enter to have Claude suggest some" if use_llm else "press Enter to skip, since Claude access is off")
    )
    sub_questions = [q.strip() for q in sub_questions_raw.split(";") if q.strip()] or None

    return TopicFinderInputs(
        field=field,
        working_title=working_title,
        research_question=research_question or None,
        extra_keywords=extra_keywords or None,
        style=style,
        use_llm_summaries=use_llm,
        sub_questions=sub_questions,
    )


def _interactive_library_indexer_inputs() -> LibraryIndexerInputs:
    print("=== Library Indexer ===")
    print("I'll scan a folder for downloaded papers (PDF/docx/txt/HTML), pull out")
    print("title/author/year/DOI where I can, verify it against Crossref/Semantic")
    print("Scholar, and build you a searchable index + bibliography.\n")

    folder = _prompt("Folder to scan (e.g. ~/Downloads)", required=True)
    recursive = _prompt("Scan subfolders too? (Y/n)", default="y").lower().startswith("y")
    style = _prompt_style()
    organize = _prompt(
        "Also copy matched files into a clean Author_Year_Title folder? "
        "Originals are never touched or moved. (y/N)",
        default="n",
    ).lower().startswith("y")
    organize_to = "library/organized"
    if organize:
        organize_to = _prompt("Destination folder for the organized copies", default=organize_to)

    research_question = _prompt(
        "Got a research question/topic? I'll score each paper's relevance to it and summarize "
        "it in that context. (optional, press Enter to skip)"
    )
    use_llm = _prompt("Use Claude for nicer summaries and stance analysis? Requires ANTHROPIC_API_KEY. (y/N)", default="n").lower().startswith("y")
    sub_questions_raw = _prompt(
        "Sub-questions to check papers against? (semicolon-separated, optional, 3-4 recommended)"
    )
    sub_questions = [q.strip() for q in sub_questions_raw.split(";") if q.strip()] or None
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
        research_question=research_question or None,
        sub_questions=sub_questions,
        use_llm=use_llm,
        fetch_references=fetch_references,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thesis-tools", description="A local toolkit for working through a thesis.")
    subparsers = parser.add_subparsers(dest="command")

    tf = subparsers.add_parser("topic-finder", help="Part 1: find/validate a thesis title and check it against existing literature")
    tf.add_argument("--field", help="Your field/discipline")
    tf.add_argument("--title", dest="working_title", help="Proposed working thesis title")
    tf.add_argument("--question", dest="research_question", help="Core research question (optional)")
    tf.add_argument("--keywords", dest="extra_keywords", help="Extra comma-separated keywords")
    tf.add_argument("--style", choices=STYLES, default="apa", help="Citation style for the bibliography (default: apa)")
    tf.add_argument(
        "--sources",
        help=f"Comma-separated sources to search (default: all). Available: {', '.join(ALL_SOURCES)}",
    )
    tf.add_argument("--limit", type=int, default=15, help="Max results to request per source (default: 15)")
    tf.add_argument("--top", type=int, default=20, help="Max papers to include in the final report (default: 20)")
    tf.add_argument("--min-relevance", type=float, default=0.12, help="Drop papers scoring below this relevance (0-1, default: 0.12)")
    tf.add_argument("--llm-summaries", action="store_true", help="Use Claude for paper summaries, sub-question generation, and stance analysis (needs ANTHROPIC_API_KEY + `pip install anthropic`)")
    tf.add_argument("--llm-model", default="claude-sonnet-5", help="Model to use for --llm-summaries")
    tf.add_argument(
        "--sub-questions",
        help="Semicolon-separated sub-questions to check found papers against (3-4 recommended). "
        "If omitted and --llm-summaries is on, Claude suggests some automatically.",
    )
    tf.add_argument("--no-auto-subquestions", dest="auto_subquestions", action="store_false", help="Don't auto-generate sub-questions via Claude when none are given")
    tf.set_defaults(auto_subquestions=True)
    tf.add_argument("--contact-email", help="Optional email sent to OpenAlex/Crossref's 'polite pool' for faster, more reliable responses")
    tf.add_argument("-o", "--output", dest="output_path", help="Where to write the Markdown report (default: output/<slug>-<timestamp>.md)")
    tf.add_argument(
        "--reanalyze",
        dest="reanalyze_from",
        help="Path to a previous run's <report>.papers.json — skip searching and re-score/re-analyze "
        "those same papers against new --sub-questions/--style/etc.",
    )
    tf.add_argument("--non-interactive", action="store_true", help="Don't prompt for missing values; fail instead if --field/--title are missing")

    il = subparsers.add_parser("index-library", help="Part 2: scan a local folder of downloaded papers and build a searchable, cited index")
    il.add_argument("--folder", help="Folder to scan (e.g. ~/Downloads)")
    il.add_argument("--no-recursive", dest="recursive", action="store_false", help="Only scan the top level of the folder (default: scan subfolders too)")
    il.set_defaults(recursive=True)
    il.add_argument("--extensions", help="Comma-separated file extensions to index (default: pdf,docx,txt,html,htm)")
    il.add_argument("--index-path", default="library/index.json", help="Where to store the JSON index (default: library/index.json)")
    il.add_argument("--style", choices=STYLES, default="apa", help="Citation style for the bibliography (default: apa)")
    il.add_argument("-o", "--report", dest="report_path", help="Where to write the Markdown library report (default: alongside the index, as library.md)")
    il.add_argument("--rescan", action="store_true", help="Re-extract metadata even for files already in the index")
    il.add_argument("--prune", action="store_true", help="Remove index entries whose source file no longer exists")
    il.add_argument("--organize", action="store_true", help="Also copy (never move) indexed files into a clean Author_Year_Title structure")
    il.add_argument("--organize-to", default="library/organized", help="Destination folder for --organize (default: library/organized)")
    il.add_argument("--fetch-references", action="store_true", help="Also fetch each paper's own reference list from Semantic Scholar, to build the citation-coverage view (slower, more API calls)")
    il.add_argument("--question", dest="research_question", help="Your research question/topic — scores each indexed paper's relevance to it and summarizes it in that context")
    il.add_argument(
        "--sub-questions",
        help="Semicolon-separated sub-questions to check indexed papers against (3-4 recommended). "
        "Re-running with different sub-questions updates relevance/stances without re-scanning files.",
    )
    il.add_argument("--llm-summaries", action="store_true", help="Use Claude for paper summaries and stance analysis (needs ANTHROPIC_API_KEY + `pip install anthropic`)")
    il.add_argument("--llm-model", default="claude-sonnet-5", help="Model to use for --llm-summaries")
    il.add_argument("--contact-email", help="Optional email sent to Crossref's 'polite pool' for faster, more reliable responses")
    il.add_argument("--non-interactive", action="store_true", help="Don't prompt for missing values; fail instead if --folder is missing")

    return parser


def _run_topic_finder_command(args: argparse.Namespace) -> int:
    if args.field and args.working_title:
        inputs = TopicFinderInputs(
            field=args.field,
            working_title=args.working_title,
            research_question=args.research_question,
            extra_keywords=args.extra_keywords,
            style=args.style,
            sources=args.sources.split(",") if args.sources else None,
            limit_per_source=args.limit,
            top_n=args.top,
            min_relevance=args.min_relevance,
            use_llm_summaries=args.llm_summaries,
            llm_model=args.llm_model,
            contact_email=args.contact_email,
            output_path=args.output_path,
            sub_questions=[q.strip() for q in args.sub_questions.split(";") if q.strip()] if args.sub_questions else None,
            auto_subquestions=args.auto_subquestions,
            reanalyze_from=args.reanalyze_from,
        )
    elif args.non_interactive:
        print("error: --non-interactive requires --field and --title", file=sys.stderr)
        return 2
    else:
        inputs = _interactive_topic_finder_inputs()
        # CLI flags still override/augment interactive answers where given.
        if args.sources:
            inputs.sources = args.sources.split(",")
        if args.sub_questions:
            inputs.sub_questions = [q.strip() for q in args.sub_questions.split(";") if q.strip()]
        inputs.limit_per_source = args.limit
        inputs.top_n = args.top
        inputs.min_relevance = args.min_relevance
        inputs.llm_model = args.llm_model
        inputs.contact_email = args.contact_email
        inputs.output_path = args.output_path
        inputs.auto_subquestions = args.auto_subquestions
        inputs.use_llm_summaries = inputs.use_llm_summaries or args.llm_summaries
        inputs.reanalyze_from = args.reanalyze_from

    try:
        report_path = run_topic_finder(inputs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"\nReport written to {report_path}")
    return 0


def _run_index_library_command(args: argparse.Namespace) -> int:
    sub_questions = [q.strip() for q in args.sub_questions.split(";") if q.strip()] if args.sub_questions else None

    if args.folder:
        inputs = LibraryIndexerInputs(
            folder=args.folder,
            recursive=args.recursive,
            extensions=args.extensions.split(",") if args.extensions else None,
            index_path=args.index_path,
            style=args.style,
            report_path=args.report_path,
            rescan=args.rescan,
            prune=args.prune,
            organize=args.organize,
            organize_to=args.organize_to,
            contact_email=args.contact_email,
            fetch_references=args.fetch_references,
            research_question=args.research_question,
            sub_questions=sub_questions,
            use_llm=args.llm_summaries,
            llm_model=args.llm_model,
        )
    elif args.non_interactive:
        print("error: --non-interactive requires --folder", file=sys.stderr)
        return 2
    else:
        inputs = _interactive_library_indexer_inputs()
        if args.extensions:
            inputs.extensions = args.extensions.split(",")
        inputs.index_path = args.index_path
        inputs.report_path = args.report_path
        inputs.rescan = args.rescan
        inputs.prune = args.prune
        inputs.organize = inputs.organize or args.organize
        if args.organize_to != "library/organized":
            inputs.organize_to = args.organize_to
        inputs.contact_email = args.contact_email
        inputs.fetch_references = inputs.fetch_references or args.fetch_references
        inputs.research_question = inputs.research_question or args.research_question
        inputs.sub_questions = inputs.sub_questions or sub_questions
        inputs.llm_model = args.llm_model
        inputs.use_llm = inputs.use_llm or args.llm_summaries

    try:
        stats = run_library_indexer(inputs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"\nIndexed {stats['new']} new file(s), skipped {stats['skipped']} unchanged, {stats['failed']} failed.")
    if stats["pruned"]:
        print(f"Pruned {stats['pruned']} missing file(s) from the index.")
    if stats["organized"]:
        print(f"Copied {stats['organized']} file(s) into {inputs.organize_to}")
    print(f"Index ({stats['total']} total entries): {stats['index_path']}")
    print(f"Report: {stats['report_path']}")
    return 0


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "topic-finder":
        return _run_topic_finder_command(args)
    if args.command == "index-library":
        return _run_index_library_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
