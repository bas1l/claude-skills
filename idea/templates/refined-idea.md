<!--
  Output of /idea. Fill {{PLACEHOLDERS}} and write to the ideas dir (docs/development/plans/ideas/<slug>.md
  or plans/ideas/<slug>.md). Keeps the plan-create Idea header (# Idea / Date / Status) so /plan-create
  can promote it, and adds the eight pinned characteristics as ready-made plan material.
-->

# Idea: {{TITLE}}

**Date:** {{DATE}}
**Status:** Idea
**Readiness:** {{OVERALL}}/32 ({{BEFORE}}→{{AFTER}} after refinement)

## Summary
{{ONE_PARAGRAPH_SUMMARY}}   <!-- outcome + why, plain language; this is what /plan-create reads first -->

## Refined characteristics
<!-- These map onto the plan template: Goal→Overview/Problem, Criteria→Success Criteria,
     Definitions→## Definitions, Architecture→### Architecture & Module Contracts, etc. -->

- **Goal & motivation:** {{GOAL}}
- **Success criteria:** {{CRITERIA}}
- **Definitions:** {{DEFINITIONS}}
- **Constraints & conventions:** {{CONSTRAINTS}}
- **Scope — in:** {{SCOPE_IN}}
- **Scope — out:** {{SCOPE_OUT}}
- **Steps (decomposition):** {{STEPS}}
- **Architecture / module impact:** {{ARCH_IMPACT}}
- **Risks & unknowns:** {{RISKS}}

## Open questions
<!-- Anything still weak after refinement — carry into planning, don't block on it. -->
{{OPEN_QUESTIONS}}

## Scorecard
```
{{SCORECARD}}
```

---
*Refined by `/idea`. Promote with `/plan-create` (it will use the Summary + characteristics above).*
