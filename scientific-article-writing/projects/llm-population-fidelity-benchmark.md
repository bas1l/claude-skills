# Project profile: LLM demographic-fidelity benchmark

"Can LLMs Synthesise Realistic National Populations?" Primary venue PLOS ONE, TMLR backup
(decided 2026-08-28). Grid swedish_02: 13 models x 5 strategies, 58 combinations analysed,
100 individuals each; reference sampled from Statistics Sweden (SCB).

## Locations

- **MF (manuscript folder)**:
  `F:\liu-onedrive-nospecial-carac\_Teams\Gauss\04_Dissemination\Manuscripts\40_llm-population-fidelity-benchmark\`
  (same folder as `F:\OneDrive - Linköpings universitet\_Teams\Gauss\04_Dissemination\Manuscripts\40_llm-population-fidelity-benchmark\`).
- **Repo**: `F:\GitHub\clinical_projects\population-synthetic\`.
- **Analysis outputs**: `F:\liu-onedrive-nospecial-carac\_Teams\Gauss\02_Data\03_Analysis\` (read
  from repo config `output_base`; never write there without approval, same for `04_Figures\`).
- **Python**: `D:/Programming/anaconda3/envs/popsynth/python.exe`, run with
  `PYTHONIOENCODING=utf-8` (non-ASCII paths and labels break the Windows console otherwise).

## Authorities, highest first (read, do not duplicate)

1. `MF\CLAUDE.md`: folder layout, backup-before-regenerate, closed figure set, never renumber silently.
2. `MF\WRITING-TONE-RULES.md`, `MF\TERMINOLOGY-RULES.md`, `MF\DOCUMENT-FORMAT-RULES.md`,
   `MF\FIGURE-CAPTION-RULES.md` (caption and layout rules, R23: 456 pt display width).
3. `MF\analysis-notes\results-docx-drafting-strategy.md`: the detailed procedure for one block's
   methods and results docx (sentence order, notation, checks).
4. `MF\analysis-notes\manuscript-red-line_2026-08-17.md`: target structure; with
   `results-derivation-ladder_2026-08-14.md` and `manuscript-skeleton_2026-08-14.md` beside it.
5. Terminology checker: `MF\analysis-notes\check_terms.py <file>`.

The humanizer pass is the `humanizer_academic` skill (`C:\Users\basil\.claude\skills\humanizer_academic\SKILL.md`).

MF has its own skills in `MF\.claude\skills\` (`sync-skeleton`, `absorb-review`,
`interview-section`, `draft-node`); `MF\automated\` belongs to the repo's `/sync-manuscript`
skill. Never put drafts there.

## Figures

- Presentation layer: `F:\GitHub\clinical_projects\population-synthetic\src\population_synthetic\analysis\utils\`
  (`style.py`, `palette.py`, `labels.py`, `figures.py`, `grids.py`, `grid_annotations.py`,
  `table_style.py`, `glyph_grid.py`; model order in `model_order.py`, withdrawals in `cap_index.py`).
- Conventions: `F:\GitHub\clinical_projects\population-synthetic\docs\development\figure-conventions.md`
  and the repo `CLAUDE.md` section "Presentation computes nothing".
- Width 456 pt; Arial 8 to 12 pt; single inferno ramp; no `alpha=`; model order = published
  model_ranking order (Kimi K3 first); models as columns, strategies A to E as rows, reference in
  a detached column; model names above the grid at 90 degrees, host-tinted.
- Staged figures: `MF\figures selection\` with `SOURCES.md` (provenance) and `captions\` (caption
  `.md` files, and the docx drafts beside them).
- Gallery index: `MF\figure-galleries.md` (every gallery page with absolute path, date, session,
  choice). Update it whenever a gallery is made or a choice is taken.
- Examples of a finished gallery round: typicality P20 (`typicality_distribution_by_model_strategy`),
  severity P19 (`severity_worst_clash_by_model_strategy`); both recorded in `figure-galleries.md`.

## Text

- Docx toolkit: `MF\analysis-notes\docx-toolkit\_helpers.py` and
  `MF\analysis-notes\docx-toolkit\example_build_population_methods.py`. Copy both next to the
  output, adapt the copy; copy an improved `_helpers.py` back into `docx-toolkit\`.
- Style template docx: `MF\F11-method-anova-results-draft.docx`. Style model article for the
  order of statistical sentences: `F:\OneDrive - Linköpings universitet\Zotero\Duvernoy et al. - 2021 - Numerosity Identification Used to Assess Tactile Stimulation Methods for Communication.pdf`.
- Skeleton he pastes into: `MF\manuscript-skeleton.docx` (never write to it unless asked;
  `manuscript-skeleton_NEW_<date>.docx` is a pending build, see `MF\CLAUDE.md`).
- LaTeX: `MF\latex\` (a separate later step, compiled to `MF\latex\main.pdf`).
- Backups: `MF\backup\<name>_YYYY-MM-DD_HHMM.docx`.
- Reviewed examples showing his trim: `MF\figures selection\captions\typicality_distribution_by_model_strategy.results-reviewed-0 2.docx`
  (the name really contains a space) and
  `MF\figures selection\captions\severity_worst_clash_by_model_strategy.methods-results-discussion-draft.reviewed.docx`.

## Article-specific decisions

- Terms: individual (never persona), strategy (never method, for A to E), attribute (never
  category), reference (never ground truth), fourteen attributes from thirteen SCB tables.
  Display names only; strategies as "strategy E" in prose.
- Docx form: A4, Cambria, 11 pt body, 9.5 pt captions, justified body, booktabs tables, OMML
  equations numbered continuously, no Word comments, author property "Basil Duvernoy".
- Statistics notation: *F*(4, 36) = 189.49, *p* < 1.2 x 10^-23 (*eta*^2p = 0.95) with italic symbols,
  true minus, leading zero, no "e-" notation (exact forms in the drafting-strategy file).
- Known open conflicts to state in the notes, never resolve silently: red-line versus live
  skeleton numbering; figure citations in prose; "where" after equations; equation layout;
  TV similarity versus TV-similarity; retained versus valid individuals; clash-severity naming
  (atypicality rank, A1 to A3, S1 to S3; "near-impossible" versus "implausible"); CI format.
