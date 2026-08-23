"""Command-line entry point for thesis-tools."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from .citations import STYLES
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


def _interactive_inputs() -> TopicFinderInputs:
    print("=== Thesis Topic Finder ===")
    print("Answer a few questions and I'll scan free literature databases")
    print("(Semantic Scholar, OpenAlex, Crossref, arXiv) to check how novel")
    print("your proposed topic is, and build you a starter bibliography.\n")

    field = _prompt("What field/discipline is your thesis in? (e.g. 'clinical psychology', 'computer science', 'marketing')", required=True)
    working_title = _prompt("What's your working thesis title (or best guess at one)?", required=True)
    research_question = _prompt("What's the core research question, if you have one? (optional, press Enter to skip)")
    extra_keywords = _prompt("Any extra keywords to include in the search? (comma-separated, optional)")
    style = _prompt(f"Citation style ({'/'.join(STYLES)})", default="apa")
    while style.lower() not in STYLES:
        print(f"  '{style}' isn't one of: {', '.join(STYLES)}")
        style = _prompt(f"Citation style ({'/'.join(STYLES)})", default="apa")

    use_llm = _prompt("Use Claude to write nicer paper summaries? Requires ANTHROPIC_API_KEY. (y/N)", default="n").lower().startswith("y")

    return TopicFinderInputs(
        field=field,
        working_title=working_title,
        research_question=research_question or None,
        extra_keywords=extra_keywords or None,
        style=style.lower(),
        use_llm_summaries=use_llm,
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
    tf.add_argument("--llm-summaries", action="store_true", help="Use Claude for paper summaries (needs ANTHROPIC_API_KEY + `pip install anthropic`)")
    tf.add_argument("--llm-model", default="claude-sonnet-5", help="Model to use for --llm-summaries")
    tf.add_argument("--contact-email", help="Optional email sent to OpenAlex/Crossref's 'polite pool' for faster, more reliable responses")
    tf.add_argument("-o", "--output", dest="output_path", help="Where to write the Markdown report (default: output/<slug>-<timestamp>.md)")
    tf.add_argument("--non-interactive", action="store_true", help="Don't prompt for missing values; fail instead if --field/--title are missing")

    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "topic-finder":
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
            )
        elif args.non_interactive:
            print("error: --non-interactive requires --field and --title", file=sys.stderr)
            return 2
        else:
            inputs = _interactive_inputs()
            # CLI flags still override/augment interactive answers where given.
            if args.sources:
                inputs.sources = args.sources.split(",")
            inputs.limit_per_source = args.limit
            inputs.top_n = args.top
            inputs.min_relevance = args.min_relevance
            inputs.llm_model = args.llm_model
            inputs.contact_email = args.contact_email
            inputs.output_path = args.output_path
            inputs.use_llm_summaries = inputs.use_llm_summaries or args.llm_summaries

        try:
            report_path = run_topic_finder(inputs)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        print(f"\nReport written to {report_path}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
