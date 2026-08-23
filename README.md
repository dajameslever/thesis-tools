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

### Setting things up before running anything else

You don't have to wait until Part 1 asks — `thesis-tools configure` sets
(and remembers) your field, title, research question, sub-questions, and
**citation style** directly, with no search involved:

```bash
python -m thesis_tools configure --style ieee --field "clinical psychology"
```

Run it with no flags for an interactive prompt (pre-filled with whatever's
already saved — press Enter to keep a value), `--show` to print the current
settings without changing anything, and `--no-llm-summaries` / `--llm-summaries`
to set your Claude preference explicitly. Every later `topic-finder`,
`index-library`, or `literature-review` run picks these up automatically —
including with `--non-interactive`, once field/title are set this way.

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
expected and handled gracefully. Semantic Scholar's unauthenticated tier
shares a strict, global rate limit, so a `429` from it is routine rather
than a sign of trouble — the client retries a couple of times with backoff
before giving up and just proceeding with whatever the other three sources
found. An occasional empty/`null` response body under load is handled the
same way rather than raising. It's also normal for the same query against
different sources to turn up zero overlap after de-duplication: each runs
its own relevance ranking over a different corpus, so their top results
genuinely don't have to intersect. When neither of the above can verify
something (see Part 2's "Needs manual review"), the report hands you a
pre-filled **Google Scholar** / **ScienceDirect** search link instead — not an
API call, just a deep link, so you can finish the check by hand in one click.

In Part 2, one file's DOI/title verification blowing up (a flaky API call,
an unexpected response shape) never aborts indexing the rest of the folder,
and never means losing that file either: it still gets indexed from the
PDF's own extracted title/author/year alone, flagged `unresolved` in
"Needs manual review" — same as when verification runs cleanly but finds no
match. An actually unreadable file (corrupt, unsupported format) is the
only thing that gets skipped outright, since there's no metadata to fall
back to in that case.

**Treat all of this as a fast first pass, not a substitute for a full
literature review** — always also check your own institution's library
database before finalizing a topic.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

(`requirements.txt` pins `urllib3<2` — on a Python built against LibreSSL
instead of OpenSSL, which is common for macOS system/Homebrew Python, `urllib3`
2.x prints a `NotOpenSSLWarning` on every run; 1.x has no such check and works
identically here.)

The `anthropic` package is installed by default (it's in `requirements.txt`),
so Claude-drafted summaries, sub-question suggestions, stance analysis, and
literature-review prose are available the moment you set `ANTHROPIC_API_KEY`
— no separate install step. When a key is present, every interactive prompt
defaults to "yes, use Claude" — you don't have to remember to opt in.

You don't have to set the environment variable yourself: if you answer "yes"
to using Claude in an interactive prompt and no key is found, the tool asks
for it right there (input hidden) and offers to remember it in a local
`.env` file for next time — `.env` is git-ignored, and the key is never
written into the shared `thesis_tools_project.json`.

## Part 1: Topic Finder

### Usage

Interactive (recommended the first time):

```bash
python -m thesis_tools topic-finder
```

A bare `topic-finder` with no flags always walks through the interactive
prompts — even once `configure` or an earlier run has already saved a
field/title/style to the project file, so a fresh run through the checklist
(sub-question confirmation included) happens every time, not just the
first. Passing `--field` and `--title` directly, or `--non-interactive`,
skips straight to searching using saved/given values instead.

Sub-questions are always confirmed, never just assumed, whatever state
they're in when the prompt starts:

- **Blank, Claude enabled:** it suggests 3-4 for your topic, prints them,
  and asks you to confirm before anything else happens — no search or
  per-paper analysis runs against an unconfirmed batch. Accept as-is, or
  decline and type your own instead.
- **Already saved from a previous run:** they're printed again rather than
  reused silently. With Claude enabled you get a real choice — `Keep
  these, or have Claude suggest fresh ones for this run? (keep/suggest)` —
  so opting into Claude actually gets you fresh recommendations rather than
  the old batch by default. Without Claude, it's a plain `Keep these
  sub-questions? (Y/n)`; declining lets you type new ones.
- **Still blank after all of that** (Claude off and you skipped past the
  "type your own" prompt too): it says so explicitly — `No sub-questions
  set — the report won't include stance/compare-and-contrast analysis` —
  and asks `Continue without sub-questions? (y/N)` before proceeding,
  giving one more chance to enter some rather than silently running with
  zero.

Running non-interactively (`--field`/`--title` given directly, no human to
confirm with) still shows whatever Claude generated in the console output,
so you can see — and re-run with `--sub-questions` to override — what was
used. Either way, the sub-questions actually used are saved back into the
shared project file, so `index-library`/`literature-review` reuse the same
ones.

Also available, opt-in: `--download-papers` (or the matching interactive
prompt) downloads each shortlisted paper's PDF where — and only where — a
source API itself reports an open-access copy (arXiv, Semantic Scholar's
`openAccessPdf`, OpenAlex's best OA location), extracts its text, and saves
both under `--download-dir` (default: `processed/`) as `processed/pdfs/
<slug>.pdf` and `processed/text/<slug>.txt`. It never follows a paywalled or
scraped link, and papers with no known open-access copy are silently
skipped. This is the same extraction Part 2 uses on local files, so the
resulting excerpt can ground a direct quotation in Part 3's literature
review rather than just an abstract.

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

Or non-interactively — if you've already run `topic-finder` or
`thesis-tools configure` here, you can skip `--question`/`--sub-questions`/
`--style` entirely and it'll reuse what's already saved:

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
- **With Claude** (default — and defaults to `claude-opus-5`, not Sonnet,
  since well-written prose benefits more from the stronger model than the
  classification-style work in Parts 1/2; override with `--llm-model`):
  writes a real 150-250 word synthesis paragraph following standard
  literature-review conventions — synthesizing by theme rather than
  listing sources one by one (no "Smith (2020) found X. Jones (2019) found
  Y." laundry-listing), and using a *sparing* direct quotation only when
  exact wording earns its place, otherwise paraphrasing.
- **Without Claude** (`--no-llm`, or no API key): a structured bullet outline
  grouped by stance instead of prose — still useful, just not narrative.

**Quoting is grounded in real text, not just abstracts.** For papers Part 2
indexed locally, the draft has access to the actual extracted document text
(with page markers for PDFs), not only the abstract — so a direct quotation
can be a real sentence from the paper, cited with a real page number. Any
quotation must be copied verbatim from that text or the abstract; Claude is
explicitly instructed to never invent or reconstruct a quotation from
memory, and to paraphrase instead if extracted text looks garbled (PDF
extraction can introduce broken hyphenation or OCR noise). Papers found only
via Part 1's search APIs have just an abstract — those get paraphrased, not
quoted, and the draft's header reports how many of your sources have real
text available so you know which claims to double-check hardest.

The draft also gets an introduction, a closing **"gaps and tensions"**
section (surfacing disagreements and sub-questions with no coverage at all —
i.e. candidate contributions for your thesis), and a reference list
containing only the papers actually cited in the draft.

> ⚠️ **This is a draft, not a citable final product.** Claims about papers
> Part 2 indexed locally draw on real extracted text; claims about papers
> found only via Part 1's search draw on the abstract only. Either way,
> verify every claim (and any quote) against the source before relying on
> it, and rewrite it in your own voice.

Run `python -m thesis_tools literature-review --help` for all options.

### Citation styles

APA 7, MLA 9, Chicago (author-date), Harvard, and IEEE are supported
(`--style`) in all three parts. Set it once with `thesis-tools configure
--style ...` and every part reuses it from then on. These are **best-effort
formatters** built from whatever metadata the free APIs return — always
sanity-check the generated bibliography against your university's exact
style requirements before submitting.

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
  env.py              Minimal .env support for ANTHROPIC_API_KEY (git-ignored, not the shared project file)
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
  cli.py              `topic-finder` / `index-library` / `literature-review` / `configure` commands
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
