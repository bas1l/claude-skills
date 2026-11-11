---
description: Clean up a messy/dictated (voice-to-text) prompt, then act on the cleaned version
argument-hint: <your dictated prompt>
---

The text below is a raw prompt captured via voice-to-text. It may contain
speech-recognition slips, translation errors, run-on phrasing, filler words,
and missing punctuation. Your job:

1. Reconstruct the user's actual intent. Correct obvious transcription errors
   (homophones, mis-split words, garbled technical terms). Use the surrounding
   context and this codebase's vocabulary to disambiguate — e.g. a garbled word
   near "pipeline" or "receptive field" is probably a term from this repo.
2. Rewrite it into one clean, well-structured request: clear objective, any
   constraints or acceptance criteria, and expected output/format if implied.
   Do not invent requirements that were not in the original — if something is
   genuinely ambiguous, note it briefly rather than guessing.
3. Print the cleaned prompt in one short block prefixed with **Cleaned prompt:**
   so the user can see how it was interpreted.
4. Then immediately act on the cleaned version — carry it out as if the user had
   typed the cleaned prompt directly. Do not wait for confirmation.

Exception: if a likely transcription error changes the meaning in a way that
would make you do substantially the wrong or irreversible thing, stop after
step 3 and ask one targeted question before acting.

Raw dictated prompt:
$ARGUMENTS
