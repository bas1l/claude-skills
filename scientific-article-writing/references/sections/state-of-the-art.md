# State of the art: positioning against prior work

Covers the positioning section itself, whether it is a separate "related work" section or the
literature paragraphs of the Introduction. Drafted after the Discussion, or revised then. The
comparison of our findings with the literature inside the Discussion is in
`references/sections/discussion.md` section 2. Citation checks are in `references/global.md`
section 4.

## 1. Purpose

- Positioning, not a catalogue: the reader must see how this work differs from each prior
  contribution. NeurIPS review form: "Is it clear how this work differs from previous
  contributions, with relevant citations provided?"
  (https://neurips.cc/Conferences/2025/ReviewerGuidelines); the Datasets and Benchmarks track has
  a "Relation to prior work" item
  (https://neurips.cc/Conferences/2023/DatasetsAndBenchmarks/ReviewGuidelines).

## 2. Placement

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
  accept either. Follow the target venue's template; when it is silent, propose a placement in
  the notes and let him decide.

## 3. Organisation

- By idea or subtopic, not source by source; chronological only when the chronology shows a trend
  (UNC, https://writingcenter.unc.edu/tips-and-tools/literature-reviews/ ; CSUN,
  https://libguides.csun.edu/literature-review/synthesis).
- Build a synthesis matrix first: rows are papers, columns are themes; read down a column to
  write that theme's paragraph (Wheaton,
  https://guides.library.wheaton.edu/PSCI361/Organizing_Lit_Review , **snippet-level**).
- End each strand with how this work differs ("Our work differs from White in...", Peyton Jones).

## 4. Search and "first" claims

- A documented search (sources, inclusion criteria, dates, search terms) is the defensible basis
  for any "first" or "to our knowledge" claim. The Lancet "Evidence before this study" panel is
  the model (third-party copy of the author guidelines,
  https://c2.legalinsurrection.com/wp-content/uploads/2024/05/The-Lancet-Author-Guidelines.pdf).
  No target venue requires it; record the search in the notes either way.
- "First" claims: no publisher ban was found, but editors advise against them (LetPub,
  https://www.letpub.com/Let-your-research-speak-for-itself ; doi:10.1177/0310057X211025387;
  both **snippet-level**). Default: avoid the word; if kept, back it with the documented search.

## 5. Recency and preprints

- Work appearing shortly before submission counts as contemporaneous: ICLR 2025 uses the last
  four months (https://iclr.cc/Conferences/2025/FAQ); ACL uses three months
  (https://www.aclweb.org/adminwiki/index.php/ACL_Reviewer_Guidelines). Cite it, but it need not
  be outperformed.
- Preprints: PLOS ONE accepts them with a DOI or arXiv URL; the Lancet marks them "[preprint]".
  Follow the target venue's citation format.

## 6. Cite only what was read

- About 20% of citers read the original, as estimated from the propagation of misprints in
  citations (Simkin & Roychowdhury, https://arxiv.org/abs/cond-mat/0212043). A source not read in
  full is marked under the rule of `references/global.md` section 4.

## 7. Mistakes to check for

Check the draft for each, and fix or flag:

- listing papers instead of positioning against them (section 1);
- strawmanning: "be generous to the competition" (Peyton Jones);
- omitting the closest competitor: "either you don't know... or pretending it's yours" (Peyton
  Jones);
- overlong history;
- terminology misuse: "overloading technical terminology" and "suitcase words" (Lipton &
  Steinhardt, https://arxiv.org/abs/1807.03341);
- related work never reused in the Discussion. This is an inference from the hourglass shape, not
  a rule any source names: each strand positioned here should return in the Discussion's
  comparison with prior work (`references/sections/discussion.md` section 2, item 3), or be cut.

## 8. Benchmark papers

- Novelty of method is not required. TMLR: "novelty of the studied method is not a necessary
  criterion" (https://jmlr.org/tmlr/acceptance-criteria.html).
  NeurIPS: originality "does not necessarily require introducing an entirely new method", and
  "novel insights by evaluating existing methods" are equally valuable (NeurIPS 2025 reviewer
  guidelines, URL in section 1). Both favour a benchmark paper: position it by what it measures that
  prior benchmarks did not, not by a new method.
- Unverified: EPJ Data Science structure; IJPDS author guidelines beyond the reviewer page. TMLR's
  pages do not mention related work.
