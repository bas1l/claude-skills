---
name: scientific-article-writing
description: "How Basil and Claude co-write a scientific journal article: figures first (claim check, gallery of house-style prototypes, ranked proposals, variants, export, staging), then Results as verified standalone docx drafts, the Word review and trim loop with tracked changes, then Materials and Methods cut to the kept Results, then Discussion. Use whenever work touches a manuscript, article or paper: writing, drafting, revising, trimming or restructuring a Results, Methods or Discussion section (restructure the methods to follow the Results); generating, choosing or redrawing a paper figure; writing or shortening captions; building a figure gallery or prototype set; reviewing a reviewed or trimmed .docx edited in Word; adding context or corrections to kept text; staging figures into figures selection; checking terms across figure, caption and text. Applies in the population-synthetic repo, the 40_llm-population-fidelity-benchmark manuscript folder and any future article, even when 'skill' or 'article' is not said."
---

# Scientific article writing

The way Basil (researcher, sole author voice) and Claude produce a journal article together.
The order is fixed: **figures, then Results, then Materials and Methods, then Discussion**.
Each text section is sized by what the author kept of the previous one, so drafting ahead of his
trim wastes his time and bloats the paper.

Generic rules live here and in `references/`. Everything specific to one article (paths, rule
files, toolkit, env, terminology owners) lives in `projects/<article>.md`.

## Step 0: load the project profile

Identify the article from the working directory or the files named, then read its profile:

| Article | Profile |
|---|---|
| LLM demographic-fidelity benchmark (repo `population-synthetic`, manuscript `40_llm-population-fidelity-benchmark`) | `projects/llm-population-fidelity-benchmark.md` |

The profile names the manuscript folder's own `CLAUDE.md` and rule files. **Those win over this
skill** wherever they are more specific. If no profile matches, see "Adding a new article" below.

## Working style (applies to every phase)

- **Manager, not worker.** Push data extraction, statistics checks, prototype drawing, docx
  builds and verification to background subagents; keep only their conclusions. Resume the same
  figure agent (SendMessage) for follow-up variants so it keeps its context.
- **Plain, concrete language.** Lead with the answer; tie every term to a real file or number.
  Name things by their own name or the paper's own numbering (5.2, Figure 5a). Never coin
  shorthand codes (M1, "#A3") in documents or replies.
- **Options with trade-offs, in prose.** When several choices are viable, list them with the
  consequence of each and let him choose. When one reading is clearly likeliest, act on it and
  state the assumption.
- **Deliver, then ask.** Build the requested file in the same run, record every default under
  "Notes for the author", and put the questions next to the finished file.
- **Ping when done** with full absolute paths (file, build script, gallery page), never
  `scratchpad/...` or other relative forms.
- **Permission.** Never edit files he owns (rule files, skeleton, reviewed docx, repo code,
  either `CLAUDE.md`) without an explicit request. Never write Claude into any artefact:
  no attribution lines, no "Claude" as a tracked-change author.

## Phase A: figures (checklist)

Full procedure: `references/figures-workflow.md`.

1. **Claim before plot.** Brainstorm what the figure must show; a background stats agent checks
   which claims the data actually support. Drop post-hoc or unsupported claims. Read against the
   real reference population where one exists.
2. **Divergent gallery.** Background agents draw many distinct prototypes (around 14, ids P01,
   P02, ...) through the repository's presentation layer, at journal width, house model order,
   labels and palette, withdrawn cells kept visible. Key data messages are asserted in code first.
3. **Compare.** A local `index.html` contact sheet plus a ranked `proposals.md` (rank, what it
   shows, pros, cons, height). Add your own critical read of the top candidates.
4. **Converge.** He picks by gallery rank; follow-up variants get new ids (P15+, P03a, P09a ...),
   never overwriting earlier ones.
5. **Export.** Final PNG + SVG + EPS through the house writer; a term table (file:line) matching
   figure words to the article; level and rank names identical in figure, caption and Methods.
6. **Caption.** Short: only what the artwork cannot show (unit, scale, meaning of printed
   numbers). Match the length of captions he has already accepted.
7. **Stage and index.** Copy the chosen figure into the manuscript's staged-figure folder with a
   provenance entry; keep the manuscript's gallery index current; warn that session scratchpads
   under Temp are volatile.

## Phase B: text (checklist)

Full procedure: `references/text-drafting-loop.md`; review mode: `references/review-and-trim-rules.md`.

1. **Results first.** One standalone docx per analysis block, built with the project's docx
   toolkit. Every number asserted against its source file before saving; a banned-token check
   refuses to save. Results report observations and statistics (tests, CIs, effect sizes) only.
2. **He trims in Word** (`...reviewed.docx`, `...trimmed.docx`). Claude's review is tracked
   changes by author "Suggested edits", backup first, only the section asked, and only context
   or corrections to what he kept. Never re-insert cut content; flag dependencies in prose.
3. **Materials and Methods** next, cut to exactly what the kept Results need, and **ordered as
   the Results**: a short shared introduction (only what all outcomes share), then one block per
   Results outcome in Results order, each holding its definition, data scope and statistics; no
   interleaving of outcomes. A shared test is defined at first use and referenced afterwards;
   alpha and software once; equations renumbered in order of appearance.
4. **Discussion** last: interpretation at the strength the statistics support, limits,
   literature only from verified sources, no untested joint claims.
5. **Hand-over.** "Notes for the author (not for submission)" as a numbered list; new files get a
   suffix and never overwrite; outputs sit beside the figure's caption file. He pastes accepted
   text into the manuscript skeleton himself.

## Hard rules

- **Results describe, Discussion interprets.** No causes, "suggests", evaluative adjectives or
  literature in Results; Methods states what was compared, not why it reads as good or bad.
- **Every number traces to a file and key**, rounded once from the stored value. Numbers computed
  only in scratch are listed as new in the notes.
- **Every test reported is one that exists, is interpretable and is described in Methods**, and
  every Methods test has a Results sentence. Degenerate cases are stated without a p value.
- **Figures only through the repository presentation layer**, even scratch ones: house order,
  width, palette, labels, no transparency, ids never on the canvas.
- **A trim is a decision.** Review adds the minimum context a kept sentence needs; it never
  restores a cut.
- **Back up before any edit** to a file he has opened; edit in place at run level; never
  regenerate it; refuse to write while a Word `~$` lock file exists.
- **No em dashes, straight quotes only**, and the project's banned-word list, in every output.
- **His own text keeps his voice.** Flag corrections, never rewrite silently.

## Reference files

| File | Read when |
|---|---|
| `references/figures-workflow.md` | Any figure generation, gallery, variant, export, caption or staging work |
| `references/text-drafting-loop.md` | Drafting Results, Methods or Discussion, or building a docx |
| `references/review-and-trim-rules.md` | He hands back a reviewed or trimmed docx, or asks for corrections or criticism |
| `projects/llm-population-fidelity-benchmark.md` | Work on the LLM demographic-fidelity benchmark |

## Adding a new article

Create `projects/<article-slug>.md` with these sections, then add a row to the Step 0 table:

1. Identity: title, venue, where the manuscript folder and the code repository live.
2. Authorities: the manuscript folder's `CLAUDE.md` and rule files (tone, terminology, format,
   captions), in order of precedence. Reference them by path; do not copy their rules.
3. Figures: presentation layer, figure conventions doc, journal width, model or factor order
   source, staged-figure folder, provenance file, gallery index file.
4. Text: docx toolkit and example builder, drafting-strategy file, style template docx, style
   model article, skeleton document, captions folder, backup folder.
5. Environment: python interpreter, required env vars, data output roots.
6. Terminology owners and known open conflicts.

Keep generic lessons in `references/`; only paths and article-specific decisions go in the profile.
