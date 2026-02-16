# Judge System Design

> Design decisions for the LLM-as-Judge evaluation pipeline.
> Reference: EVALS_FRAMEWORK.md (4-part formula), CORE_MENTAL_MODEL.md (TPR/TNR validation)
>
> **This is a template.** Copy to your evals directory and fill in all `[TAILOR]` sections.

---

## Architecture Overview

```
evals/results/eval_run_*.jsonl     (bot responses from eval runner)
        │
        ▼
evals/scripts/run_judges.py        (sends responses to judge LLMs)
        │
        ├── reads judges/[TAILOR: judge_1].md
        ├── reads judges/[TAILOR: judge_2].md
        └── reads judges/[TAILOR: judge_3].md
        │
        ▼
evals/results/judge_run_*.jsonl    (judge verdicts: pass/fail/unknown + reason)
        │
        ▼
evals/scripts/validate_judges.py   (compares judge verdicts to human labels)
        │
        ▼
stdout: TPR/TNR per judge + disagreement details
```

---

## Design Principles

1. **One file does one thing** — each judge is a standalone .md system prompt
2. **Auto-discovery** — the judge runner reads all .md files in judges/ (excluding README.md). Add a new judge by creating a file, no script changes needed.
3. **Selective execution** — run just one judge by name when iterating
4. **JSONL everywhere** — consistent format across the entire pipeline
5. **No over-engineering** — no database, no web UI, no parallel execution. Scripts and files.

---

## Judge Prompt Format

Each judge file has YAML frontmatter + the 4-part system prompt + escape hatch:

```markdown
---
name: [TAILOR: judge name]
description: [TAILOR: one-line summary]
applies_to: [TAILOR: list of test case categories this judge runs on]
needs_source_data: [TAILOR: true if judge needs access to source/reference data]
---

[ROLE]
You are an expert evaluator...

[CONTEXT]
You will receive...

[GOAL]
Your task is to determine...

[GROUNDING]
In this context, "[TAILOR: term]" means...

[ESCAPE HATCH]
If you cannot make a confident judgment, return "unknown".
```

### Frontmatter fields:
- **name**: Judge identifier (used in output and --judge flag)
- **description**: One-line summary
- **applies_to**: Which test case categories this judge runs on.
  [TAILOR: explain why some judges don't apply to all categories in your domain]
  This prevents wasted API calls and noisy results.
- **needs_source_data**: If true, source/reference data is included in the judge context.
  [TAILOR: which judges need source data and which don't, and why]

### Output format:
```json
{"verdict": "pass" | "fail" | "unknown", "reason": "one sentence explanation"}
```

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Judge model | [TAILOR: model name] | [TAILOR: speed/cost/quality tradeoff for your use case] |
| Output format | JSONL | Consistent with eval runner output |
| Source data | [TAILOR: how source/reference data is loaded and passed to judges] | Avoids redundant file reads |
| Judge scope | Filter by category when available; run all when no category exists | Works for both synthetic (categorized) and production (uncategorized) data |
| Concurrency | [TAILOR: serial or async, based on volume] | [TAILOR: rationale — serial is fine for <500 calls with fast models] |
| Error handling | Log and skip | If one judge call fails, don't abort the run |

---

## Which Judges and Why

[TAILOR: Map judges to actual failure modes from Phase 1. Start with 2-4 judges covering your highest-priority failure modes.]

| Judge | Failure Mode | Priority | Why This One |
|---|---|---|---|
| [TAILOR] | [TAILOR] | P0 | [TAILOR: why this failure mode is critical] |
| [TAILOR] | [TAILOR] | P1 | [TAILOR: why this failure mode matters] |
| [TAILOR] | [TAILOR] | P1 | [TAILOR: why this failure mode matters] |

### Judges NOT built yet (and why):
[TAILOR: List failure modes that don't warrant a judge yet and explain why. Common reasons: too few failures, fix the root cause first, low severity.]

Per the framework: "Start from real user failures, not industry buzzwords."

---

## Validation Process

After judges produce verdicts, validate by comparing to human labels:

```
For each judge:
  TPR = (human=pass AND judge=pass) / (human=pass)
  TNR = (human=fail AND judge=fail) / (human=fail)
```

[TAILOR: State your error tolerance stance]
- High-stakes → **prioritize TNR** (catch every failure, tolerate false alarms)
- Creative → **prioritize TPR** (don't over-reject good outputs)

Target: TNR > [TAILOR]%, TPR > [TAILOR]%

If a judge doesn't meet thresholds, iterate on the prompt using the dev set.

### Data split (per framework):
- Train (10-20%): Examples baked into judge prompts as few-shot examples
- Dev (40-45%): Iterate prompt refinement
- Test (40-45%): Final untouched validation

---

## Scripts Summary

[TAILOR: List your actual scripts and their purposes]

```bash
# Step 1: Run queries against the app
python evals/scripts/run_eval.py

# Step 2: [TAILOR: human review workflow if applicable]

# Step 3: Run judges against responses
python evals/scripts/run_judges.py

# Step 4: Validate judges against human labels
python evals/scripts/validate_judges.py
```

---

## Cost Estimate

[TAILOR: Calculate based on your dataset size and judge count]

```
[TAILOR: N] responses × [TAILOR: M] judges = [TAILOR: N×M] judge calls
~[TAILOR] tokens per call (prompt + response)
≈ [TAILOR] tokens total
≈ $[TAILOR] per full judge run
```

[TAILOR: Note whether this is cheap enough to iterate frequently or requires batching]
