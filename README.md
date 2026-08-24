# thesis-tools

A local toolkit for working through a thesis or dissertation, built one part at a time.

I build this as I struggled during my masters to "master" the literature review, I didn't use Ai much at the time, but now with AI it can be easier to evaluate and help co-think about your dissertation. So I've built these tools. The goal isn't to write your dissertation quickly, its actually to help you plan and research your literature review.

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

### Which Claude model gets used

Left alone, the toolkit picks from two tiers rather than using one model
everywhere:

- **`claude-sonnet-5`** for the one-shot, quality-sensitive calls that only
  happen once (or a handful of times) per run: Part 1's sub-question
  generation and Part 3's literature-review drafting.
- **`claude-haiku-4-5`** for the bulk, per-paper work: abstract/excerpt
  summaries and sub-question stance classification (supports/challenges/
  mixed/unrelated). This runs once per paper — or once per paper per
  sub-question — so it's the majority of a run's actual token spend, and
  classification-style work doesn't need a larger model to do well.

Pass `--llm-model` explicitly (e.g. `--llm-model claude-opus-5`) to override
both tiers at once for that run, if a particular draft or analysis is worth
the extra cost — an explicit choice always wins over the automatic default,
uniformly across everything that command does.

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

**Every downloaded paper is also added straight to Part 2's library index**
(`library/index.json` by default, or wherever `index-library` last wrote to
— override with `--library-index-path`) — no DOI/title lookup needed, since
the metadata already came straight from the source API that found it. This
means a paper `topic-finder` finds and downloads for your topic/sub-
questions shows up in `visualize-library` and `literature-review`'s
library-index path too, not just this run's own report — one shared
library, however a paper first got found.

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

Relevance scoring, "what it's about" summaries, and sub-question stance
classification all use whichever text is actually available: a paper's
abstract when it has one, otherwise the text extracted from the file
itself. Most locally-indexed PDFs have no machine-readable abstract field
at all (extraction grabs raw page text, not a parsed abstract), so this
matters — without it, every such paper would score near-zero relevance and
read as "unrelated" to every sub-question regardless of what it actually
says. Extraction itself keeps the **entire document**, not a prefix of it
— a whole 40-page PDF, not just the first few pages — since these are pure
local computations with no per-call cost; only what actually gets sent to
Claude (stance classification, literature-review synthesis) applies its
own separate, much smaller truncation, so a longer extraction never
translates into a bigger API bill.

Every extracted file also gets its full text saved as a plain `.txt` under
`processed/text/` (`--processed-dir` to change where), so you can open any
paper's extracted text directly and confirm it's complete — the same
location and naming Part 1's `--download-papers` uses, so both land in one
place regardless of which part found the paper.

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

Progress prints as it goes, not just a summary at the end: a `[3/22]`
counter and filename before each file starts, then what happened to it —
how many candidate DOIs were found and each one being resolved, a title
search if no DOI panned out, the final outcome (verified via DOI/title
match or left unresolved), how many references were fetched (with
`--fetch-references`), and where its extracted text was saved — so a long
run over a big folder shows what it's actually doing rather than sitting
silent, and a slow file shows exactly which network call it's waiting on.

DOI discovery only searches roughly the first page of a file's extracted
text, not the whole document — a paper's own DOI is always printed there,
while its bibliography (now that extraction keeps the whole document, see
above) can contain dozens of *other* papers' DOIs. Searching the whole
thing would mean several real network round-trips per file trying each one
in turn — noticeably slow — and risks resolving a citation instead of the
paper itself.

After the per-file loop finishes, a second pass recomputes relevance
scores, summaries, and sub-question stances for **every** entry in the
index (not just the ones just scanned) — this is what keeps
`--question`/`--sub-questions` updates instant on a rerun without
rescanning files, but with `--llm-summaries` it's a Claude call per paper,
so it also gets its own progress notice and, per paper, a counter and
title while it's classifying — the same visibility as the scan phase
above, not a silent gap between "files indexed" and the final summary
line.

Run `python -m thesis_tools index-library --help` for all options.

### Visualizing what's indexed

```bash
python -m thesis_tools visualize-library
```

Renders a single self-contained HTML file (`library/visualization.html` by
default — open it straight in a browser, no server needed) from the index
`index-library` already built. It automatically reuses whatever research
question/sub-questions Part 1/`configure` already saved (`--question` and
`--sub-questions` to override, `--llm-summaries` to classify with Claude
instead of the heuristic):

- **Coverage by sub-question** — the page's anchor, shown first: for each
  sub-question, how many indexed papers support it, challenge it, or give
  mixed evidence — the same classification Part 2's Markdown report and
  Part 3's literature review both already compute, so all three agree. A
  sub-question with zero supporting papers is called out explicitly (and
  flagged below in "Weaknesses") rather than the page just being
  library-wide stats with no connection to your actual research questions.
- **Relevance to your questions** — a grid with one row per paper and one
  column per question: a bar for how relevant the paper is to your overall
  research question, then a coloured cell per sub-question showing whether
  that paper supports it (`+`), challenges it (`−`), gives mixed evidence
  (`~`), or says nothing useful (`·`). Rows are sorted most-relevant first,
  so the papers earning their place are at the top and the ones you should
  probably drop are at the bottom. Supports/challenges use a diverging
  blue↔red pair rather than green/red — a paper challenging your assumption
  is the opposite pole of one supporting it, not a bad outcome — and every
  cell carries its glyph and a written label too, so the colour never
  carries the meaning on its own.
- **How your papers connect** — an arc diagram of your library's *internal*
  citation structure: each dot is one indexed paper, ordered oldest to
  newest, and an arc joins two papers when one cites the other. Hover or tab
  a dot to isolate just its links. It reports how many of your papers are
  connected to at least one other, how many citation links there are, and
  how many stand alone — a paper nothing else in your library talks to is a
  real finding, not an absence to hide. (This replaced a force-directed
  graph, which turned a few dozen papers into an unreadable hairball whose
  shape changed every run; an arc diagram fixes the papers on a meaningful
  axis, so the layout is deterministic and labels can't collide.)
- **Papers worth adding next** — the works your own papers cite that you
  *don't* have, ranked by how many of your papers cite each one, since
  something several of your sources lean on is usually foundational. Each
  gets a direct DOI link when one's known, plus pre-filled Google Scholar
  and ScienceDirect search links as a fallback — the same deep-search
  pattern used for "Needs manual review" — so you can track one down in one
  click instead of retyping the title. Needs `--fetch-references`.
- **Where your metadata came from** — a bar chart of how many papers were
  verified via each source (Crossref, Semantic Scholar, OpenAlex, arXiv) vs.
  resolved from local file metadata alone.
- **Verification confidence** — DOI-verified vs. title-match-verified vs.
  unresolved.
- **Publication years** — a bar chart across your library (binned into
  5-year buckets if the range is wide).
- **Citation coverage** — the same included-vs-missing breakdown as the
  Markdown report's "Citation coverage" section (needs `--fetch-references`
  to have been used at least once).
- **Weaknesses worth a second look** — computed flags, not just raw counts:
  unresolved files, possible duplicate downloads, a high share of papers
  with no abstract on record, over-reliance on a single source (70%+ from
  one database), a high share of cited references still missing, a library
  skewed toward older papers, papers that don't relate to **any** of your
  sub-questions (classified "unrelated" to all of them — worth confirming
  they still belong, or that a sub-question is missing to cover them), and
  — with `--question` set — papers with low relevance to your actual
  research question. Each flag lists the specific files/papers involved —
  with the same find-it links where relevant — not just a percentage.

**With `--llm-summaries`, stance classifications are cached per paper**
(`library/stance_cache.json` by default, next to `--index-path` — override
with `--stance-cache-path`), so re-running `visualize-library` on an
unchanged library and unchanged sub-questions costs nothing: only a paper
whose text actually changed (e.g. a fuller re-extraction) or a changed
sub-question set triggers a fresh Claude call, restoring the "cheap to
regenerate any time" promise this command otherwise makes. Pass
`--no-stance-cache` to always reclassify from scratch.

### Downloading a literature-review matrix

Every `visualize-library` run also writes a companion Excel file —
`library/literature_matrix.xlsx` by default, next to `--output` — with a
**⬇ Download as Excel** link right at the top of the HTML page. One row per
indexed paper, in the "synthesis matrix" format literature-review guidance
commonly recommends for tracking sources: citation (in whatever `--style`
you've configured), authors, year, title, venue, DOI, verification status,
a free local summary, relevance to your research question (when `--question`
is set), the local file path, and — when sub-questions are configured — one
column per sub-question showing that paper's supports/challenges/mixed/
unrelated stance. It's a real spreadsheet: frozen header row, autofilter,
and sortable/filterable like any other `.xlsx`, so you can work the review
outside a browser, add your own notes column, or hand it to a supervisor.

Building the matrix never triggers a second round of Claude calls — it
reuses whichever stance classification (cached or freshly made) the HTML
page's own `--llm-summaries` run already computed. Use `--matrix-path` to
write it somewhere else, or `--no-matrix` to skip generating it and just get
the HTML page.

It's pure local computation over the existing index — no network calls, so
it's cheap to regenerate (`-o some/path.html` to change where it's written)
any time you re-run `index-library`.

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
  (reusing Part 1/2's stance analysis) — when a sub-question has more
  candidate papers than fit in one drafting call, **both sides of the
  debate are kept**: papers are picked in relevance-to-this-sub-question
  order, alternating across supports/challenges/mixed, so a handful of
  challenging papers is never crowded out by a larger pile of supporting
  ones.
- **With Claude** (default — uses `claude-sonnet-5`; override with
  `--llm-model claude-opus-5` if a particular draft is worth the extra cost):
  writes a real 150-250 word synthesis paragraph following standard
  literature-review conventions — synthesizing by theme rather than
  listing sources one by one (no "Smith (2020) found X. Jones (2019) found
  Y." laundry-listing), and using a *sparing* direct quotation only when
  exact wording earns its place, otherwise paraphrasing. **When the papers
  disagree, the paragraph debates it**: the case for, then the case
  against, then a brief critical evaluation of which side's evidence is
  stronger (or why they might reasonably disagree) — rather than a single
  throwaway line noting a disagreement exists.
- **Without Claude** (`--no-llm`, or no API key): a structured bullet outline
  grouped by stance instead of prose — still useful, just not narrative.
- **In-text citations match whatever style you've configured** (`--style` —
  APA/Harvard: `(Smith, 2020)`; Chicago author-date: `(Smith 2020)`; MLA:
  `(Smith)`/`(Smith 15)`; IEEE: numbered `[3]`, assigned by order of first
  citation and matching the reference list's own numbering) — Claude is
  handed the exact marker to use for each paper rather than guessing at
  style rules itself, so the in-text citations and the final reference list
  never mismatch.

**Full document text goes into the drafting prompt, not a truncated
excerpt** — the whole point of debating both sides properly is seeing each
paper's actual argument, not just whatever fell in the first few thousand
characters. **Quoting is grounded in real text, not just abstracts.** For
papers Part 2 indexed locally, the draft has access to the actual extracted
document text (with page markers for PDFs), not only the abstract — so a
direct quotation can be a real sentence from the paper, cited with a real
page number. Any quotation must be copied verbatim from that text or the
abstract; Claude is explicitly instructed to never invent or reconstruct a
quotation from memory, and to paraphrase instead if extracted text looks
garbled (PDF extraction can introduce broken hyphenation or OCR noise).
Papers found only via Part 1's search APIs have just an abstract — those get
paraphrased, not quoted, and the draft's header reports how many of your
sources have real text available so you know which claims to double-check
hardest.

The draft also gets an introduction and a closing **"Conclusion and Areas
for Further Research"** section — a brief synthesis of the review as a
whole, plus an explicit bulleted list of concrete further-research
directions drawn from sub-questions where the literature disagrees with
itself and sub-questions with no coverage at all (i.e. candidate
contributions for your thesis) — and a reference list containing only the
papers actually cited in the draft.

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
  stance_cache.py     Persists analyze_subquestions()'s per-paper Claude classifications so an
                      unchanged paper/question set is never reclassified (used by visualize-library)
  citations.py        APA / MLA / Chicago / Harvard / IEEE reference-list formatting, plus
                      in_text_citation() for the parenthetical/numbered marker used inline
  report.py           Renders Part 1's Markdown report
  topic_finder.py     Orchestrates Part 1 (search/dedupe/score/analyze/report + reanalyze cache)
  literature_review.py Orchestrates Part 3 (load -> dedupe -> synthesize -> draft)
  library/
    extract.py         Per-file-type text/metadata extraction (PDF/docx/txt/HTML)
    identify.py         DOI/title resolution against Crossref + Semantic Scholar
    index_store.py       The JSON-backed local index (library/index.json)
    citation_graph.py    Citation-coverage computation, internal citation links, Mermaid mind-map
    organizer.py         Optional copy-only file organizer
    report.py            Renders Part 2's Markdown report
    library_indexer.py   Orchestrates Part 2
    visualize.py          Computes + renders the `visualize-library` HTML page
    literature_matrix.py  Builds the companion Excel synthesis-matrix workbook
  cli.py              `topic-finder` / `index-library` / `visualize-library` / `literature-review` / `configure` commands
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
