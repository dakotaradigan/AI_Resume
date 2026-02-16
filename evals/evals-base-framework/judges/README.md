# Judges

LLM-as-judge prompts live here. One file per eval criterion.

## The 4-Part Formula + Escape Hatch

Each judge prompt file MUST contain:

1. **Role** — The evaluator persona ("You are an expert evaluator of...")
2. **Context** — Where app data gets injected (use `{{placeholder}}` syntax)
3. **Goal** — What pass vs. fail means, with concrete examples of each
4. **Grounding** — Definitions of key terms specific to this app
5. **Escape Hatch** — An "Unknown / Insufficient Information" option so the
   judge doesn't hallucinate a grade when it lacks context

## Judge Sub-Types

Choose the right sub-type for each criterion:

| Sub-Type                   | When to Use                                        |
|----------------------------|----------------------------------------------------|
| **Rubric-Based Scoring**   | Most common — tone, quality, completeness          |
| **Natural Language Assertions** | Checking specific claims (true/false)         |
| **Pairwise Comparison**    | A/B testing prompt changes                         |
| **Reference-Based**        | When you have gold-standard answers                |
| **Multi-Judge Consensus**  | High-stakes decisions, reducing individual bias    |

## Scoring

- **Simple tasks:** Binary pass/fail
- **Complex tasks:** Partial credit (0.0-1.0) or component-level binary (3/5 passed)

## Validation

Before deploying any judge:
1. Test against labeled data (TPR and TNR, not raw accuracy)
2. Read 10-20 graded transcripts to verify reasoning quality
3. Confirm the escape hatch works (judge says "Unknown" when info is missing)

## Naming
`judge_{criterion}.md` — e.g. `judge_hallucination.md`, `judge_tone.md`

## Template

```markdown
# Judge: [Criterion Name]

## Role
You are an expert evaluator specializing in [domain].

## Context
You will be given:
- {{user_input}}: The original user query
- {{agent_output}}: The AI system's response
- {{reference_data}}: [Any ground truth or context docs]

## Goal
Evaluate whether the response [specific criterion].

**Pass:** [Concrete description of what passing looks like, with example]
**Fail:** [Concrete description of what failing looks like, with example]
**Unknown:** If you do not have sufficient information to make a judgment,
respond with "Unknown" and explain what information is missing.

## Grounding
In this context, "[key term]" means [specific definition for this app].

## Output Format
Respond with a JSON object:
{
  "verdict": "pass" | "fail" | "unknown",
  "score": 0.0-1.0,  // optional, for partial credit
  "reason": "Brief explanation of your verdict"
}
```
