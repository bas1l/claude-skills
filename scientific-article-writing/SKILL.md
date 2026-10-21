---
name: scientific-article-writing
description: "How Basil and Claude co-write a scientific journal article, in linked section pairs drafted and loaded together: figures first (claim check, gallery of house-style prototypes, ranked proposals, variants, export, staging); then Results with Materials and Methods (Results as verified standalone docx drafts, the Word review and trim loop with tracked changes, Methods cut to the kept Results); then Discussion with the state of the art; then Introduction with Conclusion, fitted to what was kept; then the Abstract last, alone. Takes an optional section argument (figures, results, methods, discussion, introduction, state-of-the-art, conclusion, abstract) and loads only that section's guidance, its pair's guidance and the global rules. Use whenever work touches a manuscript, article or paper: writing, drafting, revising, trimming or restructuring a Results, Methods, Discussion, Introduction, related-work, Conclusion or Abstract section (restructure the methods to follow the Results); generating, choosing or redrawing a paper figure; writing or shortening captions; building a figure gallery or prototype set; reviewing a reviewed or trimmed .docx edited in Word; adding context or corrections to kept text; staging figures into figures_selection; checking terms across figure, caption and text. Applies in the population-synthetic repo, the 40_llm-population-fidelity-benchmark manuscript folder and any future article, even when 'skill' or 'article' is not said."
---

# Scientific article writing

The way Basil (researcher, sole author voice) and Claude produce a journal article together.
This file is a router: it fixes the order, then sends you to the global rules and to the
section pair the task needs.

## Order (fixed): linked pairs

Sections come in linked pairs, drafted together and loaded together.

1. **Figures.** Their own first step, but part of the Results and Methods stage: the Results are
   written from the figures.
2. **Results + Materials and Methods.** Results for one analysis block, as a standalone docx; he
   trims and reviews it in Word. Materials and Methods is then generated to cover exactly what
   the kept Results report.
3. **Discussion + state of the art.** The Discussion interprets the kept Results; its comparison
   with prior work takes up the strands the state of the art positions
   (`references/sections/state-of-the-art.md` section 2).
4. **Introduction + Conclusion**, drafted after the Discussion, or revised then if an earlier
   draft exists, so that the gap, the questions and the take-home message match the kept Results;
   the Conclusion answers the aim and questions the Introduction states
   (`references/sections/conclusion.md` section 2).
5. **Abstract**, alone, written last, once every section is kept, because it summarises them; any
   earlier abstract text is revised then.

Each stage is written from what the author kept after his trim of the stage before, so drafting
ahead of his trim wastes his time and bloats the paper.

## Hard rule before any file is read

**Permission.** Never edit files he owns (rule files, skeleton, reviewed docx, repo code, either
`CLAUDE.md`) without an explicit request. Never write Claude into any artefact: no attribution
lines, no "Claude" as a tracked-change author.

## What to read

1. **Always** read `references/global.md` (working style, claim strength, terminology, citations,
   house style, docx build, notes and hand-over, the review and trim loop).
2. **Then read the targeted section's file and its pair's file** from the table, and no other
   section file. If no section is named, infer it from the request. Load a second pair only when
   the task genuinely spans two stages (for example Methods and Discussion fitted to his trimmed
   Results).
3. **Then the project profile** (Step 0 below) when working on that project.

| Section argument or intent | File | Pair (load too) |
|---|---|---|
| `figures`: any figure (even a scratch one), gallery, prototype, variant, export, caption, staging, term table | `references/sections/figures.md` | none; `references/sections/results.md` only if the task also touches text |
| `results`: drafting a Results block, or a correctness pass on his kept Results | `references/sections/results.md` | `references/sections/methods.md` |
| `methods`: Materials and Methods, cutting it to the kept Results, reordering it to follow the Results | `references/sections/methods.md` | `references/sections/results.md` |
| `discussion`: interpreting the kept Results, limitations, comparison with literature, venue fit | `references/sections/discussion.md` | `references/sections/state-of-the-art.md` |
| `state-of-the-art` (also related work, background, literature review): positioning against prior work, placement, search, "first" claims | `references/sections/state-of-the-art.md` | `references/sections/discussion.md` |
| `introduction`: the gap, the question, the contributions, opening moves, length | `references/sections/introduction.md` | `references/sections/conclusion.md` |
| `conclusion`: the take-home message, spin check, how the Discussion ends without a Conclusions section | `references/sections/conclusion.md` | `references/sections/introduction.md` |
| `abstract`: the standalone summary, its structure and moves, main numbers, venue word limits, keywords and discoverability | `references/sections/abstract.md` | none |
| `review` or `trim` with no section named: a reviewed or trimmed docx, corrections, criticism | `references/global.md` section 9 only, plus the file of the section the docx holds | that section's pair |

## Step 0: load the project profile

Generic rules live in `references/`. Everything specific to one article (paths, rule files,
toolkit, env, terminology owners) lives in `projects/<article>.md`. Identify the article from the
working directory or the files named, then read its profile:

| Article | Profile |
|---|---|
| LLM demographic-fidelity benchmark (repo `population-synthetic`, manuscript `40_llm-population-fidelity-benchmark`) | `projects/llm-population-fidelity-benchmark.md` |

The profile names the manuscript folder's own `CLAUDE.md` and rule files. **Those win over this
skill** wherever they are more specific. If no profile matches, see "Adding a new article" below.

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

Keep generic lessons in `references/` (section-agnostic ones in `global.md`, section ones in
`sections/`); only paths and article-specific decisions go in the profile.
