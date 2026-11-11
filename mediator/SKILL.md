---
name: mediator
description: "Impartial adjudicator — takes two documents with opposing viewpoints, analyses both using structured argumentation frameworks, and delivers a reasoned verdict on which points are reasonable"
allowed-tools:
  - Glob
  - Read
  - Grep
  - Write
  - WebSearch
  - WebFetch
---

# Mediator — Structured Adjudication of Opposing Viewpoints

This skill acts as an **impartial adjudicator** between two documents presenting
opposing positions. It decomposes each side's arguments, evaluates evidence
quality, checks for logical validity, and delivers a reasoned per-point verdict
on which claims are reasonable — backed by explicit criteria, web research, and
transparent reasoning.

It writes its adjudication report to a `.mediation.md` file alongside the input documents.

It receives `$ARGUMENTS` which must identify **two documents** to adjudicate.
Accepted formats:
- Two plan/idea names separated by `vs` or `versus` (e.g., `plan-a vs plan-b`)
- Two file paths separated by `vs` or `versus`
- A single plan name that has an associated `-challenge.md` file in
  `docs/development/challenges/` (auto-pairs the plan with its challenge)

---

## Step 1: Locate and load both documents

### 1a. Parse the input

Split `$ARGUMENTS` on `vs` or `versus` (case-insensitive, trimmed).

- If **two parts** found → match each independently (Step 1b)
- If **one part** found → match it as a plan/idea, then look for a paired
  challenge file in `docs/development/challenges/` named `<plan-slug>-challenge.md`.
  If found, use the plan as Document A and the challenge as Document B. If no
  challenge file exists, ask the user to provide the second document, **stop**.
- If `$ARGUMENTS` is **empty** → ask the user what to mediate, **stop**.

### 1b. Match each document

Use **three-pass matching** (stop at first hit) for each document identifier:

1. **Exact filename:** matches a filename (with or without `.md`)
2. **Slug containment:** slugify the identifier (lowercase, spaces/special chars
   → hyphens, collapse runs), check if any filename **starts with** or
   **contains** the slug
3. **Title search:** read `# Plan:` or `# Idea:` headings from files,
   case-insensitive substring match

Search order across directories:
- `docs/development/plans/ideas/`
- `docs/development/plans/pending/`
- `docs/development/plans/active/`
- `docs/development/plans/completed/`
- `docs/development/challenges/`

Rules:
- If **multiple files** match for either side → list matches, ask the user to
  clarify, **stop**.
- If **no match** and the identifier looks like a file path → attempt to read it
  directly.
- If **no match** at all → inform the user, **stop**.

### 1c. Label the documents

Assign neutral labels:
- **Document A** — the first document (or the plan when auto-paired)
- **Document B** — the second document (or the challenge when auto-paired)

Read both documents in full before proceeding.

---

## Step 2: Decompose each position (Toulmin Analysis)

For each document, extract and organize arguments using the **Toulmin model**:

| Component | What to extract |
|-----------|----------------|
| **Claims** | Central assertions and sub-claims |
| **Evidence/Grounds** | Data, studies, examples, or facts cited to support claims |
| **Warrants** | The reasoning connecting evidence to claims (often implicit) |
| **Backing** | Support for the warrants themselves |
| **Qualifiers** | Degree of certainty expressed ("always", "likely", "sometimes") |
| **Rebuttals** | Exceptions, limitations, or counter-arguments the document acknowledges |

For each document, produce:
- A **3–5 bullet summary** of the core position
- A numbered list of **discrete claims** (typically 3–8 per document)
- For each claim: the evidence offered, the warrant used, and any qualifiers

Present this as:

```
## Document A: <title>
### Position Summary
[3–5 bullets]

### Claims
1. **[Claim]** — Evidence: [what's cited] | Warrant: [reasoning] | Qualifier: [certainty level]
2. ...

## Document B: <title>
### Position Summary
[3–5 bullets]

### Claims
1. ...
```

---

## Step 3: Map the disagreement

Identify the **specific points of contention** between the two documents.
Classify each into:

| Category | Description |
|----------|-------------|
| **Direct contradiction** | Both sides make incompatible factual or logical claims about the same thing |
| **Competing interpretation** | Both accept similar facts but draw different conclusions |
| **Scope disagreement** | One side addresses something the other ignores or dismisses as irrelevant |
| **Values/priorities conflict** | Both may be factually correct but prioritize different goals or criteria |
| **Talking past each other** | Arguments that don't actually engage — different topics framed as opposition |

Also identify **points of agreement** — claims where both documents align (these
exist more often than adversarial framing suggests).

Present as:

```
## Disagreement Map

### Points of Contention
1. **[Topic]** — Type: [category] — A says: [X] / B says: [Y]
2. ...

### Points of Agreement
1. **[Topic]** — Both agree: [X]
2. ...
```

---

## Step 4: Web research (verification-oriented)

Unlike `/challenge` (which searches adversarially), the mediator searches
**neutrally** to verify and contextualize claims from both sides.

Perform **4–6 targeted searches** covering:

1. **Fact-checking Document A's key claims:** Verify the evidence and sources
   cited. Are they real, current, and correctly interpreted?
   Example queries: `"[A's claim] evidence"`, `"[A's cited source] validity"`

2. **Fact-checking Document B's key claims:** Same verification for the other
   side.
   Example queries: `"[B's claim] evidence"`, `"[B's cited source] criticism"`

3. **Independent evidence on contested points:** For each direct contradiction,
   seek authoritative third-party sources that can adjudicate.
   Example queries: `"[contested topic] research 2025"`,
   `"[contested topic] meta-analysis"`, `"[contested topic] expert consensus"`

4. **Domain context:** Background that neither document may provide but that
   bears on the dispute.
   Example queries: `"[domain] best practices"`,
   `"[domain] state of the art"`, `"[domain] common misconceptions"`

For each search, use `WebFetch` to read the **1–2 most substantive results**.
Prioritise:
- Peer-reviewed research or systematic reviews
- Authoritative documentation and official sources
- Post-mortems and experience reports with concrete data
- Multiple independent sources corroborating the same finding

**Critical rules:**
- Do not fabricate sources. Every cited URL must be real and actually accessed.
- If verification finds nothing → state so explicitly and rely on logical
  analysis.
- If a document cites a source that turns out to be misrepresented or
  non-existent → flag this prominently.

---

## Step 5: Evaluate each contested point

For each point of contention identified in Step 3, apply this structured
evaluation:

### 5a. Steelman both sides

Before judging, construct the **strongest reasonable version** of each side's
argument on this point. This is mandatory — it counteracts confirmation bias
more effectively than simply trying to "be fair" (Mussweiler et al., 2000:
"consider the opposite" reduces anchoring bias significantly more than
neutrality instructions).

### 5b. Check for fallacies

Explicitly scan each side's argument on this point for:
- Straw man (misrepresenting the other side)
- Ad hominem (attacking the arguer, not the argument)
- False dilemma (presenting only two options)
- Appeal to authority (citing unqualified sources)
- Slippery slope (unsupported causal chains)
- Circular reasoning
- Equivocation (shifting meaning of key terms)
- Cherry-picking (selective evidence)

This step is explicitly required because LLMs have a documented **~43% miss
rate** on fallacy detection without structured prompting (CALM Framework, ICLR
2025).

### 5c. Assess evidence quality

For each side's evidence on this point, evaluate:
- **Source reliability:** Is the source authoritative, current, and free of
  obvious conflicts of interest?
- **Methodological quality:** How was the evidence generated? Is the methodology
  sound for the claim being made?
- **Relevance:** Does the evidence actually support the specific claim, or is it
  tangential?
- **Corroboration:** Is this a single source or corroborated by independent
  evidence?

Do NOT use a rigid evidence hierarchy (meta-analysis > RCT > observational).
Meta-epidemiological research shows **quality of execution matters more than
study design category**. Evaluate each source on its own merits.

### 5d. Assess logical validity

- Does the evidence actually support the claim via the stated or implied
  warrant?
- Are there logical gaps in the reasoning chain?
- Does the argument conflate correlation with causation?
- Are qualifiers appropriate to the evidence strength?

### 5e. Render per-point verdict

For each contested point, assign one of:

| Verdict | Meaning |
|---------|---------|
| **A is reasonable** | Document A's position on this point is well-supported; B's is not |
| **B is reasonable** | Document B's position on this point is well-supported; A's is not |
| **Both reasonable** | Both positions have merit; the disagreement reflects legitimate uncertainty, values difference, or scope difference |
| **Neither reasonable** | Both sides argue this point poorly — flawed logic or insufficient evidence on both sides |
| **Cannot adjudicate** | Insufficient domain expertise or available evidence to make a determination |

Each verdict MUST include:
- The explicit reasoning chain that led to it
- Which specific evidence or logical factors were decisive
- What would change the verdict (what evidence or argument would flip it)

---

## Step 6: Bias self-check

Before writing the final output, perform these checks (grounded in LLM-as-judge
bias research):

1. **Position bias:** Would the verdicts change if the documents were presented
   in reverse order? If any verdict feels order-dependent, flag it and
   re-examine.
2. **Verbosity bias:** Is a longer, more formally written document receiving
   favorable treatment over a shorter but equally substantive one? Discount
   length and style; judge substance only.
3. **Anchoring bias:** Is the first document's framing dominating how contested
   points are understood? Re-read Document B's framing independently.
4. **Epistemic humility:** For points marked "cannot adjudicate" — is this
   genuine uncertainty or avoidance of a difficult call? Make the call if the
   evidence supports it, even if marginal.

If any bias is detected, adjust the relevant verdicts and note the correction in
the output.

---

## Step 7: Produce the adjudication report

Use this exact output structure:

```
=== MEDIATION: <Document A title> vs <Document B title> ===
Sources: <path A> | <path B>

## Document A: Position Summary
[3–5 bullet summary]

## Document B: Position Summary
[3–5 bullet summary]

## Points of Agreement
[Numbered list of areas where both documents align]

## Adjudication of Contested Points

### 1. [Topic of contention]
**Type:** [Direct contradiction | Competing interpretation | Scope disagreement
| Values conflict | Talking past each other]

**Document A argues:** [steelmanned version]
**Document B argues:** [steelmanned version]

**Fallacies detected:** [None | list with explanation]

**Evidence assessment:**
- A's evidence: [quality evaluation]
- B's evidence: [quality evaluation]
- Independent findings: [what web research revealed]

**Verdict: [A is reasonable | B is reasonable | Both reasonable | Neither
reasonable | Cannot adjudicate]**
**Reasoning:** [explicit chain of logic]
**What would change this:** [reversibility condition]

### 2. [Next topic]
...

## Verdict Summary

| # | Topic | Verdict | Confidence |
|---|-------|---------|------------|
| 1 | ... | A is reasonable | High/Medium/Low |
| 2 | ... | Both reasonable | ... |
| ... | | | |

**Overall assessment:**
[Synthesize across all points. Which document's position is stronger overall?
Is the overall picture clear-cut or genuinely mixed? Are there patterns —
e.g., one document is factually stronger but the other raises valid concerns
the first ignores?]

**Key recommendation:**
[If the documents represent competing proposals or approaches — what should
the decision-maker do? Adopt A? Adopt B? Synthesize? Defer pending more
information?]

## Bias Self-Check
[Report any bias detected in Step 6 and corrections applied. If none detected,
state so briefly.]

## Sources
[All web sources actually cited, with URLs and a one-line summary of what each
contributed to the adjudication.]

## Methodology Note
This adjudication used Toulmin argument decomposition, per-point structured
evaluation (steelmanning, fallacy detection, evidence quality assessment,
logical validity), and explicit bias self-checks. Verdicts reflect the
available evidence and reasoning at time of analysis — not absolute truth.
Points marked "cannot adjudicate" indicate genuine epistemic limits.
```

---

## Step 8: Write the report to a file

### 8a. Determine the output folder

Always write mediation reports to `docs/development/challenges/`.

### 8b. Determine the output filename

Construct the filename from slugified document titles:

```
<slug-A>-vs-<slug-B>.mediation.md
```

Where slugification = lowercase, spaces/special chars → hyphens, collapse runs.

Example: `plan-a-vs-challenge-plan-a.mediation.md`

### 8c. Write the file

Write the full adjudication report (the output from Step 7) to `<output-folder>/<filename>`.

After writing, tell the user the path of the file that was written.

---

## Calibration

- **Always impartial.** The skill's job is to evaluate both sides with equal
  rigor. Never adopt either document's framing as the default lens.
- **Steelman first, judge second.** For every contested point, construct the
  strongest version of both arguments before rendering a verdict. This is not
  optional — it is the primary debiasing mechanism (empirically validated,
  d=0.89 effect size on argument quality).
- **Explicit reasoning chains.** Every verdict must contain the logical steps:
  "Because [evidence X] supports [claim Y] via [warrant Z], and [counter-
  evidence] is [weaker/absent/flawed] because [reason], therefore [verdict]."
- **Fact-backed.** Use web research to verify claims, not just to find more
  arguments. When verification is impossible, state so explicitly.
- **Substance over style.** A poorly written document with strong evidence
  outweighs an eloquent document with weak evidence. Do not let presentation
  quality influence verdicts.
- **Proportionate depth.** A dispute between two short idea sketches deserves
  concise treatment. A dispute between detailed plans with technical designs
  deserves thorough analysis with full research.
- **Honest uncertainty.** Use "cannot adjudicate" when genuinely warranted. But
  do not hide behind it — if the evidence leans one way, say so with
  appropriate qualifiers.
- **No fabricated sources.** If web research yields nothing, state that clearly.
  Never invent URLs, paper titles, or author names.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| `$ARGUMENTS` is empty | Ask the user what to mediate, **stop** |
| Only one document identified | Look for a `.challenge.md` pair; if none found, ask for the second document, **stop** |
| Multiple matches for either side | List matches, ask user to clarify, **stop** |
| Documents argue about completely different things | Note in the Disagreement Map that the documents are "talking past each other" on most points; adjudicate only genuine overlaps |
| One document is vastly more detailed | Note the asymmetry; evaluate each on substance, not volume; do not penalise brevity |
| Both documents are wrong on a point | Verdict: "Neither reasonable" — explain what the evidence actually shows |
| Documents are mostly in agreement | Report the agreement; focus adjudication on the genuine (possibly narrow) differences |
| A cited source turns out to be fabricated or misrepresented | Flag prominently; this significantly damages that claim's credibility |
| Domain is too specialized to evaluate | Use "Cannot adjudicate" with explanation; suggest what kind of domain expert could resolve it |
| Plan + its own challenge file (auto-pair) | Valid and expected — the most common use case |

---

## Important Constraints

- **Write output only:** This skill writes exactly one file — the adjudication
  report — and does NOT edit input files, create commits, or switch branches.
- **No implementation commentary:** Do not comment on code quality, naming,
  task granularity, or file organization. Stay at the conceptual and
  argumentation level.
- **Source honesty:** Every claim attributed to web research must have an actual
  URL that was fetched and read. Never invent sources.
- **Steelman mandatory:** Never misrepresent either side's position. Always
  evaluate the strongest reasonable interpretation of each argument.
- **Transparency:** The reasoning behind every verdict must be explicit and
  traceable. A reader should be able to disagree with a specific step in the
  reasoning chain, not just the conclusion.
