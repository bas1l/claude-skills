<!--
  The idea-readiness scale. Score each characteristic 0–4 against these rungs; ≤2 is "weak" and gets
  one targeted refinement question (use the `next:` hint to form it). Tunable — edit rungs here, not in
  SKILL.md. The characteristics deliberately mirror the plan-create template so a 4 maps onto a plan.
-->

# Idea-readiness scale (0–4 per characteristic)

## 1. Goal & motivation
- **0** absent — no goal stated
- **1** an activity named, no outcome ("work on the exporter")
- **2** outcome stated, no *why*
- **3** outcome **and** why
- **4** outcome + why in one crisp sentence, tied to a concrete trigger
- *next:* state the outcome and why it matters, in one sentence.

## 2. Success criteria
- **0** absent
- **1** implied only
- **2** stated but not measurable ("works well", "looks good")
- **3** at least one **measurable** criterion ("re-running reproduces identical images")
- **4** measurable + edge cases / explicit acceptance test
- *next:* state one measurable way we'll know it's done.

## 3. Definitions
- **0** load-bearing terms undefined
- **1** terms used, none defined
- **2** some defined, a key one still vague
- **3** every load-bearing term pinned
- **4** pinned **and testable** (e.g. *intact* = "re-run reproduces the exact outputs, plus the new ones")
- *next:* define the term the task hinges on, in testable words.

## 4. Constraints & conventions
- **0** none stated
- **1** vague ("keep it clean")
- **2** one real constraint named
- **3** hard limits stated + the relevant standing conventions
- **4** limits + specific `_code-conventions` named (config-driven, no hardcoding, agnostic layers)
- *next:* name the hard limits and any standing convention that applies.

## 5. Scope (in / out)
- **0** unbounded
- **1** in-scope only, and fuzzy
- **2** in-scope clear, nothing said about out-of-scope
- **3** in **and** out of scope both stated
- **4** in/out + explicit non-goals that prevent drift
- *next:* say what is explicitly OUT of scope.

## 6. Decomposition
- **0** one undifferentiated blob
- **1** implied ordering
- **2** a couple of steps sketched
- **3** discrete, ordered steps
- **4** ordered steps with dependencies noted
- *next:* break it into discrete, ordered points.

## 7. Architecture / module impact
- **0** unknown
- **1** "somewhere in the code"
- **2** an area/file named
- **3** modules named + what changes in each
- **4** modules + their boundaries ("must NOT know about") — ready to become Module Contracts
- *next:* name the modules touched and what each must not depend on.

## 8. Risks & unknowns
- **0** none considered
- **1** "might be tricky"
- **2** one risk named
- **3** key risks named
- **4** risks + the open unknowns to resolve first
- *next:* name the biggest risk or the key unknown to resolve first.

---
**Weak = ≤2** (gets a refinement question). **Plan-ready** ≈ all characteristics ≥3 (overall ≥24/32).
