# Conclusion: the take-home message

Drafted together with the Introduction (`references/sections/introduction.md`, its pair), after
the Discussion, or revised then, so that it answers only what the kept Results support. Claim strength and citation checks are in `references/global.md` sections 2 and 4; they
bind every sentence here.

Counts marked "corpus" come from 15 highly cited open-access articles (5 each from The Lancet
Digital Health, JAMIA Open and JMLR, extracted in October 2026; word counts and shares of the
main text by script; every other count, verdict and label by one reader, by hand, single pass,
not checked by a second reader). The corpus shows practice, not guidance: where practice breaks a rule below (spin, untested
recommendations), the rule stands. Section 7 lists what the corpus does and does not support.

## 1. Purpose

- The Conclusion holds the take-home message: a short answer to the Introduction's aim
  (section 2). The Discussion interprets, compares and
  covers limitations in depth; the Abstract summarises the whole study (Editage,
  https://www.editage.com/insights/discussion-vs-conclusion-in-research-paper).
- It says what the principal finding means and why it matters. It does not rewrite the abstract
  and does not open with "we investigated..." (PLOS,
  https://explore.plos.org/author-resources/how-to-write-effective-discussions-and-conclusions).
- **Opening with what was done** is allowed only when the same sentence states the result:
  "By jointly pre-training the retriever module and the language model, we show that Atlas has
  strong few-shot learning capabilities" (JMLR, Atlas). A Conclusion that only describes what was
  done answers no aim: "we described the opportunities and challenges facing providers" (JAMIA
  Open). Corpus: 4/15 open with "In this paper / work / study, we", 3 of them JMLR; 8/15 open with
  the finding itself.

## 2. Contents and length

- **Answer the Introduction.** "Link the conclusions with the goals of the study" (ICMJE,
  https://www.icmje.org/recommendations/browse/manuscript-preparation/preparing-for-submission.html):
  answer the aim and each question the Introduction states
  (`references/sections/introduction.md` section 1). Flag in the notes any stated question left
  without an answer, and any conclusion that answers no stated question.
- **Check clause by clause.** An aim that lists N outcomes needs N answers. The usual miss is the
  last outcome listed (an aim naming "documentation burden, after-hours work, burnout risk, and job
  satisfaction" whose Conclusion never mentions burnout) or the second half of a paired aim ("the
  strengths and limitations of using synthetic data", answered on strengths only). Corpus: aim
  fully answered 7/15, partly 6/15, not at all 2/15.
- The key findings without inferential statistics: no P values, intervals or test names (corpus:
  none in 15/15). One headline score may be quoted when it is the paper's central result, as ML
  venues commonly do (corpus: 4/15, 3/5 JMLR, e.g. "75.2% on five-shot MMLU"); it matches the
  Results value exactly and keeps its Results label (one corpus article turns a 91.6% "accuracy"
  into "92% performance in assessing overall potential eligibility"). Then why the findings
  matter; one implication or next step (Editage; PLOS; corpus: an implication in 12/15).
- At most one sentence on limitations (Editage); the limitations themselves are in the
  Discussion.
- **Where the limitations go.** The limitations paragraph, and any detailed list of future work,
  sits immediately before the Conclusion: the last paragraphs of the Discussion, or a separate
  "Future Work" or "Open Questions" section in ML venues. The Conclusion keeps at most one sentence
  of each. Corpus: limitations immediately before the ending in 8/10 Lancet Digital Health and
  JAMIA Open articles; a separate forward-looking section in 2/5 JMLR; when the Conclusion itself
  carries a limitation or scope statement (5/15), it is one or two sentences.
- Future work only if specific, under the rule of `references/sections/discussion.md` section 2,
  item 7: name the research needed, never a bare "further research is needed" (secondary source,
  https://en.wikipedia.org/wiki/Further_research_is_needed , **snippet-level**; a claimed BMJ ban
  on the phrase is unverified, do not cite it). Corpus: future work in 8/15 Conclusions, specific
  in 7 of them.
- **The last sentence** states the implication or one specific next step. A closing "we hope our
  work ..." or "this study provides an example of ..." carries no content; replace it with the
  step. Corpus: 9/15 end looking forward; 3/15 (all JMLR) end on "we hope" or "we believe"; 3/15
  end on a statement about the paper's own contribution or a model release.
- Length: one or two paragraphs, about 50 to 180 words; one paragraph is the most common form.
  Corpus: 8/9 Conclusion sections have one or two paragraphs, none has three, median 135 words
  (range 56 to 177, one outlier of 748 words), 1.6 to 4.2% of the main text. Guidance sources
  give two or three paragraphs (PLOS) and one to three short paragraphs (CASRAI,
  https://casrai.org/guides/how-to-write-a-conclusion-for-a-research-paper). No journal found sets
  a word limit.

## 3. Rules

- **No new data or arguments** (PLOS; Editage). Everything stated was reported in the kept
  Results and interpreted in the Discussion. The two common violations, which are checked by
  name: an opening sentence of background the reader already has from the Introduction ("SARS-CoV-2
  has provided a stark reminder that infectious diseases are a major threat ..."), and a
  recommendation or application the study did not test ("frequent handwashing ... should be
  routine behaviour within every population"; "data compression" as a benefit of an image
  generator). Corpus: 7/15 contain one or both, 4/15 each.
- **Citations: sources disagree.** UCL allows citations already made earlier but no new ones
  (https://www.ucl.ac.uk/ioe-writing-centre/organise-and-structure-your-writing/conclusion ,
  **snippet-level**, the page returned 403); some journals ban citations entirely (LSMU,
  **snippet-level**); the target venues say nothing. Default: no new citations; follow the target
  venue's template if it fixes a rule. Corpus: no new citation in 15/15; no citation at all in
  13/15.
- **No overclaiming**: "avoid unqualified statements and conclusions not adequately supported by
  the data" (ICMJE); do not overstate importance (PLOS). Claims stay within the generalisation
  scope set in `references/sections/discussion.md` section 6.
- **Consistency**: the abstract's conclusion and the main-text conclusion agree with each other
  and with the results (Chiu et al. 2017, https://pmc.ncbi.nlm.nih.gov/articles/PMC5593172/).
  Compare them sentence by sentence and flag any difference in the notes.

## 4. Spin in conclusions

Spin is "specific reporting practices that distort the interpretation of results and mislead
readers"; its most common form is a conclusion more favourable than the results, with prevalence
reported from 26 to 84% (Chiu et al. 2017). Evidence that conclusions are where it concentrates:

- Boutron et al. 2010, 72 trials with a nonsignificant primary outcome: spin in 37.5% of abstract
  conclusions and 50% of main-text conclusions
  (https://jamanetwork.com/journals/jama/fullarticle/185958 ; figures from a secondary summary,
  **snippet-level**).
- Lazarus et al. 2015, 128 non-randomised studies: 84% of abstracts had at least one form of spin;
  48% had high spin in their conclusions; extrapolation to another population or setting in 8.6%;
  a recommendation for practice without adequate evidence in 19.5%
  (https://pmc.ncbi.nlm.nih.gov/articles/PMC4604617/). Its causal-wording figure is applied in
  `references/sections/discussion.md` section 5.
- Corpus: at least one claim stronger than the evidence in 5/15 Conclusions, including highly
  cited ones.

All three studies are biomedical; applying them to an ML benchmark is an analogy. Check the draft
for: a conclusion more favourable than the results, extrapolation beyond the populations, models
and settings tested, and recommendations the evidence does not support; "significantly" on any
outcome that was not tested (one corpus Conclusion reports that a tool "significantly improved
... job satisfaction" when only 2 survey items were tested); a perception or proxy restated as the
outcome itself (clinicians' reported after-hours time written as "reduced after-hours work");
boosters ("breakthrough", "outstanding", "It is obvious that").

## 5. Venue notes

- **PLOS ONE**: a Conclusions section is optional, and sections may be combined
  (https://journals.plos.org/plosone/s/submission-guidelines).
- **IJPDS**: a conclusion is required (https://ijpds.org/index.php/ijpds/author-guidelines); the
  abstract's headings are in `references/sections/abstract.md` section 5.
- **TMLR**: no section structure prescribed; a Broader Impact statement only for work with a
  significant risk of harm (https://jmlr.org/tmlr/author-guide.html).
- **NeurIPS checklist**: its claim-scope items are applied in
  `references/sections/discussion.md` sections 6 and 7 and `references/sections/introduction.md`
  section 5; a Conclusion claim may not go further than either.
- **EPJ Data Science**: unverified.

## 6. When the venue has no Conclusions section

The last paragraph of the Discussion acts as the Conclusion and follows sections 1 to 4. It comes
after the limitations paragraph, never before it. It may open with a signpost ("In summary," or
"In conclusion,"), restates the principal finding in one sentence without statistics, and ends on
the finding's implication, linking it to the wider subject, or on a specific piece of future
research (PLOS). It follows the rules of section 3: no new evidence, hedging that matches the
evidence, and agreement with the abstract's conclusion. The restated finding is never the last
sentence: a paragraph that ends on it, or on "more research is needed", is the trivial ending of
`references/sections/discussion.md` section 5. Corpus: none of the 5 Lancet Digital Health
articles has a Conclusions section; in 4/5 the last paragraph restates the principal finding
("In summary, a novel, externally validated deep learning system provides rapid measurements of
plaque volume ..."), in 3/5 it opens on a signpost, in 4/5 it follows the limitations paragraph,
and in 5/5 it states an implication. The one that does not restate the finding answers no aim and
ends on untested recommendations.

## 7. What the corpus supports

- Kept unchanged because the corpus agrees: no new citations (15/15); future work specific when
  present (7/8); at most one or two sentences of limitation when present (5/5).
- No rule is set for person or tense: first person in 11/15; the finding is in past or present
  perfect in 7 and in present in 6; implications are in present or modal tense throughout.
- Limits: 5 articles per journal cannot separate a journal convention from chance; citation
  counts measure influence, not writing quality; one coder, single pass; JMLR texts come from
  PDF extraction with tables lost.
