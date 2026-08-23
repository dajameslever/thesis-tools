# thesis-tools

A local toolkit for working through a thesis, built one part at a time.

## Part 1: Topic Finder

Helps you pick (or pressure-test) a thesis title/research question by scanning
free literature databases for closely related existing work — so you don't
spend months on a question someone already answered — and generates a starter
bibliography in your citation style of choice.

### What it searches, and why not ScienceDirect / Google Scholar

Neither ScienceDirect nor Google Scholar offers a way for a tool like this to
query them directly:

- **ScienceDirect** (Elsevier) requires a paid API subscription / institutional
  access agreement.
- **Google Scholar** has no public API at all, and automated querying violates
  its Terms of Service (it also actively blocks scraping).

Instead, this tool uses four **free, no-API-key** scholarly sources that
together cover essentially the same ground for a novelty check:

| Source | Good for |
|---|---|
| [Semantic Scholar](https://www.semanticscholar.org/) | Broad coverage across most fields, includes abstracts |
| [OpenAlex](https://openalex.org/) | Very broad coverage (successor to Microsoft Academic Graph) |
| [Crossref](https://www.crossref.org/) | Metadata for nearly all published journal articles — best for catching an exact title match even on a paywalled paper |
| [arXiv](https://arxiv.org/) | Preprints in CS / physics / math / stats |

If your field isn't STEM, arXiv will just return nothing for it — that's
expected and handled gracefully. **Treat this as a fast first pass, not a
substitute for a full literature review** — always also check your own
institution's library database before finalizing a topic.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

(Optional, for nicer AI-written summaries instead of extractive ones: `pip
install anthropic` and set `ANTHROPIC_API_KEY`.)

### Usage

Interactive (recommended the first time — it'll ask your field, working
title, research question, keywords, and citation style):

```bash
python -m thesis_tools topic-finder
```

Or non-interactively, e.g. for scripting:

```bash
python -m thesis_tools topic-finder \
  --field "clinical psychology" \
  --title "The effect of sleep deprivation on adolescent decision-making" \
  --question "Does chronic sleep deprivation impair risk-based decision-making in adolescents?" \
  --keywords "sleep deprivation, adolescents, decision-making, risk" \
  --style apa
```

This writes a Markdown report to `output/<slug>-<timestamp>.md` containing:

1. **A novelty check** — any existing paper with a near-identical title is
   flagged ⚠️, and papers with high title overlap are flagged 🟠, so you see
   immediately if your exact question has already been answered.
2. **Ranked related work** — the most relevant papers found, each with a
   short summary and a fully formatted citation.
3. **A full bibliography** in your chosen style, ready to paste into your
   thesis's reference list.
4. **Suggested next steps** for narrowing/differentiating your topic if there
   turns out to be overlap.

Run `python -m thesis_tools topic-finder --help` for all options (sources to
use, how many results per source, relevance threshold, output path, etc).

### Citation styles

APA 7, MLA 9, Chicago (author-date), Harvard, and IEEE are supported
(`--style`). These are **best-effort formatters** built from whatever
metadata the free APIs return — always sanity-check the generated
bibliography against your university's exact style requirements before
submitting.

## Project layout

```
thesis_tools/
  sources/          API clients for Semantic Scholar, OpenAlex, Crossref, arXiv
  dedupe.py         Merges the same paper found via multiple sources
  relevance.py      Keyword extraction + relevance/title-similarity scoring
  summarize.py      Extractive (default) or Claude-powered abstract summaries
  citations.py      APA / MLA / Chicago / Harvard / IEEE formatting
  report.py         Renders the Markdown report
  topic_finder.py   Orchestrates the above into the Part 1 pipeline
  cli.py            `thesis-tools topic-finder` command (interactive + flags)
tests/              Unit tests (network calls are mocked)
```

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Roadmap

Part 1 (topic/title finder + novelty check) is done. Planned next:

- **Part 2:** structuring a thesis outline/proposal from the chosen topic.
- **Part 3:** ongoing reference management as you read and write (import the
  Part 1 bibliography, add new sources, re-export in any style).

Contributions/ideas welcome — this is meant to grow part by part.
