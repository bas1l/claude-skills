---
name: challenge
description: "Rigorous devil's advocate — argues against a plan, idea, or concept using logic, evidence, and web research to surface blind spots and missed perspectives"
allowed-tools:
  - Glob
  - Read
  - Grep
  - Write
  - WebSearch
  - WebFetch
---

# Challenge — Rigorous Opposition

This skill argues **against** the user's position. Its purpose is to broaden
the user's thinking, surface blind spots, and minimize missed perspectives by
constructing the strongest possible counter-arguments backed by logic, evidence,
and web research.

It **writes its analysis** to a file alongside the input file (no commits, no
branch changes).

It receives `$ARGUMENTS` which can be:
- A plan or idea name (matched against the plans directory)
- Free-text describing a concept to argue against

---

## Step 1: Locate the subject

Attempt to match `$ARGUMENTS` against existing plans and ideas using
**three-pass matching** (stop at first hit):

1. **Exact filename:** `$ARGUMENTS` matches a filename (with or without `.md`)
2. **Slug containment:** slugify `$ARGUMENTS` (lowercase, spaces/special chars
   → hyphens, collapse runs), check if any filename **starts with** or
   **contains** the slug
3. **Title search:** read `# Plan:` or `# Idea:` headings from files,
   case-insensitive substring match against `$ARGUMENTS`

Search order across directories:
- `docs/development/plans/ideas/`
- `docs/development/plans/pending/`
- `docs/development/plans/active/`
- `docs/development/plans/completed/`
- `docs/development/challenges/`

Rules:
- If `$ARGUMENTS` is **empty** → ask the user what to challenge, **stop**.
- If **multiple files** match → list the matches, ask the user to clarify,
  **stop**.
- If **exactly one** match → read the full file, proceed to Step 2.
- If **no match** → treat `$ARGUMENTS` as a **free-text concept** to argue
  against. Skip Step 2, go directly to Step 3 using `$ARGUMENTS` as the
  position.

---

## Step 2: Extract the position to oppose

Read the matched plan or idea and identify the position you will argue against.

For **ideas** (files in `ideas/`):
- **Thesis:** What the idea proposes (from `## Summary`)
- **Approach:** How it would work (from `## Rough Approach`)
- **Reasoning:** Why the author believes this is the right approach
- **Implicit assumptions:** Unstated beliefs the idea depends on

For **full plans** (files in `pending/`, `active/`, `completed/`):
- **Thesis:** The core claim — what is being built and why (from `**What:**`
  and `**Why:**` in Overview)
- **Problem claim:** The problem statement — is this problem real and
  significant?
- **Approach:** The chosen technical approach (from Technical Design)
- **Rejected alternatives:** What was considered and dismissed (from
  Alternatives Considered) — these are potential counter-arguments the plan
  already tried to defuse
- **Stated risks:** What the plan already acknowledges as risky
- **Implicit assumptions:** Unstated beliefs underpinning the design

Summarise these elements in 3–5 bullet points under the heading
`## Your Position` so the user can verify the interpretation is correct.

---

## Step 3: Web research for counter-positions

Use `WebSearch` to actively seek out evidence and logic that **undermines** the
user's position. Perform **3–5 targeted searches** covering different angles.
The research strategy must be **adversarial by design** — you are looking for
ammunition against the position, not neutral information.

**Search angles (select the most relevant):**

1. **Contradicting evidence:** Studies, data, or authoritative sources that
   directly oppose the thesis or show the problem is not real / not important.
   Example queries: `"[core claim] criticism"`,
   `"[problem domain] evidence against"`,
   `"[approach] doesn't work research"`

2. **Failed precedents:** Documented cases where this approach or similar ones
   failed, with analysis of why.
   Example queries: `"[technique] failure post-mortem"`,
   `"[approach] failed case study"`,
   `"why [approach] was abandoned"`

3. **Superior alternatives:** Approaches that solve the same problem better,
   with evidence of their superiority.
   Example queries: `"better alternative to [approach]"`,
   `"[problem domain] state of the art 2025"`,
   `"[approach] vs [alternative] comparison"`

4. **Hidden costs and second-order effects:** Non-obvious consequences the
   position ignores — maintenance burden, technical debt, scalability walls.
   Example queries: `"[approach] hidden complexity"`,
   `"[technique] long-term problems"`,
   `"[approach] unintended consequences"`

5. **Opposing expert viewpoints:** Domain experts who argue the opposite.
   Example queries: `"[domain] expert criticism [approach]"`,
   `"[approach] skepticism"`,
   `"against [technique] [domain]"`

For each search, use `WebFetch` to read the **1–2 most substantive results** in
full. Prioritise:
- Peer-reviewed papers or well-established technical references
- Post-mortems and experience reports with concrete data
- Authoritative documentation that contradicts assumptions

**Critical rule:** Do not fabricate sources. If a search yields nothing relevant
for a particular angle, say so and rely on logical argumentation instead. Every
cited URL must be real and actually support the claim made.

---

## Step 4: Build the opposition

Construct a structured counter-argument. Every challenge must meet this quality
bar:

- **Supported:** Every claim backed by either explicit logical reasoning OR a
  factual source with URL. No unsupported assertions.
- **Specific:** No vague "have you considered the risks?" — concrete
  counter-claims with evidence or logical chain.
- **Steel-manned:** Present the **strongest possible version** of each
  counter-argument, not a strawman. If there is a weaker and a stronger way to
  make the same point, always choose the stronger one.

Use this exact output structure:

```
=== CHALLENGE: <Title or concept> ===
Source: <plan path | idea path | "free-text concept">

## Your Position

[3–5 bullet summary of the user's position for verification]

## Opposition

### 1. The problem may be misdiagnosed

[Argue that the problem as framed is wrong, exaggerated, or a symptom of
something deeper. Present evidence that the real problem lies elsewhere, or
that the problem's importance is overstated. Build a logical case for why
the framing is flawed.]

### 2. Critical assumptions that may not hold

[Identify 2–3 load-bearing assumptions the position depends on. For each:
- State the assumption explicitly
- Present evidence or reasoning why it could be false
- Explain what breaks if it is false
These should be assumptions the user hasn't explicitly defended.]

### 3. Stronger alternatives exist

[Present 1–3 alternative approaches with evidence of their merit. For each:
- What is the alternative?
- What evidence supports it? (cite sources)
- What specifically does the current approach sacrifice compared to it?
If the plan already rejected alternatives, argue why that rejection was
premature or based on incomplete information.]

### 4. What this position ignores

[Surface blind spots: risks, failure modes, second-order effects, stakeholder
perspectives, or domain knowledge the position doesn't account for. These
should be things genuinely absent from the plan/idea, not restating known
risks. Back with evidence where possible.]

### 5. The strongest case against

[Synthesize the single most compelling reason this position is wrong or
misguided. This should be the hardest point to refute. Build it from the
best evidence and strongest logic found across all research. This is the
one argument that, if the user cannot answer, should give them genuine
pause.]

## Sources

[List all web sources actually cited above, with URLs and a one-line
summary of what each contributed to the opposition.]

## Assessment

[Honest verdict on the opposition's strength:
- If the challenges are devastating → say so clearly
- If the position holds up well → acknowledge it, but note which specific
  challenges still deserve attention
- Rate overall: "strong opposition" / "moderate concerns" / "position is
  robust — challenges are secondary"
This must be genuinely honest, not artificially balanced.]
```

---

## Step 5: Write the analysis to file

After producing the challenge output, **write the full analysis to a file** in
the same directory as the input file.

**File naming:**
- If the input was a plan/idea file like `my-plan.md`, write to
  `my-plan-challenge.md` in `docs/development/challenges/`.
- If the input was a **free-text concept** (no file match), write to
  `<slugified-concept>-challenge.md` in `docs/development/challenges/`.

**File content:** The complete output from Step 4 (everything inside the
`=== CHALLENGE ===` structure), written as-is — no additional wrapper or
frontmatter.

**Rules:**
- If a `.challenge.md` file already exists at that path, **overwrite it** with
  the new analysis.
- Inform the user where the file was written.

---

## Calibration

- **Always oppose.** The skill's job is to argue against the position, even
  when it is strong. Find the best counter-arguments available. A weak
  challenge against a strong idea is still valuable — it builds confidence.
- **Logic first.** Every challenge must contain explicit reasoning chains, not
  just "what if X?" Present the logical steps: "If A, then B, therefore C is
  a problem because D."
- **Fact-backed.** Use web research to ground arguments in reality, not
  speculation. When evidence is unavailable, make the logical argument
  explicitly and note the absence of empirical data.
- **Conceptual level only.** Challenge the *why* and the *what*, never the
  *how*. Do not comment on implementation details, code patterns, task
  checklists, naming conventions, or phase ordering. That is `plan-review`'s
  job.
- **Proportionate depth.** A one-paragraph idea in `ideas/` deserves a focused
  challenge (2–3 tight paragraphs). A detailed plan with Technical Design and
  Alternatives Considered deserves thorough opposition with full research.
- **Acknowledge existing defences.** If the plan's Risks section or Alternatives
  Considered already addresses a concern, say: "The plan acknowledges this but
  the defence is insufficient because..." — don't pretend the author didn't
  think of it.
- **No fabricated sources.** If web research yields nothing for an angle, state
  that clearly. Never invent URLs, paper titles, or author names.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| `$ARGUMENTS` is empty | Ask the user what to challenge, **stop** |
| Multiple plan/idea matches | List matches, ask user to clarify, **stop** |
| Very short idea (< 5 lines of content) | Treat as free-text concept, note the file exists but is too sparse to analyse structurally |
| Plan in `completed/` | Still valid — post-hoc opposition can surface lessons learned |
| Web search yields nothing for an angle | State no counter-evidence was found, rely on logical argumentation for that section |
| Vague free-text concept | Ask one clarifying question to sharpen the position, then oppose |
| Position seems obviously correct | Find the best opposition anyway — that is the skill's entire purpose. Note in Assessment that the position is robust. |
| Plan already has extensive Risks/Alternatives | Build on those — argue the mitigations are insufficient or the rejected alternatives were dismissed prematurely |

---

## Important Constraints

- **Write-only to challenge files:** This skill only writes `.challenge.md`
  files. It does NOT edit existing plan/idea files, create commits, or switch
  branches.
- **No implementation commentary:** Do not comment on code quality, naming,
  task granularity, or file organization. Stay at the conceptual level.
- **Source honesty:** Every claim attributed to web research must have an actual
  URL. Never invent sources. If research finds nothing, say so explicitly.
- **Steel-man only:** Never misrepresent the user's position to make it easier
  to attack. Always argue against the strongest interpretation of their idea.
