# Judges

LLM-as-judge prompts live here. One file per eval criterion. See
`docs/EVALS_FRAMEWORK.md` (Phase 2) for the full judge methodology.

## The 4-Part Formula + Escape Hatch

Each judge prompt file MUST contain:

1. **Role** — The evaluator persona ("You are an expert evaluator of...")
2. **Context** — Where app data gets injected (use `{{placeholder}}` syntax)
3. **Goal** — What pass vs. fail means, with concrete examples of each
4. **Grounding** — Definitions of key terms specific to this app
5. **Escape Hatch** — An "Unknown / Insufficient Information" option so the
   judge doesn't hallucinate a grade when it lacks context

## Naming
`{criterion}.md` — e.g. `groundedness.md`, `conciseness.md`

## Auto-Discovery
`run_judges.py` auto-discovers all `.md` files in this directory (excluding
README.md). Add a new judge by creating a file — no script changes needed.

## Template

```markdown
---
name: judge_name
description: one-line summary
applies_to: [core, edge_case]
needs_source_data: true
---

[ROLE]
You are an expert evaluator specializing in [domain].

[CONTEXT]
You will be given:
- The user's query
- The bot's response
- [Any source/reference data]

[GOAL]
Evaluate whether the response [specific criterion].

**Pass:** [Concrete description with example]
**Fail:** [Concrete description with example]
**Unknown:** If you do not have sufficient information to make a judgment,
respond with "unknown" and explain what information is missing.

[GROUNDING]
In this context, "[key term]" means [specific definition for this app].

Respond with ONLY this JSON (no other text):
{"verdict": "pass" or "fail" or "unknown", "reason": "one sentence explanation"}
```
