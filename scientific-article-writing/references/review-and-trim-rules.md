# Review and trim rules: working on a docx he has edited

Applies when he hands back `...reviewed.docx`, `...trimmed.docx` or any draft he has opened, and
asks for criticism, corrections or suggested edits.

## 1. What a trim means

His trim is deliberate: its purpose is to limit how much information the article carries. The
review therefore works **only on what he kept**.

- Allowed: the minimal context a kept sentence needs (name an unlabelled rate, give the
  denominator, say which comparison a p value belongs to), factual corrections (a wrong number, a
  wrong figure or panel reference), grammar and punctuation, terminology fixes.
- Not allowed: re-pasting removed results, tests, tables or paragraphs, even when Methods or
  Discussion still depend on them. Flag the dependency in prose (in the reply or the notes) and
  let him decide whether to cut the other section too.
- Default to the smallest edit. Mention missing blocks; do not insert them.

## 2. Mechanics

1. **Backup first**: copy the file to the project backup folder as
   `<name>_YYYY-MM-DD_HHMM.docx`; assert the backup name does not already exist.
2. **Lock check**: refuse while a `~$` Word lock file sits beside it; ask him to close Word.
3. **Scope**: touch only the section or paragraph he asked about. Record the paragraph texts
   before, and assert afterwards that every other paragraph is identical.
4. **Tracked changes** in `word/document.xml`: `w:del` around the old runs (their `w:t` renamed
   to `w:delText`) and `w:ins` with the new run, copying the original run properties. Author is
   **"Suggested edits"**, never a name and never Claude. One tracked change per logical edit.
5. **Verify**: count `w:ins` and `w:del`, re-read the text, re-run the banned-token checks on the
   inserted text, and report old and new word counts of each changed paragraph.
6. Never regenerate a file he has opened from its build script.

## 3. Correctness pass on kept text

For each kept Results sentence check that it:

- names its rate or count, its unit and its denominator;
- names the comparison (which levels, which population) and the test behind any p value;
- matches the source files (re-verify every number, not only the changed ones);
- has its test described in the kept Methods, and that no Methods test lacks a kept result;
- contains no interpretation (move it to Discussion or flag it);
- uses the settled terms, and the same rank or level names as the figure and caption.

## 4. Unresolved revisions in his file

If his file still holds tracked changes he has not accepted or rejected, stop and ask which way
he wants them, unless they are trivial punctuation. Trivial ones may be resolved **in a copy
only**, never in his file, and each resolution is listed in the notes (what, accepted or
rejected, why).

## 5. Building a new version from his trimmed text

When he asks for a next version (for example Methods and Discussion fitted to his trimmed
Results), copy his kept text and formatting verbatim into the new file, build the new parts
around it, save under a new suffix, and list in the notes exactly what was taken from his file,
what was cut from Methods and Discussion to match, and what remains open.

## 6. Restructuring a section he wrote

When he asks to reorder a section (for example Methods to follow the Results order, see
`text-drafting-loop.md` section 2):

- Move his sentences verbatim; split only a sentence that mixes two outcomes, keeping its words.
  No rewording, no new content beyond the minimal bridge a moved sentence needs (flag each one).
- Deliver as **tracked changes in a new file** (moves as `w:del` at the old place and `w:ins` at
  the new one, author "Suggested edits"), never in his file, after the backup and lock checks of
  section 2.
- Also deliver a **clean accepted-view preview** (a separate file with all changes accepted) so
  he can read the new order without the markup.
- Verify that the multiset of his words is unchanged apart from listed splits and bridges, and
  that equation numbers and references follow the new order.
