# Judges

LLM-as-judge prompts live here. One file per eval criterion.

## Format
Each judge prompt file should contain:
1. **Role** — The evaluator persona
2. **Context** — Where app data gets injected (use `{{placeholder}}` syntax)
3. **Goal** — What pass vs. fail means
4. **Grounding** — Definitions of key terms for this app

## Naming
`judge_{criterion}.md` — e.g. `judge_hallucination.md`, `judge_tone.md`
