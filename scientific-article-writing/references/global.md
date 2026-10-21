# Global rules: every section, every task

Read this for any work on the article, whatever the section. The section files under
`references/sections/` hold only what is specific to one section. The project's
drafting-strategy file (see profile) is the detailed procedure for one analysis block and wins
where it is more specific.

## 1. Working style

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

## 2. Cross-section boundaries and claim strength

- **Results describe, Discussion interprets.** No causes, "suggests", evaluative adjectives
  ("tidy", "defect", "realistic", "better") or literature in Results; Methods states what was
  compared, not why it reads as good or bad.
- **Claim at the strength the statistics support**: a significant difference may be called a
  difference; a descriptive pattern is described as such; a non-significant result is not
  evidence of equality.
- **No untested joint claims.** Two separate findings do not make a "trade-off", a mechanism or a
  dominance claim unless a test addressed the joint statement. (The clash draft's "trade-off"
  framing was dropped for this reason and became a banned body word.)
- **Every number traces to a file and key**, rounded once from the stored value. Numbers computed
  only in scratch are listed as new in the notes.
- **Every test reported is one that exists, is interpretable and is described in Methods**, and
  every Methods test has a Results sentence. Degenerate cases are stated without a p value.

## 3. Terminology

- Use the settled terms everywhere, and the same rank or level names in figure, caption, Results
  and Methods. The figure's term table (`references/sections/figures.md` section 5) records
  the match.

## 4. Citations

- Literature only from verified sources. Each citation is marked checked against the source or
  snippet-only; snippet-only references are listed in the notes to verify before submission.

## 5. House writing style

- **No em dashes, straight quotes only**, and the project's banned-word list, in every output.
- **His own text keeps his voice.** Flag corrections, never rewrite silently.

## 6. Building a docx

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

## 7. Notes for the author

- Heading "Notes for the author (not for submission)" after the body, numbered items, one bold
  label each.
- Contents: every default chosen, convention conflicts (numbering, term choices, equation layout,
  CI format), unverified facts, tests not in the pipeline, numbers newly computed in scratch,
  figure and caption mismatches, what was cut and what now depends on it, open items carried over.
- On later passes mark items "(resolved)" rather than deleting them.

## 8. Hand-over reply

Full absolute paths (docx, build script), outline with word counts per part, the banned-token
result, defaults chosen, newly computed numbers, unverified facts, open questions. He pastes the
accepted paragraphs into the manuscript skeleton himself; do not write to the skeleton unless asked.

## 9. Review and trim loop: working on a docx he has edited

Applies when he hands back `...reviewed.docx`, `...trimmed.docx` or any draft he has opened, and
asks for criticism, corrections or suggested edits. Section-specific checks on kept text live in
the section file (for Results: `references/sections/results.md` section 2).

### 9.1 What a trim means

His trim is deliberate: its purpose is to limit how much information the article carries. **A
trim is a decision**: the review works **only on what he kept**, adds the minimum context a kept
sentence needs, and never restores a cut.

- Allowed: the minimal context a kept sentence needs (name an unlabelled rate, give the
  denominator, say which comparison a p value belongs to), factual corrections (a wrong number, a
  wrong figure or panel reference), grammar and punctuation, terminology fixes.
- Not allowed: re-pasting removed results, tests, tables or paragraphs, even when Methods or
  Discussion still depend on them. Flag the dependency in prose (in the reply or the notes) and
  let him decide whether to cut the other section too.
- Default to the smallest edit. Mention missing blocks; do not insert them.

### 9.2 Mechanics

1. **Backup first**, before any edit to a file he has opened: copy the file to the project backup
   folder as `<name>_YYYY-MM-DD_HHMM.docx`; assert the backup name does not already exist.
2. **Lock check**: refuse while a `~$` Word lock file sits beside it; ask him to close Word.
3. **Scope**: touch only the section or paragraph he asked about. Record the paragraph texts
   before, and assert afterwards that every other paragraph is identical.
4. **Tracked changes**, edited in place at run level in `word/document.xml`: `w:del` around the
   old runs (their `w:t` renamed to `w:delText`) and `w:ins` with the new run, copying the
   original run properties. Author is **"Suggested edits"**, never a name and never Claude. One
   tracked change per logical edit.
5. **Verify**: count `w:ins` and `w:del`, re-read the text, re-run the banned-token checks on the
   inserted text, and report old and new word counts of each changed paragraph.
6. Never regenerate a file he has opened from its build script.

### 9.3 Unresolved revisions in his file

If his file still holds tracked changes he has not accepted or rejected, stop and ask which way
he wants them, unless they are trivial punctuation. Trivial ones may be resolved **in a copy
only**, never in his file, and each resolution is listed in the notes (what, accepted or
rejected, why).

### 9.4 Building a new version from his trimmed text

When he asks for a next version (for example Methods and Discussion fitted to his trimmed
Results), copy his kept text and formatting verbatim into the new file, build the new parts
around it, save under a new suffix, and list in the notes exactly what was taken from his file
and what remains open. What each section must additionally list is in its section file.

### 9.5 Restructuring a section he wrote

When he asks to reorder a section (for example Methods to follow the Results order,
`references/sections/methods.md` section 2):

- Move his sentences verbatim; split only a sentence that mixes two outcomes, keeping its words.
  No rewording, no new content beyond the minimal bridge a moved sentence needs (flag each one).
- Deliver as **tracked changes in a new file** (moves as `w:del` at the old place and `w:ins` at
  the new one, author "Suggested edits"), never in his file, after the backup and lock checks of
  section 9.2.
- Also deliver a **clean accepted-view preview** (a separate file with all changes accepted) so
  he can read the new order without the markup.
- Verify that the multiset of his words is unchanged apart from listed splits and bridges, and
  that equation numbers and references follow the new order.
