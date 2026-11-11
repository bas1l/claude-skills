# Literature search: Consensus as the default finder

Loaded with any Introduction, state-of-the-art or Discussion task, and by the missing-citation
sweep (`references/citation-verification.md` section 5). Basil does not name the tool: the
writing need triggers the search. The rules on what may be cited stay in `references/global.md`
section 4 and `references/sections/state-of-the-art.md` section 7.

## 1. When to search, without being asked

Search before writing or keeping any sentence of these kinds:

- **Background claim** about the field ("CT afferents respond best to 1 to 10 cm/s stroking")
  that has no citation, or whose citation was not read.
- **Gap or novelty claim** ("little research has examined", "to our knowledge, no study"): the
  search is the documented search of `references/sections/state-of-the-art.md` section 5.
- **Strand of prior work** the state of the art positions, when the strand has fewer than two
  read sources, or none from the last five years (`state-of-the-art.md` section 6).
- **Comparison with prior work** in the Discussion (`references/sections/discussion.md`
  section 2, item 3): one search per finding compared, for agreeing and for conflicting results.
- **Alternative explanation** in the Discussion (item 4) that rests on a published mechanism.
- **Missing citation** flagged MUST or SHOULD by the sweep.

Do not search for the project's own methods, numbers or results, or for claims already backed by
a read source.

## 2. How

- Load the tool first: `ToolSearch` with `select:mcp__consensus__search` (it is deferred). A
  teammate or subagent loads it itself; MCP tools are not passed down by the brief.
- Plain-language query, one claim per query, phrased as the question the sentence answers
  ("does C-tactile afferent firing depend on stroking velocity"). For conflicting evidence, a
  second query phrased the other way.
- At most 3 searches in parallel; on a rate-limit error, wait 30 s and retry.
- No filters (year, study type, sample size) unless Basil asks, or the recency rule of
  `state-of-the-art.md` section 6 needs one.
- If the tool is missing or fails after the retry, stop and say so. Do not fall back silently to
  web search; Basil decides whether a web search replaces it.

## 3. What a hit is worth

- A Consensus result is **snippet-level**: title, abstract and metadata. It finds the paper; it
  does not license the citation. Before citing, read the full text (section 7 of
  `state-of-the-art.md`) or mark it snippet-only under `global.md` section 4.
- Verify the DOI via Crossref before it enters a reference list.
- Record each search in the notes: date, query, number of hits screened, papers kept and why.
  This record is the documented search a gap or "first" claim needs.
- In chat, cite hits inline as [1], [2] with the exact URLs the tool returned, and relay the
  tool's sign-up or usage message word for word at the end of the reply.
