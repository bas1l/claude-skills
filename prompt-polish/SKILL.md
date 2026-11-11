---
name: prompt-polish
description: Clean up a messy, dictated, or voice-to-text prompt into a clear structured request, then act on the cleaned version. Use when the user's message looks like an unpolished voice transcription (run-on phrasing, speech-recognition slips, translation errors, missing punctuation) or when they say things like "polish this", "clean this up", "fix my prompt", or dictate a request they want tidied before you act on it.
---

# Prompt polish

The user dictates prompts with voice-to-text. The transcription is often
unpolished and may contain speech-recognition slips, translation errors,
run-on phrasing, filler words, and missing punctuation. When this skill fires,
treat the user's raw message as the prompt to clean.

## Steps

1. **Reconstruct intent.** Correct obvious transcription errors — homophones,
   mis-split or merged words, garbled technical terms. Lean on the conversation
   context and this repository's vocabulary to disambiguate: a garbled word near
   "pipeline", "receptive field", "stroke axis", "GUI", etc. is almost certainly
   a term from this codebase.

2. **Rewrite** into one clean, well-structured request: a clear objective, any
   constraints or acceptance criteria, and the expected output/format if implied.
   Do not invent requirements that were not in the original. If something is
   genuinely ambiguous, note it in one line rather than silently guessing.

3. **Show it.** Print the cleaned prompt in a short block prefixed with
   **Cleaned prompt:** so the user sees how their dictation was interpreted.

4. **Act on it.** Immediately carry out the cleaned version as if the user had
   typed it directly. Do not wait for confirmation.

## Guardrail

If a likely transcription error changes the meaning in a way that would make you
do substantially the wrong thing or something irreversible (deleting files,
force-pushing, overwriting data), stop after step 3 and ask one targeted
clarifying question before acting.
