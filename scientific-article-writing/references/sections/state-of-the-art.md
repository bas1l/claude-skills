# State of the art: positioning against prior work

Covers the positioning section itself, whether it is a separate "related work" section or the
literature paragraphs of the Introduction. Drafted together with the Discussion
(`references/sections/discussion.md`, its pair), after the Results and Methods are kept, or
revised then. Citation checks are in `references/global.md` section 4.

## 1. Purpose

- Positioning, not a catalogue: the reader must see how this work differs from each prior
  contribution. NeurIPS review form: "Is it clear how this work differs from previous
  contributions, with relevant citations provided?"
  (https://neurips.cc/Conferences/2025/ReviewerGuidelines); the Datasets and Benchmarks track has
  a "Relation to prior work" item
  (https://neurips.cc/Conferences/2023/DatasetsAndBenchmarks/ReviewGuidelines).

## 2. Link to the Discussion

A check, not a requirement: it flags, it never cuts.

- Strands of prior work set up here are taken up again where the Discussion's comparison with
  prior work needs them (`references/sections/discussion.md` section 2, item 3). A strand that
  does not return there is flagged in the notes, not cut; he decides whether it stays.
- The Discussion may cite literature not positioned here (for example work that bears only on an
  unexpected result). Each such addition is listed in the notes, with the question of whether it
  belongs here instead.
- Evidence: in 15 highly cited articles (5 each from The Lancet Digital Health, JAMIA Open and
  JMLR, extracted in October 2026; counts by script, not checked by hand), the Discussion cited
  again 0 to 67% of the works positioned early (JAMIA Open median about 10%), and mostly cited new
  ones. No source states a return rule; the check follows from drafting the two sections as a pair
  and from the hourglass shape of the paper (`references/sections/introduction.md` section 1).

## 3. Placement

**Operating rule.** During drafting, keep the state of the art as a separate, temporary section,
even for venues such as PLOS ONE and IJPDS that expect it inside the Introduction: it is easier to
write and to keep in step with the Discussion that way. At final revision, fold it into the
Introduction where the venue expects that. The fold is minimal: move the paragraphs and trim them
lightly; do not rewrite them. List in the notes what the fold trimmed.

Background on where venues and guides put it, which decides the final placement:

- **PLOS ONE**: no separate section; the literature sits in the Introduction
  (`references/sections/introduction.md` section 6).
- **IJPDS**: no separate section either; earlier work goes in the introduction
  (`references/sections/introduction.md` section 6) and the comparison of results in the
  discussion (`references/sections/discussion.md` section 7).
- **Computer science**: Peyton Jones puts it late, before the conclusions, 1 to 2 pages, with "No
  related work yet!" before the reader has your idea
  (https://www.cs.ru.nl/~jhh/archive/2022/secsem/reader/writing-paper.pdf). Widom puts it early
  if it can be short yet detailed or a defensive stance is critical, late if the comparisons need
  the paper's technical content (https://cs.stanford.edu/people/widom/paper-writing.html).
- Trade-off: biomedical and population-data venues expect it in the Introduction; ML venues
  accept either. The final placement follows the target venue's template; when it is silent,
  propose a placement in the notes and let him decide.

## 4. Organisation

- By idea or subtopic, not source by source; chronological only when the chronology shows a trend
  (UNC, https://writingcenter.unc.edu/tips-and-tools/literature-reviews/ ; CSUN,
  https://libguides.csun.edu/literature-review/synthesis).
- Build a synthesis matrix first: rows are papers, columns are themes; read down a column to
  write that theme's paragraph (Wheaton,
  https://guides.library.wheaton.edu/PSCI361/Organizing_Lit_Review , **snippet-level**).
- End each strand with how this work differs ("Our work differs from White in...", Peyton Jones).
  Recommended practice, not the norm: only 4 of the 15 articles of section 2 do it. Keep it for a
  benchmark paper, which must show what it measures that earlier benchmarks do not (section 9);
  at minimum, the section as a whole states the difference.

## 5. Search and "first" claims

- A documented search (sources, inclusion criteria, dates, search terms) is the defensible basis
  for any "first" or "to our knowledge" claim. The Lancet "Evidence before this study" panel is
  the model (third-party copy of the author guidelines,
  https://c2.legalinsurrection.com/wp-content/uploads/2024/05/The-Lancet-Author-Guidelines.pdf).
  No target venue requires it; record the search in the notes either way.
- "First" claims: no publisher ban was found, but editors advise against them (LetPub,
  https://www.letpub.com/Let-your-research-speak-for-itself ; doi:10.1177/0310057X211025387;
  both **snippet-level**). Default: avoid the word; if kept, back it with the documented search.

## 6. Recency and preprints

- Work appearing shortly before submission counts as contemporaneous: ICLR 2025 uses the last
  four months (https://iclr.cc/Conferences/2025/FAQ); ACL uses three months
  (https://www.aclweb.org/adminwiki/index.php/ACL_Reviewer_Guidelines). Cite it, but it need not
  be outperformed.
- Preprints: PLOS ONE accepts them with a DOI or arXiv URL; the Lancet marks them "[preprint]".
  Follow the target venue's citation format.

## 7. Cite only what was read

- About 20% of citers read the original, as estimated from the propagation of misprints in
  citations (Simkin & Roychowdhury, https://arxiv.org/abs/cond-mat/0212043). A source not read in
  full is marked under the rule of `references/global.md` section 4.

## 8. Mistakes to check for

Check the draft for each, and fix or flag:

- listing papers instead of positioning against them (section 1);
- strawmanning: "be generous to the competition" (Peyton Jones);
- omitting the closest competitor: "either you don't know... or pretending it's yours" (Peyton
  Jones); only 4 of the 15 articles of section 2 name it, but a benchmark paper should;
- overlong history, or over the length norm at the final check (section 11);
- the gap stated inside the related-work body instead of the Introduction (section 10);
- terminology misuse: "overloading technical terminology" and "suitcase words" (Lipton &
  Steinhardt, https://arxiv.org/abs/1807.03341);
- a strand never taken up in the Discussion, or a Discussion comparison against new literature
  not listed in the notes (section 2): flag, do not cut.

## 9. Benchmark papers

- Novelty of method is not required. TMLR: "novelty of the studied method is not a necessary
  criterion" (https://jmlr.org/tmlr/acceptance-criteria.html).
  NeurIPS: originality "does not necessarily require introducing an entirely new method", and
  "novel insights by evaluating existing methods" are equally valuable (NeurIPS 2025 reviewer
  guidelines, URL in section 1). Both favour a benchmark paper: position it by what it measures that
  prior benchmarks did not, not by a new method.
- Unverified: EPJ Data Science structure; IJPDS author guidelines beyond the reviewer page. TMLR's
  pages do not mention related work.

## 10. Gap, framing and tense

Observed in all 15 articles of section 2 (common practice in highly cited work, not a venue rule):

- **The gap lives in the Introduction**, stated once, before the method
  (`references/sections/introduction.md` section 2, move 2). This section positions the work
  against prior contributions; it does not carry the gap. A related-work section placed late (as
  in all 5 JMLR articles) still leaves the gap in the Introduction.
- **The gap is phrased as an absence or a need** ("no study has compared...", "has yet to be
  measured"), not as a fault of named authors.
- **Prior work is framed as complementary or supporting**, never as wrong ("these approaches are
  complementary"). This is the operational form of "be generous to the competition" (section 8).
- **Tense**: present tense for what is established ("X measures Y"), then "we" for this work.
- **Novelty is shown, not announced**: by what this work measures or by numbers, with "first"
  avoided (section 5).

## 11. Length: the last check, never a drafting constraint

- **While drafting the Discussion and the state of the art, do not constrain length.** Write
  each strand as long as the positioning needs; trimming early cuts strands before the Discussion
  has shown which ones it needs.
- **The length check is the final step of the stage**, run once the Discussion is otherwise
  finished (`references/sections/discussion.md` section 8), and before the stage counts as done.
  It reports word counts in the notes and proposes cuts; it does not apply them without his
  agreement.
- Norm from the 15 articles of section 2: about 300 to 1,100 words, at most about 12% of the
  main text (JAMIA Open 300 to 650 words, 7 to 14%; JMLR 456 to 1,101 words, 3 to 12%; Lancet
  Digital Health Introductions 232 to 582 words, with the panel beside them). When folded into
  the Introduction at final revision (section 3), the Introduction's own length rule also applies
  (`references/sections/introduction.md` section 4).
