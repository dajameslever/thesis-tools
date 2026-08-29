# thesis-tools (Literature Review)

A local toolkit for working through a thesis or dissertation's literature review, built one part at a time.

I build this as I struggled during my masters to "master" the literature review, I didn't use Ai much at the time, but now with AI it can be easier to evaluate and help co-think about your dissertation. So I've built these tools. The goal isn't to write your dissertation quickly, its actually to help you plan and research your literature review.

This works best with claude, you need an api version of claude - goto console.claude.ai and purchase some credits - about $10 should be sufficient. The code tries to re-use outputs and use AI efficiently, but i'm sure there's room for improvement. 

Go through the steps to be the most efficient. 

- **Part 1 — Topic Finder:** pick/pressure-test a thesis title, break it into
  sub-questions, and check the literature for overlap, agreement, and conflict.
- **Part 2 — Library Indexer:** scan a folder of downloaded papers (PDF/docx/
  txt/HTML) and turn it into a verified, cited, searchable index.
- **Part 2a - Visualisation:** this visualises Part 2 and helps you find more sources, it also builds your index as an excel source. 
- **Part 3 — Literature Review Drafter:** turn what Parts 1 and 2 found into
  a structured literature review draft, organized around your sub-questions.

Spend a lot of time with part 2 and 2a - find more sources, ingest, review. 
Decide if your question is good enough etc. Go back to part 1 if you need to change it. 

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

`--fetch-references` can be added later. Re-running with it on an already
indexed library backfills only what is missing: each entry that has a
resolved DOI but no reference list gets one fetched, with no re-extraction
and no re-identification of files that haven't changed. Entries that never
resolved a DOI have nothing to fetch against and are reported as such, since
those are the same unresolved files that hollow out every other view.

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
- **Where to explore next** — a mind-map tree of where to go from what you
  already have. Every paper is a collapsed branch showing how many works it
  cites that you haven't imported; expand one to see them, each with a
  direct DOI link when one's known plus Google Scholar / ScienceDirect
  search links, alongside the works it cites that you *do* already hold.
  Branches are ordered by how much unexplored work each paper opens up, so
  the paper that leads furthest is first. Built from nested `<details>`, so
  expanding works with no JavaScript, from the keyboard, and in a screen
  reader — and a paper citing eighty works costs nothing until you open it.
- **Papers worth adding next** — the works your own papers cite that you
  *don't* have, ranked by how many of your papers cite each one, since
  something several of your sources lean on is usually foundational. Each
  gets a direct DOI link when one's known, plus pre-filled Google Scholar
  and ScienceDirect search links as a fallback — the same deep-search
  pattern used for "Needs manual review" — so you can track one down in one
  click instead of retyping the title. Needs `--fetch-references`.

**Suggestions are filtered to your questions.** Recommending whatever your
papers happen to cite most is how a reading list fills up with well-cited
work that has nothing to do with your thesis — a co-author's unrelated
output, methods papers, the field's ambient classics. Every cited-but-missing
work is scored against your research question and sub-questions, and only
the on-topic ones are suggested (in the mind-map, the ranked list, *and*
Part 2's Markdown report, so the two never recommend different reading
lists).

A missing reference is known only by its title, so the score asks "what
share of this title's meaningful words are words you actually ask about",
weighting each by how central it is across your question set — a word you
ask about in three of four questions counts for more than one that appears
once. That's what separates a real match from an incidental one: *Measuring
Sleepiness: The Stanford Scale* and *Urban Planning and Commute Times* both
match exactly one word in four against a set of sleep questions, but only
one of them is on topic.

Because a title-only match will sometimes misjudge something genuinely
relevant, filtering is a **split, not a drop** — whatever's held back stays
one click away under "Show the N held back as off-topic", so you can spot a
false negative. Tune the bar with `--min-gap-relevance` (0–1, default 0.1),
or pass `--min-gap-relevance 0` to suggest everything regardless of topic.
With no question or sub-questions configured there's nothing to score
against, so nothing is filtered.
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

### Themes across your library

Every other view on that page starts from questions **you** supplied:
relevance is scored against them, stances are classified against them,
coverage is counted against them. That makes them all blind in one specific
way — your library can be full of a topic you never thought to ask about,
and nothing built from your questions will ever show it.

The theme cloud is built from the papers' own words instead. Recurring
phrases are pulled from titles and abstracts and sized by how many
**different** papers use them — document frequency, not raw count, because a
phrase repeated fifteen times inside one paper is that paper's vocabulary
while one appearing once each in nine papers is a theme running through the
library. **Click any theme to list the papers it comes from**, each with a
direct link to open your local PDF, plus DOI / Google Scholar /
ScienceDirect.

The cloud is split in two, and the second half is the point:

- **Themes your questions reach**
- **In your library, but no paper using it speaks to any of your questions**

That second group is the blind spot made visible — a real cluster of work
you have collected that your sub-questions don't touch. Either it belongs in
your questions, or those papers don't belong in your library.

Some details that make it read as themes rather than word soup:

- Phrases never span a stopword or a sentence break, so "impact of AI on
  travel planning" yields *AI* and *travel planning*, never the phantom
  "AI travel".
- Short acronyms survive the minimum word length — *AI*, *ML*, *UX*, *OTA*
  are usually the terms you'd look for first, and a flat length floor drops
  exactly those.
- Terms display as the papers write them: *generative AI*, *ChatGPT*, not
  *generative ai*.
- A bare word is dropped when a phrase already says it (*generative* beside
  *generative AI* is one theme shown twice) unless it's genuinely used
  beyond that phrase.
- Title scaffolding is filtered out — "a systematic review exploring
  perspectives on X" names no subject, so none of those words is a theme.

Size carries reach and the count is printed on every chip, so magnitude is
never size-alone; colour is left free for selection state rather than
repeating what size already says. Chips are real buttons — tab to them,
Enter to select, Escape to clear — and with scripting off every theme's
papers are listed rather than leaving a cloud that does nothing when
clicked.

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

**Papers that don't match your questions are ignored.** Each paper is scored
against your research question *and* every sub-question, and kept if it
matches **any** of them — so a paper that speaks only to one sub-question
survives, which it didn't when scoring ran against the research question
alone ("School start times and academic outcomes" scores 0.00 against "Does
sleep deprivation affect adolescent decision-making?" and 0.67 against the
sub-question it was indexed for). Everything below `--min-relevance`
(default 0.1) is dropped before any drafting happens, and the draft's header
says how many were ignored. In the rare case that *nothing* matches, the
draft is written from everything rather than coming back empty — but says so
loudly, in the header as well as on stderr, because that draft may be a
review of the wrong literature.

Beyond that filter, a paper only appears in a paragraph if it's classified
as supporting, challenging, or giving mixed evidence on that specific
sub-question — one classified "unrelated" is never cited, and the reference
list only contains papers actually cited in the draft.

- Gathers the papers that support, challenge, or give mixed evidence on it
  (reusing Part 1/2's stance analysis) — when a sub-question has more
  candidate papers than fit in one drafting call, **both sides of the
  debate are kept**: papers are picked in relevance-to-this-sub-question
  order, alternating across supports/challenges/mixed, so a handful of
  challenging papers is never crowded out by a larger pile of supporting
  ones.
- **With Claude** (default — uses `claude-sonnet-5`; override with
  `--llm-model claude-opus-5` if a particular draft is worth the extra cost):
  writes a **section scaled to the evidence behind that question** — roughly
  a paragraph's worth of prose per source, so a well-supported question earns
  1,000–2,000 words and a thinly supported one gets a short section instead
  of the same length padded out. Limited sources, limited summary.
  `--words-per-question` forces a fixed length on every section instead.
  Sections follow standard
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

**Condensed, and paraphrased rather than quoted.** The point of a review
section is to show the sources were read and understood, which is
demonstrated by compressing them accurately, not by reproducing their
sentences. Each paper is reduced to its core question and its essential
finding — what it set out to establish, what it shows, what that means here —
and a source that took thirty pages may take a clause. Every sentence has to
carry a finding or a link between findings; coming in under the target
because the material is thin is correct, padding to reach it is not.

Direct quotation is **off by default** for the same reason (a real submitted
dissertation this was calibrated against quotes 27 words in ~2,900 — under
1%). Pass `--allow-quotes` to permit a sparing quotation where exact wording
genuinely carries something a paraphrase cannot; the verbatim-only rules
still apply then, so a quotation is never invented.

**You get both a Markdown file and an HTML page.** The `.md` is the one to
edit; the `.html` beside it is the one to read — a sticky contents list, a
measured line length, and print styling, which matters once a draft runs to
several thousand words. `--html-output` moves it, `--no-html` skips it.

**A failed section never masquerades as a written one.** If a request to
Claude fails, that section falls back to a bullet outline of its sources —
but the section says so, quoting the actual error, and the draft header
reports the run as partially failed rather than claiming "Claude-written
prose". The fallback outline now quotes each paper's most on-question
passage rather than its first 220 characters, which on a locally indexed PDF
is the title page and author affiliations.

**The prompt is budgeted so the call survives.** Each paper's full extracted
text goes in, untrimmed, whenever the batch fits; when it would not, the
budget is shared out — short papers donate what they do not use, no paper is
ever dropped entirely — and the section says how many sources were trimmed.
Long sections are streamed, so a slow generation cannot time out.

**Classification isn't paid for twice.** Working out each paper's stance on
each sub-question is the same job `visualize-library` already does, so Part
3 reads and writes the same cache file (`stance_cache.json` next to your
library index) and reuses anything still valid instead of re-running it. It
also uses the cheap extraction tier (`claude-haiku-4-5`) for that
classification rather than the drafting model — an explicit `--llm-model`
still applies to both, and switching models correctly invalidates the cache
rather than handing back what a cheaper model said earlier. Pass
`--no-stance-cache` to force a fresh classification.

**The drafting prompts are cached, the small ones deliberately aren't.** A
section's prompt carries whole papers — tens of thousands of tokens — so
those calls ask Claude to cache the prompt. Re-run the draft within five
minutes (tuning `--words-per-question`, fixing a sub-question, adding one
paper) and the unchanged papers are read back at a tenth of the input price
instead of being charged in full. Two details make that actually work rather
than just look like it does:

- The per-section bits — the sub-question and the target word count — are
  sent *after* the cache breakpoint, so changing the target length doesn't
  invalidate the papers sitting in front of it. Caching is a prefix match,
  and anything that varies inside the prefix quietly turns every read into a
  fresh write.
- The small calls (introduction, conclusion) and the per-paper
  classification calls are **not** cached, on purpose. The minimum cacheable
  prefix is 1,024 tokens on Sonnet and 4,096 on Haiku; below that a cache
  request stores nothing at all, silently, while still costing 1.25x to
  attempt. Repeat runs of the per-paper work are covered by the on-disk
  stance cache above, which costs nothing.

Every run prints what it actually spent (`Drafting used 12,400 input, 3,100
output, 0 cache-write, 88,000 cache-read tokens`) — cache reads are the
number worth watching, since a cache that only ever writes is overhead paid
for nothing. Pass `--no-prompt-cache` for a genuinely one-shot run.
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
characters. **With `--allow-quotes`, quoting is grounded in real text, not just abstracts.** For
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

### What the review is written to be marked on

The drafting prompts follow a taught postgraduate dissertation brief rather
than a generic "summarise these papers" instruction. The literature review
and discussion sections carry **30% of the marks each**, and what they are
marked on is critical understanding, not coverage. Specifically:

| Requirement | How the tool enforces it |
|---|---|
| A review is *"defined by a guiding concept … not a descriptive list of the material available, or a set of summaries"* | The introduction must state the guiding concept and signpost how the review is organised; sections must group by claim, never run one paper after another |
| *"Critically appraise strengths and weaknesses"* — Describe → Interpret → **Evaluate** → Synthesise | Sections must say what a claim rests on: design, sample, setting, period, whether a conclusion outruns its evidence, whose assumption is doing the work, where a finding has dated — and name genuine strengths as readily as faults |
| *"Contradictory findings — do not simply note differences; you need to explain them"* | Disagreements must be **accounted for** (different population, method, measure, setting, period), not just reported, before any judgement on which side is stronger |
| Expected content includes *"definitions and discussion of terminology"* and theoretical underpinnings, **in summary** at MA/MSc level | Sections must surface where sources define a key term differently or argue from different frameworks — and keep it to a summary, not an exposition |
| *"So what? — draw out implications of your discussions"* | Every section closes on what the evidence means for the student's own study: what is settled, what is open, what that implies for design and scope |
| *"Signalling a gap … and using this to justify your own"* | The conclusion reiterates the key arguments, states where knowledge stands, then uses the gap as the warrant for the student's contribution |
| *"Adequate signposting"* for reader processing | The introduction names the sub-questions in order; each section opens by framing what is at stake and how its evidence is organised |

The **Excel workbook** Part 2 produces carries the three working documents
the same material recommends keeping while you review:

1. **Literature Review Matrix** — the synthesis matrix itself: one row per
   paper, columns to compare across them.
2. **Criticality** — the critical-question chart, verbatim: thirteen
   questions down the side, one column per paper (the fifteen most relevant,
   because eighty columns is not a working document). Four rows are filled
   in because the toolkit can answer them honestly — relevance to your
   question, how old the work is, the themes it contributes to, and **who
   agrees or disagrees with it**, naming the other papers on each side.
   That last one is the question the tool answers better than memory can: it
   has already classified every paper against every sub-question. The other
   nine are blank on purpose. A blank cell is the question being put to you,
   which is the whole point of the exercise — pre-filling "is there bias?"
   with a guess would replace judgement with the appearance of it.
3. **Reading log** — title, author/date, and a starting summary are filled
   in, plus how each paper relates to what others say. *Text (exact)*,
   *What it means to me* and *Argument link* are headed "(yours to write)"
   and left empty. A log with the reflection already written is not a
   reading log.

The marking criteria above apply to `--output-type review` only — the
summaries answer a different question for a different reader, and there are
tests asserting they do not inherit criteria written for a dissertation
chapter. **Critical appraisal is the one thing they do share**, because a
summary that reports findings without their weight throws away the part of
the review that was hardest to write. The detailed summary gains a **How
good is the evidence** paragraph per sub-question (design, sample, setting,
period, where a conclusion outruns what is behind it, where a study's own
limitations qualify it) and must explain divergence rather than record it.
In the executive summary the `[Evidence]` / `[Contested]` / `[Gap]` tag is
now explicitly a judgement about how much weight a finding will bear, not a
count of how many papers mention it — a single well-designed study can
outweigh three that assume what they set out to show.

### The other outputs: an executive summary, or a detailed one

`--output-type` picks which single document a run produces — one, never
several:

| `--output-type` | What you get | Length |
|---|---|---|
| `review` (default) | The full draft, one section per sub-question — what you'd build a chapter from | 250–2,000 words *per question* |
| `summary` | Executive summary: answer first, themed across the questions, compressed to what a reader needs to know | 400–2,500 words |
| `detailed` | Everything interesting the sources say, question by question, with the specifics behind each finding | 800–8,000 words |

Under the hood all three run the same pipeline: the sections are drafted
first, and the summaries are written *from those sections*. So a summary can
never claim something the review would not have said, and all three cite
with the same in-text markers. For `summary` and `detailed` the sections
simply are not written out.

**Neither summary repeats itself.** The same sources reach several
sub-questions, and restating them under each is what turns a detailed
summary into a merely long one — so each source's contribution is stated
once, in full, under the question it bears on most directly; where it also
bears on a later one, only what is *additional* is written there. Sections
never open by restating their own heading, findings are never restated as
their own implications, and neither document has a closing recap — the
reader has just read it.

#### `--output-type summary`

For someone who will not read a full review: a supervisor, a panel, or you
deciding where the contribution is. It follows the structure consulting
practice uses for an executive summary, adapted to literature rather than to
a business case:

- **The short version** — Situation, Complication, Question, Answer, in four
  sentences. The Answer is the headline: a reader who stops there still
  knows what the literature concludes.
- **What the evidence shows** — findings that cut *across* the sub-questions
  rather than restating each section in turn. Each is a headline assertion
  used as its own heading, so reading only the headings gives the whole
  argument, and each is tagged **[Evidence]** (sources agree and none
  contradicts), **[Contested]** (sources disagree) or **[Gap]** (pointed
  toward but not tested). The consulting version of this tag is Evidence /
  Assumption / Gap; in a review the interesting middle case is not an
  untested assumption but a genuine disagreement between published studies.
  **Every finding ends with a "So:" sentence** naming what the student
  should now do differently — a design choice, a scope decision, a claim
  they can now make or must stop making. A finding without one is not
  finished.
- **Where the literature disagrees** — the debate stated as a debate: who
  claims what, and what would settle it. If nothing in your sources conflicts
  anywhere, it says so and treats that as a finding — an evidence base with
  no disagreement in it is either immature or narrowly selected.
- **Worth calling out** — what a careful reader would want flagged and would
  otherwise miss: a result cutting against the set, a claim resting on one
  source, evidence concentrated in one country or period, a term defined
  inconsistently between papers, a finding that has aged badly.
- **What this means for the thesis** — concrete next actions, highest value
  first, each naming what it would establish and which finding it came from.
  Anything that would read the same way for a different thesis in a
  different field is rejected by the prompt.

**It is proportional to the evidence, in both directions.** Length scales
with the sources actually cited (400–2,500 words), and so does *how much is
said*: four sources buy two to three findings, sixty buy five to seven.
Length alone is not proportionality — a long summary that still makes three
points has padded three points — so the number of findings and callouts is
scaled and stated in the request, not left to the model.

#### `--output-type detailed`

The other half of that coin. Where the executive summary asks *what do I
need to know*, this one asks *what is actually in this literature* — and
answers it question by question, keeping the specifics that make a finding
usable rather than only the conclusion drawn from it: what was studied, on
whom and where, by what method, in which direction and how strongly, and
when. Evaluative words carry no information on their own, so the prompt
rejects "significant" / "important" / "robust" standing alone in place of
the actual result.

- **What this evidence base looks like** — three or four sentences on the
  *shape* of the evidence: how much there is, where it clusters (period,
  setting, population, method), where it is thin. Deliberately no findings
  here; those belong to the questions.
- **One section per sub-question**, numbered, opening directly with what the
  sources establish. Then — only where there is something real to say —
  **Where they diverge**, **Notable**, and **Not covered**. Any that would be
  empty is omitted: a heading followed by "none" is noise, and a question
  with nothing behind it costs one honest sentence rather than a paragraph
  explaining that it has nothing behind it.
- **Across the questions** — strictly limited to what no single question
  could carry: a method or population common to all of them, a definition
  that shifts between them, a source that answers one question well and
  another badly. Anything already said above is ineligible.
- **Where this leaves the thesis** — the same actionable close, each step
  naming what it would establish and which section it came from.

`--summary-words` forces a length on either summary; `-o` moves the file.

**Length caps do not fight the evidence.** At 200 words per source, 34
sources want about 6,800 words; a cap of 4,000 asked for a document the
evidence did not fit into, and the model wrote past the ask rather than
dropping the detail — until the API cut it off with its closing section
unwritten. The detailed cap is 8,000, and the request budget is now computed
in *tokens* (a word costs a bit over one) with 2.5× headroom, because a word
count is a target rather than a limit. Headroom is free: output is billed on
what comes back, not on what was allowed.

**A summary that stops early is caught, retried, and labelled.** A model
that ends its turn halfway through does not announce it: the reply arrives
with a normal stop reason and reads like the opening of the right document.
One run of `--output-type detailed` produced its opening paragraph, a bare
`## 1.` heading, and nothing else — and that file was written out as though
it were finished. So the returned document is now checked against what was
asked for (a section per sub-question, the closing section, and no ending on
a heading with nothing under it). If it falls short it is retried once — the
prompt prefix is cached, so the second attempt re-reads it at a tenth of the
input price — and if it still falls short, the file says so in its header,
naming what is missing. Running out of room and choosing to stop are
reported separately, and handled differently: a truncation is retried with a
wider budget, since retrying it on the same one truncates again in the same
place, while a model that simply stopped gets the same budget back, because
nothing was wrong with it.

If the request to Claude fails outright, what gets written is a labelled
skeleton.
And if a section underneath it failed to draft, either summary says so in
its header: the review flags that on the section itself, but a standalone
summary has no section to flag it on, which would make it the one place a
reader could never learn that the evidence beneath is thinner than it looks.

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

### Living views vs. kept outputs

Two kinds of file, two different rules.

**Documents are always kept.** Everything `literature-review` produces — the
review, the executive summary, the detailed summary, and the HTML beside
each — plus Part 1's report. These are things you made at a moment in time,
and you'll want today's against last week's. They are kept **wherever you
write them**: in `output/`, or anywhere else you point `-o`.

Most already carry a timestamp in the filename and pile up on their own:

```
output/
  literature-review-20260824-165223.md
  literature-review-20260825-080928.md
  executive-summary-20260825-080928.md
  detailed-summary-20260825-081402.md
```

The case that needs help is reusing one explicit `-o path` across runs, since
that names a single fixed file. There the existing file moves into a
`previous/` folder beside it, stamped with **its own** modification time
(when it was produced, not when it was displaced), so the folder reads as a
history of runs. The path you named keeps pointing at the newest.

**Living views are overwritten** — `library/visualization.html`,
`library/literature_matrix.xlsx`, `library/library.md`. These describe your
library *as it stands right now*, so re-running after adding papers is meant
to replace them: an old snapshot of a library you've since changed isn't
history, it's a stale picture of something that no longer exists. Their
fixed names are what your bookmark, your open tab and the page's own
download link all point at.

**...unless you put one in `output/`.** Which rule applies is decided by
where the file lands, not by which command wrote it. Point the visualization
at `output/visualization.html` and every version is kept, exactly as it
would be for any other file there. "Anything in `output/` is kept" is a rule
you can predict from a path; "the review is kept and the visualization
isn't" is one you'd have to remember per command, and it breaks the moment
you point one command at the other's folder.

Neither rule applies to state and caches — `index.json`, the stance cache,
the extracted `.txt` files, downloaded PDFs. Those are meant to be rewritten
in place, and versioning every one would bury the real history in noise. If
filing an old copy away ever fails (a read-only folder, say), the run says
so and still writes the new output: losing this run's work because last
run's couldn't be archived would be the worse outcome.

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
  outputs.py          Documents are kept wherever written; library views are overwritten in
                      place unless they land in output/, where the destination's rule wins
  review_html.py      Renders Part 3's draft as a self-contained HTML page
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
    themes.py            Recurring phrases across the library, by document frequency — the one view
                         built from the papers' own words rather than from your questions
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
