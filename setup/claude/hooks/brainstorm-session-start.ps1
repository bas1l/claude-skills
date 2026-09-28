# SessionStart hook — nudges the brainstorm skills on new-generation openers.
# Its stdout is injected into the session context. The condition is evaluated by the model
# against the user's first message; it self-gates, so it is harmless on resume/compact.
Write-Output @'
[brainstorm trigger] If the user's FIRST substantive request this session is about creating, generating, or building something NEW (a feature, script, document, tool, analysis, or plan) AND the idea is not already fully specified, offer to brainstorm it first, before planning or coding. Two modes exist — ask which the user prefers (or use whichever they name):
  - `/brainstorm-conversation` — free-flowing, generative back-and-forth that widens the space and stress-tests whether the stated goal is the one they really want.
  - `/brainstorm-interview` — the same maturation, but as a structured, question-led walk through exploration dimensions.
Skip entirely (do not offer) when the request is a fix, a question, a trivial edit, or already carries a complete specification. Never let it become ceremony on a well-formed ask.
'@
