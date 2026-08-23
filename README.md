# thesis-tools

A local toolkit for working through a thesis, built one part at a time.

- **Part 1 — Topic Finder:** pick/pressure-test a thesis title, break it into
  sub-questions, and check the literature for overlap, agreement, and conflict.
- **Part 2 — Library Indexer:** scan a folder of downloaded papers (PDF/docx/
  txt/HTML) and turn it into a verified, cited, searchable index.
- **Part 3 — Literature Review Drafter:** turn what Parts 1 and 2 found into
  a structured literature review draft, organized around your sub-questions.

All three share a **project file** (`thesis_tools_project.json`, created next
to wherever you run the tool) holding your field, working title, research
question, sub-questions, citation style, and Claude preference. **Answer
these once, in whichever part you run first — every later command reuses
them automatically and only asks for whatever's still missing.** Pass
`--question`/`--sub-questions`/`--style`/etc. explicitly at any point to
override what's saved, or point `--project-file` elsewhere to run more than
one thesis project side by side.

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
| [Semantic Scholar](https://www.semanticscholar.org/) | Broad coverage across most fields, includes abstracts, and each paper's own reference list |
| [OpenAlex](https://openalex.org/) | Very broad coverage (successor to Microsoft Academic Graph) |
| [Crossref](https://www.crossref.org/) | Metadata for nearly all published journal articles — best for catching an exact title/DOI match even on a paywalled paper |
| [arXiv](https://arxiv.org/) | Preprints in CS / physics / math / stats |

If your field isn't STEM, arXiv will just return nothing for it — that's
expected and handled gracefully. When neither of the above can verify
something (see Part 2's "Needs manual review"), the report hands you a
pre-filled **Google Scholar** / **ScienceDirect** search link instead — not an
API call, just a deep link, so you can finish the check by hand in one click.

**Treat all of this as a fast first pass, not a substitute for a full
literature review** — always also check your own institution's library
database before finalizing a topic.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For Claude-drafted summaries, sub-question suggestions, stance analysis, and
literature-review prose instead of the built-in heuristics: `pip install
anthropic` and set `ANTHROPIC_API_KEY`. When a key is present, every
interactive prompt defaults to "yes, use Claude" — you don't have to
remember to opt in.

## Part 1: Topic Finder

### Usage

Interactive (recommended the first time):

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
  --sub-questions "Does it affect risk-taking?;Does it affect working memory?" \
  --style apa
```

This writes a Markdown report to `output/<slug>-<timestamp>.md` containing:

1. **A novelty check** — any existing paper with a near-identical title is
   flagged ⚠️, and papers with high title overlap are flagged 🟠, so you see
   immediately if your exact question has already been answered.
2. **Sub-questions** (3-4, your own or Claude-suggested) — each found paper
   is checked against every sub-question and marked ✅ supports / ❌
   challenges / ⚖️ mixed, with a **"Where the literature disagrees"**
   callout wherever papers land on both sides of the same sub-question —
   often exactly the gap a thesis can sit in.
3. **Ranked related work** — the most relevant papers found, each with a
   short summary, its stance on your sub-questions, and a fully formatted
   citation.
4. **Compare and contrast** — a table of everything found side by side
   (year, recency, relevance, citation count, stances), plus a note when the
   set spans enough years that an older source may have been superseded.
5. **A full bibliography** in your chosen style, ready to paste into your
   thesis's reference list.
6. **Suggested next steps** for narrowing/differentiating your topic.

Run `python -m thesis_tools topic-finder --help` for all options.

#### Changing your sub-questions without re-searching

Every run also saves `<report>.papers.json` — the exact set of papers found.
If you just want to tweak your sub-questions (or citation style) and see
updated relevance/stances, you don't need to re-hit the search APIs:

```bash
python -m thesis_tools topic-finder \
  --field "clinical psychology" --title "..." \
  --reanalyze output/your-report.md.papers.json \
  --sub-questions "A new set of sub-questions;Another one"
```

## Part 2: Library Indexer

Scans a folder (e.g. `~/Downloads`) for papers you've already downloaded —
PDF, `.docx`, `.txt`, or saved HTML — and builds a verified, cited index of
them, without ever renaming, moving, or modifying your original files unless
you explicitly ask it to.

### Usage

Interactive:

```bash
python -m thesis_tools index-library
```

Or non-interactively — if you've already run `topic-finder` in this folder,
you can skip `--question`/`--sub-questions`/`--style` entirely and it'll
reuse what you already told Part 1:

```bash
python -m thesis_tools index-library --folder ~/Downloads
```

For each file, it:

1. Looks for a DOI in the file and resolves it against Crossref (falling back
   to Semantic Scholar) for **canonical, verified metadata**.
2. If no DOI is found, builds a best-effort title from the file's own
   metadata/text and confirms it via a title search — still verified, just a
   different route.
3. Otherwise falls back to local heuristics and flags the file **"needs
   manual review"** — with one-click Google Scholar / ScienceDirect search
   links so you can track down the canonical record yourself.

The resulting report (`library/library.md` by default, alongside a
`library/index.json` you can inspect or version-control) includes, per paper:

- **What it's about** (an abstract summary), **contributors**, and **how
  recent** it is.
- **Relevance to your research question** and **stances on your
  sub-questions** (reused from Part 1, or pass `--question`/`--sub-questions`
  to set/override them here) — re-running with different questions updates
  these instantly without re-scanning your files.
- **Citation coverage** (with `--fetch-references`): each paper's own
  reference list is checked against what's already in your library, and
  references cited by 2+ of your papers but still missing are surfaced as
  **recurring gaps** — often older, foundational works worth tracking down —
  alongside a Mermaid mind-map diagram of what's included (✅) vs. missing (❌).
- **Possible duplicate downloads** (the same DOI saved to two files).

Rerunning is incremental: unchanged files (by content hash) are skipped, so
you can point it at a growing Downloads folder repeatedly. Use `--rescan` to
force re-extraction, `--prune` to drop entries whose file was deleted, and
`--organize --organize-to some/folder` to get **copies** (never the
originals) renamed to a clean `Author_Year_Title.ext` scheme.

Run `python -m thesis_tools index-library --help` for all options.

## Part 3: Literature Review Drafter

Turns whatever Part 1 (topic search) and/or Part 2 (your library) already
found into a structured literature review draft, organized around your
sub-questions — **no new searching happens**, so it's fast and free of API
rate limits regardless of your library's size.

### Usage

Interactive:

```bash
python -m thesis_tools literature-review
```

Or non-interactively — after running `topic-finder` and/or `index-library`,
this needs nothing else:

```bash
python -m thesis_tools literature-review
```

It draws papers from Part 1's `<report>.papers.json` and/or Part 2's
`library/index.json` (auto-detected from the project file; override with
`--topic-cache`/`--library-index`), merges and de-duplicates them, then for
each sub-question:

- Gathers the papers that support, challenge, or give mixed evidence on it
  (reusing Part 1/2's stance analysis).
- **With Claude** (default, needs `ANTHROPIC_API_KEY`): writes a real
  150-250 word synthesis paragraph **grounded only in the abstracts you
  already have**, with in-text `(Author, Year)` citations — explicitly
  instructed to never invent findings, and to say so plainly when the
  literature doesn't actually address the sub-question.
- **Without Claude** (`--no-llm`, or no API key): a structured bullet outline
  grouped by stance instead of prose — still useful, just not narrative.

The draft also gets an introduction, a closing **"gaps and tensions"**
section (surfacing disagreements and sub-questions with no coverage at all —
i.e. candidate contributions for your thesis), and a reference list
containing only the papers actually cited in the draft.

> ⚠️ **This is a draft, not a citable final product.** It's synthesized from
> abstracts, not full papers — verify every claim against the source before
> relying on it, and rewrite it in your own voice.

Run `python -m thesis_tools literature-review --help` for all options.

### Citation styles

APA 7, MLA 9, Chicago (author-date), Harvard, and IEEE are supported
(`--style`) in all three parts. These are **best-effort formatters** built
from whatever metadata the free APIs return — always sanity-check the
generated bibliography against your university's exact style requirements
before submitting.

## Project layout

```
thesis_tools/
  sources/            API clients: Semantic Scholar, OpenAlex, Crossref, arXiv
                       (search, DOI lookup, and — Semantic Scholar only — a
                       paper's own reference list)
  project.py          Shared cross-part state (thesis_tools_project.json)
  dedupe.py           Merges the same paper found via multiple sources
  relevance.py        Keyword extraction + relevance/title-similarity scoring
  recency.py          "How old is this, relative to now and its peers?"
  links.py            Google Scholar / ScienceDirect deep-search link builders
  llm.py              Shared optional Claude client (used across all three parts)
  summarize.py        Extractive (default) or Claude-powered abstract summaries
  subquestions.py     Sub-question generation + supports/challenges/mixed stance analysis
  citations.py        APA / MLA / Chicago / Harvard / IEEE formatting
  report.py           Renders Part 1's Markdown report
  topic_finder.py     Orchestrates Part 1 (search/dedupe/score/analyze/report + reanalyze cache)
  literature_review.py Orchestrates Part 3 (load -> dedupe -> synthesize -> draft)
  library/
    extract.py         Per-file-type text/metadata extraction (PDF/docx/txt/HTML)
    identify.py         DOI/title resolution against Crossref + Semantic Scholar
    index_store.py       The JSON-backed local index (library/index.json)
    citation_graph.py    Citation-coverage computation + Mermaid mind-map
    organizer.py         Optional copy-only file organizer
    report.py            Renders Part 2's Markdown report
    library_indexer.py   Orchestrates Part 2
  cli.py              `topic-finder` / `index-library` / `literature-review` commands
tests/                Unit tests (network calls are mocked; PDF/docx tests use real files)
```

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Roadmap

Parts 1, 2, and 3 are done. Contributions/ideas welcome — this is meant to
keep growing (e.g. exporting the draft review straight into a Word doc, or
turning the sub-questions into a full thesis outline).
