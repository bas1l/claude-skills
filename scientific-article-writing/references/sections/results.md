# Results: verified standalone drafts

The first text section, written after the figures and before Methods: one standalone docx per
analysis block, which he then trims and reviews in Word (`references/global.md` section 9).
Build mechanics, banned-token check and the describe-versus-interpret boundary are in
`references/global.md`.

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
  - descriptive paragraph first for grids and rankings, then test paragraphs in the fixed
    sentence order of the project's style model;
  - counts rather than percentages when the denominator is 100;
  - describe the procedure as run; never mention mechanisms that did not apply.

## 2. Correctness pass on kept text

For each kept Results sentence check that it:

- names its rate or count, its unit and its denominator;
- names the comparison (which levels, which population) and the test behind any p value;
- matches the source files (re-verify every number, not only the changed ones);
- has its test described in the kept Methods, and that no Methods test lacks a kept result;
- contains no interpretation (move it to Discussion or flag it);
- uses the settled terms (`references/global.md` section 3).
