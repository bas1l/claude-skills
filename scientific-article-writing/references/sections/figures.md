# Figures and captions: from claim to staged figure

The paradigm for taking one result from a claim to a staged figure. Figure labels and quoted
wording below are illustrative. Project paths (presentation layer, width, staged folder) are in
the project profile.

**Figures only through the repository presentation layer**, even scratch ones: house order,
width, palette, labels, no transparency, ids never on the canvas.

## The pipeline in one view

For each result: generate many candidate figures; Basil keeps one or a few; further rounds run
only on the kept ones, until Basil says in so many words that a figure is done. Never draw one
figure and polish it, and never narrow the set on Basil's behalf.

Round sizes from one past article, counted from the gallery folders (rounds in order):

| Result | First gallery | Later rounds | Drawn | Kept |
|---|---|---|---|---|
| Data figure A | 14 | 2, 2, 1, 1 | 20 | P17, then P20 |
| Data figure B | 19 | none | 19 | P19 |
| Data figure C | 20 | 8, 6 | 34 | P03b |
| Data figure D | 14 | 5, 3, 1, 5, 3 | 31 | P23b, then Basil's own SVG edit |
| Diagram A | 8 | 3, 6, 2, 1, 1, 1, 1, 7, 1 | 31 | P30 |
| Diagram B | 10 | 3, 2, 1, 1 | 17 | P16 |
| Diagram C | 8 | 2, 1, 2, 4 | 17 | current figure, then P14 |

Rounds shrink as a figure converges but need not shrink steadily: Diagram A went wide again for
one panel at round 9 (7 versions) after several single-figure rounds.

## 1. Establish the claim before plotting

- Start from the analysis question, not from a chart type. Write down, in one or two sentences
  each, the messages the figure must carry (for example "only the highest dose moves toward the
  control", "no dose reaches the control").
- A background stats agent checks each message in the data and says whether it is supported,
  descriptive only, or unsupported. Drop claims that need a test the design cannot give (for
  example a selection-adjusted test after picking the extreme cell, or any post-hoc contrast
  chosen by looking at the figure). A figure may show a pattern the text does not claim.
- Where a real reference exists, every message is read against it (reference drawn
  in each cell or as a detached column), and the reference is framed as what was checked, never
  as possibly defective.
- Audit an existing figure against the recorded figure standard before redrawing it (orientation,
  width, label tint, order). List compliant and non-compliant points.
- Identify an existing figure by the image embedded in the current manuscript docx and by its
  builder, not by a file name in the staged folder. One redraw started from a
  superseded hand-drawn SVG ("you are targeting the wrong figure").
- A gallery does not replace the claim. After 34 figures of one result Basil stopped the drawing: "I
  think we need to discuss what is important and valuable to show here, so that
  it drives us regarding what the figure needs to highlight rather than plotting everything".
  When a gallery produces no pick, or Basil asks what the figure should highlight,
  settle the messages before drawing again.
- Settle the data decisions a figure depends on first: "build the design gallery only
  after the data labelling".

## 2. Divergent step: many prototypes

- Brief a background agent (web access allowed for precedents) to draw many distinct encodings,
  about 14, ids `P01`...`P14`. Distinct means different encodings (glyph grid, heatmap of one
  statistic, intervals, diverging bars, ternary, small multiples), not colour variants.
  Real first galleries: 14 to 20 for data figures, 8 to 10 for diagrams. The size comes from
  Basil's request on 2026-09-21, after first rounds of 3 and 6: "Generate many proposals so I can
  review them".
- Include the current figure, if there is one, as `P00`, pinned for comparison. Several figures
  can run at once, one agent and one gallery each (three on one day).
- Build the gallery in a durable folder that the project allows, beside but outside the published
  and staged figures (for example `<figures folder>\figureN_gallery_<date>\`).
  Nothing goes into the manuscript or staged folders before a choice.
- Put the house constraints in the agent prompt explicitly, since subagents do not inherit them:
  - draw only through the repository presentation layer (style, palette, labels, grids,
    glyph grid, the single `save_figure` with fixed canvas); no ad-hoc matplotlib styling;
  - exact journal width (from the project profile), a stated target height;
  - standard factor order read from code or config, never a hardcoded list;
  - compared items as columns, conditions as rows simplest-first, reference in a detached column;
  - withdrawn or excluded cells crossed out, never dropped, so column positions stay fixed;
  - display labels only (no ids, no underscores, no internal prefixes); no transparency;
  - PNG only at prototype stage (delete the SVG and EPS the writer also produces).
- Structure the code so any prototype can be rerun alone: a `common.py`/`data.py` that loads and
  caches the data and **asserts** the key messages and denominators (for example pooled counts
  equal the published summary), then `protos_*.py` with one function per prototype taking ids
  as arguments.
- The agent looks at each PNG itself, fixes overlaps and verifies width (SVG `width="<N>pt"`, or
  PNG pixels / 300 dpi x 72).

## 3. Comparison medium

- `index.html` in the gallery folder: a local contact sheet with every prototype and its note.
  Since 2026-10-20 ("come up with similar html page which compares the different options. Be
  creative") it can be an interactive offline page: the current figure pinned beside the selected
  option, a greyscale switch, real print size, newest variants first. Every candidate stays on the
  page, whatever its rank.
- `proposals.md` beside it, per prototype: rank, id, height, encoding and unit, what it keeps,
  what it loses, readability of sparse levels, greyscale survival, precedent, fit with house
  rules; then a ranked recommendation, and a "key messages checked in the data" section at the
  top with the numbers.
- Open the top candidates yourself and add a critical read (for example "W1 assumes equal
  intervals, which conflicts with the paper's ordinal statistics"). Flag cross-cutting problems
  that affect every prototype (a label tint colliding with a data hue, levels that merge in
  greyscale).
- Precedents cited from memory rather than from the paper are marked as unchecked.
- The ranking is advice, not a filter. In one gallery the agent ranked P01 first; Basil
  worked from ranks #4 and #14, the last-ranked design.

## 4. Convergent step: follow-up variants

- He answers by gallery rank ("#4 and #14"). Confirm which object a number refers to when a rank
  and a file id could both match; draw both if cheap.
- Basil also picks by file id ("P17 is the choice"), by file name, by a label on the page, by part
  of a design ("I like the P12 right part (by condition)"), by joining designs ("take "new 2 P12"
  but replace 4.1 with "new 1 P11""), or by going back ("take back P03B"). Later rounds run only
  on what was kept; the other prototypes stay available in case Basil returns to one.
- One message from Basil is one round: a new id, the same agent, and within minutes the absolute
  path of the new PNG with what changed and what it cost in height or legibility. One figure went
  from gallery to approval in 39 minutes, another in 77.
- A question is part of choosing. "Why a triangle", "what are the pros and cons of P23b?" and "Is
  the plot showing quantity that are calculated as follows" get an answer, not a drawing. When
  Basil sees something odd in a prototype ("I see something that I thought wouldn't appear",
  2026-09-22), trace it in the data and answer before drawing more. Basil reads prototypes as a
  data check as well as a design choice.
- Show, do not describe. "I need to see to decide" (2026-10-20): colour or layout options are drawn
  as whole figures, not tabled or cropped ("build the full panel instead of just one part").
- Go wide again when asked, ordered along the range requested: "come up with several tests and
  variations, from similar to the current figure to different".
- Draw what was asked, literally. Asked for probabilities that sum to 1, an agent added a row to
  keep the real values: "do not add one row" (2026-10-20). Put an objection beside the requested
  version, not in its place.
- A file Basil edited by hand is the specification: compare it with the last version, then make
  the builder reproduce it and measure the match ("I have revised this panel ... Analyse it to
  understand what I meant compared to what you did", then "reproduce this layout exactly").
  An odd layout may be deliberate (boxes placed out of their expected order in one diagram saved
  height), so report it rather than fix it.
- Figures must read as one set. Panels sharing a meaning share colours and box style ("the color
  code of this panel is meant to match the one of the earlier diagram"), a change to one is proposed for its
  sibling, and colours are inventoried across the article's figures before new ones are offered.
  Colours must stay distinct and colourblind safe (Basil's correction of 2026-10-05). A header
  that differs for no reason "draws attention for nothing" (2026-10-20).
- When the data or a denominator changes mid-gallery, redraw every design on the new basis so the
  comparison stays fair ("divide by completed records only": all 22 designs). This is
  the one case where ids keep their names and files are redrawn; report it.
- Check a diagram against the code with a fresh agent that has not seen the gallery notes before
  publishing it, and take what it flags to Basil.
- Each request becomes a new id: `P15`, `P16`... for new designs, `P03a`, `P03b`... for variants
  of one parent (for example "by group", "by condition", "both", "one diagram instead of two").
  Earlier files are never overwritten; each variant is appended to `index.html` and to an
  addendum table in `proposals.md` with its outcome.
- Resume the same drawing agent for each round so it keeps its context.

**What ends the iteration.** Only explicit words from Basil about a named version: "P20 is what we
need", "F1_P16_p15_bracket.png is good.", "F3_P30_p24_elbow_arrows.png is good to go", "publish
... with P14". "almost", "is better" and "is good with some slight changes" open another round. A
gallery can also end with no redesign: "current figure is good as is." (the gallery stays as
reference).

**Replace or add.** A design chosen for a figure that already exists joins it as a new panel unless
Basil says otherwise: "this figure must have both the previous panel (A) AND this new subfigure
(B) like we did with the earlier figure".

**Approved is not frozen.** Figures reopen after a data re-run, a change in the text, or a later
look (the same morning, or the next day). These are usually direct edits of
the published figure with no new gallery, and the same stopping rule applies ("this new figure is
good. Branch this one in", 2026-10-21).

## 5. Final export

- Re-render the approved prototype in PNG + SVG + EPS through the house writer. Check the PNG is
  identical to the approved one and the width is exact.
- Move the previous version to `_prev\`, save the builder and a notes file beside the published
  figure, and index them so nobody has to search old sessions: "link this figure and its code so
  it is accessible without having to reach previous discussion" (2026-10-21).
- Swap the image into a docx only when Basil says so and in the file Basil names ("I'll tell you
  when to do that", then "which is the target file", 2026-10-21).
- Write a **term table** (`term_table.txt` in the final folder): for each word printed on the
  figure or used in its caption, the article's term, the source with file:line (terminology
  rules, methods text, figure-terms config), and a status (resolved, taken from the instrument,
  open). It is the record of the naming rule in `references/global.md` section 3: rank or
  level names read the same in figure, caption and Methods.
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
- Warn every time that session scratchpads under `%USERPROFILE%\AppData\Local\Temp\claude\...`
  are volatile (Disk Cleanup, Storage Sense) and recommend copying chosen figures and their final
  folders somewhere durable. This has happened: gallery pages from earlier rounds
  were gone from their indexed paths within about six weeks.
- Rejected prototypes are never deleted. They stay in the gallery, and the index records what was
  chosen.
