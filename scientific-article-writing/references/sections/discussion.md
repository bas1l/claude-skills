# Discussion: what the kept Results mean

Drafted together with the state of the art (`references/sections/state-of-the-art.md`, its
pair), after the Results and Methods are kept, interpreting the kept Results. Writing it before
his trim invites claims about results that no longer appear. Claim strength, untested joint claims and citation checks are in
`references/global.md` sections 2 and 4; they bind every sentence here.

## 1. Purpose and shape

- The Discussion answers "what do the results mean?". It is mostly interpretation, not
  repetition of the Results (Springer Nature, author guidance,
  https://www.springernature.com/gp/authors/campaigns/writing-a-manuscript/results ; Hess 2004,
  Respir Care 49:1238, https://www.math.ualberta.ca/~thillen/winter13/Hess-discussion.pdf).
- Shape: from narrow (our own findings) to wide (the literature) (HKU CAES,
  https://caes.hku.hk/acadgrammar/report/repProc/sections/discuss/general.htm); the hourglass of
  the whole paper is in `references/sections/introduction.md` section 1.
- Its link to the rest of the paper is the state of the art: the comparison with prior work
  (section 2, item 3) takes up the strands positioned there, under the rule of
  `references/sections/state-of-the-art.md` section 2. The questions the Introduction states are
  answered by the Conclusion (`references/sections/conclusion.md` section 2).

## 2. Default paragraph order

The order below is Hess 2004's, with his "relevance" step folded into implications. Docherty &
Smith, BMJ 1999;318:1224
(https://www.equator-network.org/reporting-guidelines/the-case-for-structuring-the-discussion-of-scientific-papers/ ;
**snippet-level**: the wording comes from secondary summaries, the BMJ PDF returned 403; list it in
the notes to verify before citing) use a different order: principal findings, then strengths and
weaknesses of the study, then comparison with other studies, then meaning, then unanswered
questions. Follow the target venue's template where it fixes one; otherwise use this one:

1. **Principal finding** in one plain sentence, no numbers.
2. **Meaning** of the findings, most to least important.
3. **Comparison with prior work**, including why our results differ where they do, against the
   strands the state of the art positions (`references/sections/state-of-the-art.md` section 2).
4. **Alternative explanations**: "the purpose of research is to discover and not to prove"
   (Hess 2004). State each rival explanation the design cannot exclude.
5. **Strengths and limitations**, given equal weight (section 3).
6. **Implications**, with untested ones labelled as hypotheses.
7. **Open questions and future work**, each specific (which question, which design would answer
   it); never "more studies are needed".

Findings are discussed in order of importance, most to least important (Springer Nature, above),
**not** in the order of the Results: the Results and Methods share one order (`methods.md`), the
Discussion does not follow it. Importance is judged by how much the finding changes the paper's
answer to its question; when the ranking is not obvious, propose it in the notes and let him decide.

The take-home message, and how the Discussion ends when the venue has no Conclusions section, are
in `references/sections/conclusion.md` sections 1 and 6.

## 3. Limitations

- Limits of the design stated plainly (judge self-consistency is not validity, sample size,
  single run).
- Each limitation states three things: the limitation, its consequence for inference or
  generalisability, and any mitigation (Ross & Zaidi 2019,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6684501).
- No generic disclaimers. Lingard 2015 names the failure modes: the "confessional" list, the
  "dismissal" that waves each limit away, versus the "reflection" that says what the limit means
  for the claim (https://pmc.ncbi.nlm.nih.gov/articles/PMC4456466; **snippet-level**: the three
  labels were taken from the page without a quoted passage; verify before citing). Write the
  reflection.
- Whether limitations sit inside the Discussion or in a separate section is the venue's choice:
  follow the target venue's template (section 7).

## 4. Null and unexpected results

- Report and interpret them; do not bury or explain them away. A non-significant result is
  still not evidence of equality (`references/global.md` section 2).

## 5. Mistakes to check for

Check the draft for each, and fix or flag:

- repeating the Results (numbers already reported come back only where an interpretation needs
  them);
- introducing new results not in the kept Results;
- a second literature review instead of a comparison with the findings;
- overinterpretation: "the data are the data" (Hess 2004); no claim beyond what was measured;
- unlabelled speculation: write "we speculate that";
- causal wording from non-randomised designs; spin of this kind appeared in 53% of 128 abstracts
  (Lazarus et al. 2015, BMC Med Res Methodol 15:85, https://www.biomedcentral.com/1471-2288/15/85);
- attacking other authors rather than explaining why results differ;
- trivial endings ("more research is needed", ending on a restated principal finding).

## 6. Benchmark and methods papers

- State what the benchmark does **not** measure: its construct validity, that is how far the
  score stands in for the target property (Raji et al. 2021, "AI and the Everything in the Whole
  Wide World Benchmark", https://arxiv.org/abs/2111.15366 ; Bean et al., NeurIPS 2025 Datasets
  and Benchmarks track,
  https://proceedings.neurips.cc/paper_files/paper/2025/hash/1967e0fc3aa6cbbace562f5cb8e3954e-Abstract-Datasets_and_Benchmarks_Track.html).
- Structure threats to validity as internal versus external (Liao et al. 2021, NeurIPS Datasets
  and Benchmarks track,
  https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/757b505cfd34c64c85ca5b5690ee5293-Abstract-round2.html).
- Scope each claim to how far the results generalise (populations, models, settings actually
  tested) (NeurIPS paper checklist, https://neurips.cc/public/guides/PaperChecklist).

## 7. Venue notes

- **PLOS ONE**, criterion 4: conclusions must be supported by the data; implications are allowed
  if labelled as hypotheses. A combined Results and Discussion is allowed, not required
  (https://journals.plos.org/plosone/s/criteria-for-publication).
- **TMLR**: claims supported by evidence is the most important criterion, and reducing the claims
  is an accepted remedy (https://jmlr.org/tmlr/acceptance-criteria.html). When a claim lacks
  support, offer the narrower claim before any new analysis.
- **IJPDS**: reviewers expect contextualisation against published work plus recognised
  limitations (http://ijpds.org/index.php/ijpds/peer-review).
- **NeurIPS-style venues** encourage a separate Limitations section.

## 8. Hand-over specifics

- **Length is not constrained while drafting** the Discussion or its paired state of the art. The
  length check of `references/sections/state-of-the-art.md` section 11 is the last step before
  the Discussion counts as finished: report word counts, propose cuts in the notes, apply none
  without his agreement.
- Before that final check, run the flag-only check of `references/sections/state-of-the-art.md`
  section 2 (strands not taken up, new literature cited here) and list the results in the notes.

- Links to other sections are flagged in the notes when a sentence rests on results reported
  elsewhere.
- When fitting a Discussion to his trimmed Results (`references/global.md` section 9.4), list in
  the notes what was cut from the Discussion to match.
