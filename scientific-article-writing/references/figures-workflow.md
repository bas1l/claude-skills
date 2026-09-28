# Figures workflow: from claim to staged figure

The paradigm that produced the typicality grid (P20), the severity worst-clash grid (P19) and
the clash-driver gallery. Project paths (presentation layer, width, staged folder) are in the
project profile.

## 1. Establish the claim before plotting

- Start from the analysis question, not from a chart type. Write down, in one or two sentences
  each, the messages the figure must carry (for example "only strategy E moves toward the
  reference", "no combination reaches the reference").
- A background stats agent checks each message in the data and says whether it is supported,
  descriptive only, or unsupported. Drop claims that need a test the design cannot give (for
  example a selection-adjusted test after picking the extreme cell, or any post-hoc contrast
  chosen by looking at the figure). A figure may show a pattern the text does not claim.
- Where a real reference population exists, every message is read against it (reference drawn
  in each cell or as a detached column), and the reference is framed as what was checked, never
  as possibly defective.
- Audit an existing figure against the recorded figure standard before redrawing it (orientation,
  width, label tint, order). List compliant and non-compliant points.

## 2. Divergent step: many prototypes

- Brief a background agent (web access allowed for precedents) to draw many distinct encodings,
  about 14, ids `P01`...`P14`. Distinct means different encodings (glyph grid, heatmap of one
  statistic, intervals, diverging bars, ternary, small multiples), not colour variants.
- Put the house constraints in the agent prompt explicitly, since subagents do not inherit them:
  - draw only through the repository presentation layer (style, palette, labels, grids,
    glyph grid, the single `save_figure` with fixed canvas); no ad-hoc matplotlib styling;
  - exact journal width (456 pt for the benchmark), a stated target height;
  - standard factor order read from code or config, never a hardcoded list;
  - models as columns, strategies A to E as rows simplest-first, reference in a detached column;
  - withdrawn or excluded cells crossed out, never dropped, so column positions stay fixed;
  - display labels only (no ids, no underscores, no provider prefixes); no transparency;
  - PNG only at prototype stage (delete the SVG and EPS the writer also produces).
- Structure the code so any prototype can be rerun alone: a `common.py`/`data.py` that loads and
  caches the data and **asserts** the key messages and denominators (for example pooled counts
  equal the published summary), then `protos_*.py` with one function per prototype taking ids
  as arguments.
- The agent looks at each PNG itself, fixes overlaps and verifies width (SVG `width="456pt"`, or
  PNG pixels / 300 dpi x 72).

## 3. Comparison medium

- `index.html` in the gallery folder: a local contact sheet with every prototype and its note.
- `proposals.md` beside it, per prototype: rank, id, height, encoding and unit, what it keeps,
  what it loses, readability of sparse levels, greyscale survival, precedent, fit with house
  rules; then a ranked recommendation, and a "key messages checked in the data" section at the
  top with the numbers.
- Open the top candidates yourself and add a critical read (for example "W1 assumes equal
  intervals, which conflicts with the paper's ordinal statistics"). Flag cross-cutting problems
  that affect every prototype (a label tint colliding with a data hue, levels that merge in
  greyscale).
- Precedents cited from memory rather than from the paper are marked as unchecked.

## 4. Convergent step: follow-up variants

- He answers by gallery rank ("#4 and #14"). Confirm which object a number refers to when a rank
  and a file id could both match; draw both if cheap.
- Each request becomes a new id: `P15`, `P16`... for new designs, `P03a`, `P03b`... for variants
  of one parent (for example "by model", "by strategy", "both", "one diagram instead of two").
  Earlier files are never overwritten; each variant is appended to `index.html` and to an
  addendum table in `proposals.md` with its outcome.
- Resume the same drawing agent for each round so it keeps its context.

## 5. Final export

- Re-render the approved prototype in PNG + SVG + EPS through the house writer. Check the PNG is
  identical to the approved one and the width is exact.
- Write a **term table** (`term_table.txt` in the final folder): for each word printed on the
  figure or used in its caption, the article's term, the source with file:line (terminology
  rules, methods text, figure-terms config), and a status (resolved, taken from the instrument,
  open). Rank or level names must read the same in figure, caption and Methods.
- Adopting the figure into the code pipeline is a separate step through the repository's plan
  workflow (plan with the prototype and golden tables as reproduction checks). Not part of this
  skill; offer it.

## 6. Captions

- A caption says only what the artwork does not: the unit, the scale (for example square-root
  heights), the denominator, the meaning of printed numbers, what an empty cell means.
- Short declarative noun phrase first; no "This figure shows", no cross-references, no
  provenance, no drafting notes, no interpretation.
- Match the length of captions he has already accepted for this article; shorter is safer.
- Follow the project's caption rule file for layout and tokens.

## 7. Staging and indexing

- Copy the chosen files into the project's staged-figure folder with a caption file and an
  appended provenance entry (source, date, hashes). The staged set is the closed set of figures
  the paper may use.
- Keep the manuscript's gallery index (absolute path, date, session, what it covers, how many
  figures, what was chosen) current whenever a gallery is created or a choice is made.
- Warn every time that session scratchpads under `C:\Users\basil\AppData\Local\Temp\claude\...`
  are volatile (Disk Cleanup, Storage Sense) and recommend copying chosen figures and their final
  folders somewhere durable.
