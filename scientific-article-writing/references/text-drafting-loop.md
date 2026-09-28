# Text drafting loop: Results, then Methods, then Discussion

The project's drafting-strategy file (see profile) is the detailed procedure for one analysis
block and wins where it is more specific. This file records the order and the loop.

## 0. Order and why

1. Results for one analysis block, as a standalone docx.
2. He trims and reviews it in Word.
3. Materials and Methods, generated to cover exactly what the kept Results report.
4. Discussion, interpreting the kept Results.

Writing Methods before the trim produces text for results he later cuts, and then the Methods
must be cut again. Writing Discussion before the trim invites claims about results that no
longer appear.

## 1. Results draft

- **Gather in background agents**: format and tone (rule files, style template, his latest
  Word-side edits compared with the backup), and content (the analysis outputs, every parameter
  as actually run, every number with file and key).
- **Verify before writing**: reproduce the numbers into scratch; check staleness and silent
  exclusions; every test must exist, match the design, be interpretable (no degenerate fits, no
  p stored as 0, no uncorrected families); state the correction family.
- **Content rules**:
  - observations and statistics only: rates with their denominator, counts, intervals, test
    statistic, p, effect size;
  - no causes, no "suggests", no evaluative adjectives ("tidy", "defect", "realistic", "better"),
    no literature;
  - descriptive paragraph first for grids and rankings, then test paragraphs in the fixed
    sentence order of the project's style model;
  - counts rather than percentages when the denominator is 100;
  - describe the procedure as run; never mention mechanisms that did not apply.
- **Build** with the project docx toolkit: copy `_helpers.py` and the example builder into the
  output folder, adapt the copy, never run the toolkit in place.
- **Assert every number** in the builder: load the source CSV and JSON files at the top, check
  each printed value against them (`chk(cond, what)`), and fail before anything is written.
- **Banned-token check refusing to save**: a guard on every paragraph (em dash, curly quotes,
  ASCII "e-" notation, hyphen-minus before a digit) plus word lists per part (global: where, via,
  yield, beyond, linked to, AI vocabulary; body: method, underscores, figure ids, config ids,
  ground truth; Results only: evaluative words). After saving, read the file back and grep again;
  on a hit, delete the file and stop.
- **Never overwrite**: `assert not os.path.exists(OUT)`; a new pass gets a new suffix
  (`.draft`, `.trimmed`, `-02`).
- Place the docx beside the figure's caption file in the staged-figure captions folder, named
  `<figure stem>.<scope>-draft.docx` (scope: results, methods-results,
  methods-results-discussion).

## 2. Materials and Methods

- Generated after the trim, from the kept Results: every test in a kept Results sentence is
  defined (instrument, statistic with numbered equation, outcome, test, correction family,
  effect size, alpha, software with versions); nothing whose result was cut stays.
- One bridging sentence for anything a neighbouring Methods subsection already covers.
- A short plain explanation of why a technical baseline is needed, in his register (for example
  why a chance-level similarity is estimated from the reference itself).
- List what was cut from Methods, and why, in the notes.

### Methods follow the order of the Results (rule of 2026-09-22)

The logical writing of a Methods section follows the ordering of the Results section.

- **Shared introduction first**, short, holding only what is common to all outcomes: the
  outcomes named in the order the Results report them, the design and factors, the units.
  Nothing that belongs to one outcome alone goes in it.
- **Then one Methods block per Results outcome or subsection, in the same order.** Each block
  keeps together that outcome's definition, its data scope (which individuals, which
  combinations, which denominator) and its own statistics (test, correction family, effect size).
- **No interleaving.** Two outcomes never share a paragraph or alternate between definitions and
  tests. Failure case: operational performance Methods 4.4.3 mixed the cost and retention
  definitions and tests; he asked for introduction + retention block + cost block, matching
  Results 5.4.
- **A procedure shared by several blocks** is defined in full at its first use and referenced
  afterwards ("as for the retention rate"), not repeated.
- **Significance level and software sentence once**, not per block.
- **Equations numbered in order of appearance** after any reordering; check every in-text
  equation reference against the new numbers and list renumberings in the notes.

When restructuring an existing Methods to this order, move his sentences verbatim; split only a
sentence that mixes two outcomes, and keep its words. Delivery follows
`review-and-trim-rules.md` section 6.

## 3. Discussion

- Interpretation at the strength the statistics support: a significant difference may be called
  a difference; a descriptive pattern is described as such; a non-significant result is not
  evidence of equality.
- **No untested joint claims.** Two separate findings do not make a "trade-off", a mechanism or a
  dominance claim unless a test addressed the joint statement. (The clash draft's "trade-off"
  framing was dropped for this reason and became a banned body word.)
- Limits of the design stated plainly (judge self-consistency is not validity, sample size,
  single run).
- Literature only from verified sources. Each citation is marked checked against the source or
  snippet-only; snippet-only references are listed in the notes to verify before submission.
- Links to other sections are flagged in the notes when a sentence rests on results reported
  elsewhere.

## 4. Notes for the author

- Heading "Notes for the author (not for submission)" after the body, numbered items, one bold
  label each.
- Contents: every default chosen, convention conflicts (numbering, term choices, equation layout,
  CI format), unverified facts, tests not in the pipeline, numbers newly computed in scratch,
  figure and caption mismatches, what was cut and what now depends on it, open items carried over.
- On later passes mark items "(resolved)" rather than deleting them.

## 5. Hand-over reply

Full absolute paths (docx, build script), outline with word counts per part, the banned-token
result, defaults chosen, newly computed numbers, unverified facts, open questions. He pastes the
accepted paragraphs into the manuscript skeleton himself; do not write to the skeleton unless asked.
