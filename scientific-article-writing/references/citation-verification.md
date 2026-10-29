# Citation verification: every reference against its full text

Covers checking that each cited source says what the citing sentence claims, that the reference
list is correct, and that uncited claims get a source. Run it when asked to verify citations or
check references, before submission, and after any revision that touched cited sentences.
Distilled from the full audit of 2026-10-22 on the benchmark manuscript (42 references, 87
citations). The global citation rule is `references/global.md` section 4.

## 1. Extract

- Read the docx in the **accepted view** (keep `w:ins` text, drop `w:del`) to plain text, one line
  per paragraph with its paragraph index. Never edit the source.
- Count citation occurrences per section. Separate citations from bracketed numbers that are not
  citations (confidence intervals such as "[86, 97]").

## 2. Mechanical checks first (script, no agents)

- Numbering in order of first appearance; every reference cited; no uncited entries.
- Every in-text "Author et al. (year) [n]" matches the entry's first author and year.

## 3. Every source as a local PDF before any verdict

- Folder `references_pdf\` next to the manuscript, files `NN_FirstAuthor_Year.pdf`.
- Source order: published open version (ACL Anthology, PMLR, publisher open access) > arXiv >
  Semantic Scholar `openAccessPdf`. Web pages are printed to PDF with headless Chrome, the access
  date in the file name.
- Check each file's first page is the right paper.
- Publisher sites that block scripts (Elsevier, ACM, PNAS, JSTOR, jstatsoft): write
  `references_pdf\_MISSING.md` listing per reference the DOI link, the exact file name to save as
  and why the fetch failed. He downloads them to his Downloads folder; the agent identifies each
  download by its first page (a scan without text layer: render a page image), copies it in under
  the right name, and keeps any arXiv copy as `NN_FirstAuthor_Year_arXiv-preprint.pdf`.
- `_MISSING.md` also records which files are preprints or otherwise not the cited version.
- **No final verdict without the full text.** In the 2026-10-22 run, about a quarter of verdicts
  made from abstracts or truncated HTML were overturned once the PDF was read: a "sample of
  individuals" method that used cross-tabulations; an "occupation skew" that was occupational
  diversity plus gender stereotyping; "86% use only GPT" contradicted by the paper's own counts.

## 4. Verify by reference, in topic batches

The unit of verification is the reference, not the sentence.

1. **Batches**: group references by topic, 5 to 9 per subagent (about 7 batches for 42
   references).
2. **One context file per batch**: per reference, the full entry, every citing sentence and the
   full paragraphs around them. **One shared brief file** defines the method below for all
   batches.
3. **Each subagent returns, per reference:**
   - (a) **Record vs PDF**: authors, title, venue, volume, pages, DOI; a preprint cited where a
     peer-reviewed version exists; the in-text year.
   - (b) **Per citing sentence** a verdict SUPPORTED / PARTIALLY SUPPORTED / NOT SUPPORTED /
     MISATTRIBUTED / UNVERIFIABLE, with a verbatim quote and page. Check the numbers, the direction
     of the finding, the scope (models, tasks, populations), the hedging ("suggest" versus
     "concluded"), and whether a stated mechanism was measured or is only the authors'
     explanation.
   - (c) **Paragraph level**: does the citation carry the paragraph's argument; does a sentence
     after the citation present the manuscript's own interpretation as the source's.
   - (d) A **minimal reworded sentence** for every verdict other than SUPPORTED.
   - (e) The **access level actually achieved**: FULL / ABSTRACT / NONE. Never pretend.
4. **Reports**: subagents cannot write report files (blocked); they return the report as text and
   the orchestrator saves it as `report_batchN.md`. Then one consolidated audit file, then a final
   fix list in manuscript order where the latest verdict wins.

## 5. Missing-citation sweep (separate subagent)

- Find claims that need a citation and have none; classify each MUST / SHOULD / OPTIONAL, with a
  canonical source and a DOI verified via Crossref. Candidate sources come from Consensus
  (`references/literature-search.md`).
- Typical gaps: Methods statistics (named tests, indices, corrections, bootstrap); data-source
  tables (official statistics table IDs and year); software with versions; price and web sources
  with access dates; literature-wide or novelty claims ("all approaches...", "no study has...")
  broader than the cited set; placeholders left in the text.

## 6. Applying fixes to the docx

- **Tracked changes in a new file**, never over the source; back up before each pass
  (`references/global.md` section 9.2). Author string as the manuscript folder's
  format rules file sets it (the profile names it); otherwise section 9.2's default. No highlight
  or shading on inserted runs. Minimal word-level diffs that keep the run formatting.
- **Order of passes:**
  1. Sentence rewordings from the fix list.
  2. Reference-entry corrections: only details confirmed from the PDF or Crossref; skip and report
     the rest.
  3. New citations: first a **plan JSON** (new entries verified via Crossref; anchors unique in
     the accepted view; any new disclosure text drafted strictly from code and config, with
     "[SOURCE NEEDED]" instead of a guess), reviewed by the orchestrator. Then insertion and full
     renumbering in order of first appearance: merge and sort brackets, ranges only for 3 or more
     consecutive numbers, new reference paragraphs inserted as tracked paragraphs at their numeric
     position.
- **Verify after every pass:**
  - Reject-all view equals the original source in every paragraph.
  - Accept-all view differs only in the intended places.
  - Every in-text number resolves; every entry cited; first-appearance sequence 1..N without
    gaps; list numbered 1..N.
  - Every revision carries the agreed author; the file opens in python-docx.
  - The orchestrator re-runs the numbering check itself, independently of the subagent.

## 7. His decisions, asked not taken

- Which concrete data tables to cite.
- Renumber versus append when adding references (renumbering is journal-correct).
- Scope of new citations.
- Any new Methods disclosure text.
- Unconfirmed price or provider sources.

## 8. Scripts

Scripts from a run live in the session scratchpad and do not survive it. Rebuild from the logic
above; do not cite their paths.
