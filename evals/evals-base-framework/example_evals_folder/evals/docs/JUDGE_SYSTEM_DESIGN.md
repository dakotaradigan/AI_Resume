# Judge System Design

> Design decisions for the LLM-as-Judge evaluation pipeline.
> Reference: EVALS_FRAMEWORK.md (4-part formula), CORE_MENTAL_MODEL.md (TPR/TNR validation) — both in this directory

---

## Architecture Overview

```
evals/results/eval_run_*.jsonl     (bot responses from run_eval.py)
        │
        ▼
evals/scripts/run_judges.py        (sends responses to judge LLMs)
        │
        ├── reads judges/groundedness.md
        ├── reads judges/conciseness.md
        └── reads judges/redirect_behavior.md
        │
        ▼
evals/results/judge_run_*.jsonl    (judge verdicts: pass/fail + reason)
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
2. **Auto-discovery** — run_judges.py reads all .md files in judges/ (excluding README.md). Add a new judge by creating a file, no script changes needed.
3. **Selective execution** — `--judge groundedness` runs just one judge
4. **JSONL everywhere** — consistent format across the entire pipeline
5. **No over-engineering** — no database, no web UI, no parallel execution. Scripts and files.

---

## Judge Prompt Format

Each judge file has YAML frontmatter + the 4-part system prompt:

```markdown
---
name: groundedness
description: Checks that all claims trace back to source data
applies_to: [core, edge_case]
needs_source_data: true
---

[ROLE]
You are an expert evaluator...

[CONTEXT]
You will receive...

[GOAL]
Your task is to determine...

[GROUNDING]
In this context, "grounded" means...
```

### Frontmatter fields:
- **name**: Judge identifier (used in output and --judge flag)
- **description**: One-line summary
- **applies_to**: Which test case categories this judge runs on.
  A groundedness check on an adversarial prompt injection is meaningless.
  This prevents wasted API calls and noisy results.
- **needs_source_data**: If true, resume.json is included in the judge context.
  Groundedness needs it (to verify claims). Conciseness doesn't.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Judge model | Claude Haiku | Fast (~0.5s), cheap (~$0.01/100 calls), sufficient for binary pass/fail |
| Output format | JSONL | Consistent with run_eval.py output |
| Source data | resume.json loaded once, passed to judges that need it | Avoids redundant file reads |
| Judge scope | Filter by category when available; run all when no category exists | Works for both synthetic (categorized) and production (uncategorized) data |
| Concurrency | Serial | 300 calls with Haiku takes ~3 min. Not worth the complexity of async. |
| Error handling | Log and skip | If one judge call fails, don't abort the run |

---

## Which Judges and Why

Starting with 3 judges mapped to the actual failure modes from Phase 1:

| Judge | Failure Mode | Priority | Why This One |
|---|---|---|---|
| groundedness | Hallucinated experience | P0 | One fabricated claim kills credibility |
| conciseness | Too verbose | P1 | #1 failure by count (35+ failures). Also drives latency. |
| redirect_behavior | Doesn't redirect properly | P1 | Covers adversarial + unanswerable + off-topic handling |

### Judges NOT built yet (and why):
- **completeness** — Only 8 failures. Fix the data gaps first (todo 032), then re-eval.
- **tone** — Only 2 failures (emoji). Low priority, not worth a judge yet.

Per the framework: "Start from real user failures, not industry buzzwords."

---

## Validation Process

After judges produce verdicts, validate_judges.py compares to human labels:

```
For each judge:
  TPR = (human=pass AND judge=pass) / (human=pass)
  TNR = (human=fail AND judge=fail) / (human=fail)
```

Our error tolerance is conservative → **prioritize TNR** (catch every failure).

Target: TNR > 80%, TPR > 85%

If a judge doesn't meet thresholds, iterate on the prompt using the dev set.

### Data split (per framework):
- Train (10-20%): Examples baked into judge prompts as few-shot examples
- Dev (40-45%): Iterate prompt refinement
- Test (40-45%): Final untouched validation

---

## Scripts Summary

```bash
# Step 1: Run queries against the bot (already exists)
python evals/scripts/run_eval.py

# Step 2: Generate Excel for human review (already exists)
python evals/scripts/build_review_xlsx.py

# Step 3: Parse human-reviewed Excel (already exists)
python evals/scripts/parse_review.py

# Step 4: Run judges against bot responses
python evals/scripts/run_judges.py                    # all judges
python evals/scripts/run_judges.py --judge groundedness # one judge

# Step 5: Validate judges against human labels
python evals/scripts/validate_judges.py
```

---

## Cost Estimate

100 responses × 3 judges = 300 Haiku calls
~500 tokens per call (prompt + response)
≈ 150k tokens total
≈ $0.04 per full judge run

Cheap enough to iterate frequently.
