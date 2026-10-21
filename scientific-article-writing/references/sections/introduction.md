# Introduction: from the field to this paper's question

Drafted together with the Conclusion (`references/sections/conclusion.md`, its pair), after the
Discussion and the state of the art are kept, or revised then, so that it states only the gap and
the questions the kept Results answer. Claim strength and citation checks are in `references/global.md`
sections 2 and 4; they bind every sentence here. The positioning against prior work is in
`references/sections/state-of-the-art.md`.

## 1. Purpose and shape

- The Introduction says what was studied, why it matters, what is known and what this study
  adds, going from broad to narrow (USC, https://libguides.usc.edu/writingguide/introduction).
- Hourglass, the shape of the whole paper: the Introduction narrows to the question, the
  Discussion widens back from the findings (OUP chapter,
  https://vc.uni-bamberg.de/pluginfile.php/2347251/mod_page/content/11/oso-9780198804789-chapter-8.pdf).
- The Introduction states the aim, the gap and the questions; write each one so that a kept
  Results sentence can answer it. The Conclusion answers them, under the rule of
  `references/sections/conclusion.md` section 2.
- No interpretation of the results: that belongs to the Discussion, and overlap with it is a
  defect (Bahadoran, Jeddi, Mirmiran, Ghasemi, IJEM 2018,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6218661). This holds in biomedical venues (corpus,
  section 8: 10 of 10). ML Introductions often add a one-clause reason beside a previewed result
  (4 of 5 JMLR); if the venue expects it, keep it to one clause and do not restate it in the
  Discussion.

## 2. Moves

Swales' CARS model (https://libguides.usc.edu/writingguide/CARS ;
https://www.umass.edu/writing-center/resources/creating-research-space):

1. **Establish the territory**: why the topic is central, generalisations about it, prior
   research.
2. **Establish a niche**: a counter-claim, a gap, a question, or the continuation of a tradition.
   In the corpus (section 8) the niche is a practical problem or unmet need (6 of 10 biomedical),
   a literature absence (4 of 15), a limit of the prior method (3 of 5 JMLR), competing
   predictions (1) or a continuation (1). Soften a literature absence with its true quantifier
   ("little research has examined", "largely unexplored": 5 of the 6 gaps about the literature or
   data); write "no study has" only beside a documented search.
3. **Occupy the niche**: the purpose of this study; optionally the main findings and the
   structure of the paper (section 3).

The same funnel in biomedical form (Bahadoran 2018): what is known, then what is unknown and why
it matters, then the rationale. End with the aim, stated as an objective or as what the study did
("We aimed to ...", "In this study, we ..."), with the data and design named in the same
paragraph (corpus: 15 of 15 name them; the aim is the last sentence in 8 of 10 biomedical). A
formal question or hypothesis is optional (2 of 15 state one); write it when the Results test
one, because the Conclusion is checked against the stated questions
(`references/sections/conclusion.md` section 2). In an ML venue the aim comes in paragraph 1 or 2
(4 of 5 JMLR) and the Introduction ends with the contribution list.

Computer-science form (Widom, https://cs.stanford.edu/people/widom/paper-writing.html): the
problem; why it matters; why it is hard; why prior work has not solved it; the approach, results
and limitations; then a summary of contributions with forward pointers. Peyton Jones (slides,
https://www.cse.iitm.ac.in/~kalyantv/pdf/writing-a-paper-slides.pdf): about one page; describe
the problem, then state the contributions as a bulleted list, each refutable and forward-referenced
to the section holding its evidence. In the corpus the bulleted list is ML-only (4 of 5 JMLR,
0 of 10 biomedical), after a one-line lead-in ("Our contributions are the following:");
forward references to sections are optional (1 of 5).

Follow the target venue's template where it fixes one (section 6); otherwise use the CARS moves.

## 3. Source disagreements

- **Preview of the results.** Biomedical guidance says not to; it is not the common
  recommendation (Bahadoran 2018). CARS move 3, Widom and Nature ("Here we show",
  https://www.nature.com/nature/authors/gta) say to do it.
- **Roadmap paragraph** ("the rest of this paper"). USC calls omitting it a mistake; Peyton Jones
  says not to write one.
- Default for both: follow the target venue's convention; when the venue is silent, propose a
  choice in the notes and let him decide.
- The corpus (section 8) settles the preview by venue type. Biomedical: no results in the
  Introduction (0 of 10; the Lancet panel or the abstract carries them). ML: headline results
  with numbers (4 of 5 JMLR), repeated in the bulleted contribution list.
- Roadmap: default to none (1 of 15 has one). In an ML venue a forward pointer may sit inside a
  contribution bullet ("In Section 4, we ...").

## 4. Literature and length

- Cite only the literature that justifies the gap; the full positioning goes in its own section
  or is cited sparingly (USC; Bahadoran 2018). Where it goes, and how it is folded
  in at final revision, is decided in `references/sections/state-of-the-art.md` section 3.
- Length, biomedical: 250 to 600 words, 2 to 4 paragraphs, and too long if it exceeds
  two-thirds of the Results (Bahadoran 2018); about 6 to 17% of the main text, median 9%
  (corpus, section 8: 8 of 10 biomedical within the word range, 12 of 15 within the paragraph
  range, only 5 of 15 within the 10 to 15% that Bahadoran gives). Computer science: about one
  page (Peyton Jones); 560 to 690 words in 4 of 5 JMLR.

## 5. Mistakes to check for

Check the draft for each, and fix or flag:

- excess history or background;
- a literature review instead of the gap (USC; Bahadoran 2018);
- too many citations: flag above 5 references per 100 words (the corpus maximum; 13 of 15 lie
  between 2 and 5) and any citation in the aim sentence (uncited in 13 of 15);
- an unsoftened literature gap ("no study has") without a documented search beside it
  (section 2);
- inconsistency with the rest of the paper (aims, terms, scope);
- overlap with the Discussion (section 1);
- overstated novelty. The claims in the abstract and Introduction must reflect the paper's
  contributions and scope; aspirational goals are acceptable only if marked as not attained
  (NeurIPS checklist, https://neurips.cc/public/guides/PaperChecklist). "First" claims are hard to
  substantiate (OUP chapter, https://academic.oup.com/book/58841/chapter/489871368 ,
  **snippet-level**; list it in the notes to verify before citing); hedge with "to our knowledge"
  only under the documented-search rule of `references/sections/state-of-the-art.md` section 5.
  In the corpus "to our knowledge" never appears in an Introduction (0 of 15), a "first" claim
  in 1 of 15; in a Lancet-family paper put it in the panel, next to the search (section 6);
- no clear question or hypothesis;
- a gap the paper does not fill. No source names this as a distinct mistake; it follows from the
  claim-scope rules above (claims reflect the contributions and scope). Check that each stated gap
  has a kept Results sentence that fills it.

## 6. Venue notes

- **TMLR**: the contributions and takeaways must be understandable
  (https://jmlr.org/tmlr/acceptance-criteria.html). Its evidence criterion is in
  `references/sections/discussion.md` section 7, its novelty stance in
  `references/sections/state-of-the-art.md` section 9.
- **PLOS ONE**: context; the problem and its significance; a brief review of the key literature;
  controversies; then a brief statement of the aim. The Introduction follows the abstract
  directly (https://journals.plos.org/plosone/s/submission-guidelines).
- **IJPDS**: reviewers ask that it "set the scene with reference to earlier work and context",
  give "a clear rationale" and keep a clear thread; IMRAD is not mandatory
  (http://ijpds.org/index.php/ijpds/peer-review). Scope: the homepage says submissions relating
  "only to aggregated or statistical datasets are out of scope" (https://ijpds.org/); the
  Introduction must frame the work as population data science, and the fit should be checked with
  the editor before submission.
- **EPJ Data Science**: guidelines unverified (the Springer page redirected to a login). A search
  snippet says the scope favours conceptually new methods and excludes mainly classical-statistics
  applications (https://epjdatascience.springeropen.com/submission-guidelines , **snippet-level**).
- **Lancet family**: the Research in context panel (Evidence before this study, Added value of
  this study, Implications of all the available evidence) carries the documented search, the
  absolute gap, any "to our knowledge" or "first" claim and the findings; the Introduction
  carries the problem, the need and the aim, and repeats none of them (corpus, section 8: 5 of 5).
- **JAMIA family**: Background and Significance, optionally followed by a short Objective
  section (corpus: 1 of 5).
- **ML venues (JMLR, TMLR)**: the aim in paragraph 1 or 2, headline results with numbers, then
  the bulleted contribution list (section 2; corpus: 4 of 5 JMLR).

## 7. Tense and person

- Territory and gap in the present or present perfect (corpus, section 8: 15 of 15); "we" for
  the study (14 of 15).
- The aim in the past tense for Lancet-style venues ("we aimed to", 4 of 5), present for
  informatics and ML venues ("this study aims to", "in this paper, we": 9 of 10).

## 8. Evidence base

The corpus counts in this file come from 15 highly cited open-access articles, 5 each from The
Lancet Digital Health, JAMIA Open and JMLR, extracted in October 2026. Word counts are by script;
paragraph, citation, move and gap counts are by one reader and not double-coded. Five articles per
journal is small: a 4 of 5 versus 5 of 5 difference is one article, and none of the target venues
of section 6 is in the corpus.
