<!--
  arch-diff legend & color convention.
  Paste the `classDef` block into every delta diagram, then tag nodes with `:::added` / `:::changed`
  / `:::removed` (untagged nodes read as unchanged). Style changed/removed EDGES with linkStyle.
  Colors are chosen to read in Mermaid's default light theme and stay distinguishable for CVD
  (green/amber/red also differ in lightness; removed is additionally dashed, so it never relies on
  color alone).
-->

**Legend** — 🟩 added · 🟨 changed · 🟥 removed (dashed) · ⬜ unchanged

```
%% --- paste this classDef block at the bottom of each delta flowchart ---
classDef added    fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d;
classDef changed  fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f;
classDef removed  fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#7f1d1d,stroke-dasharray:5 3;
classDef same     fill:#f1f5f9,stroke:#94a3b8,stroke-width:1px,color:#334155;
```

Usage inside a diagram:

```
flowchart LR
  loader[loader]:::same --> mapper[reference_mapper]:::changed
  mapper --> exporter[rf_exporter]:::added
  mapper -. removed .-> legacy[old_writer]:::removed
  linkStyle 2 stroke:#dc2626,stroke-dasharray:5 3;   %% the removed edge
classDef added   fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d;
classDef changed fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f;
classDef removed fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#7f1d1d,stroke-dasharray:5 3;
classDef same    fill:#f1f5f9,stroke:#94a3b8,stroke-width:1px,color:#334155;
```

Boundary risk: if a planned edge would violate a module's **"must NOT know about"** contract, color it
red and add a comment line `%% ⚠ boundary risk: <module> must not know about <thing>`.
