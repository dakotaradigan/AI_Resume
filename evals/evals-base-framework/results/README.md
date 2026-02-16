# Results

Eval run outputs and historical scores live here.

## File Format: JSONL

All results use **JSONL** (one JSON object per line). Each run produces a
timestamped result file: `{date}_{run_description}.jsonl`

## Contents per Run
- Run-level summary (first line): overall pass rate, capability vs. regression split, config
- Task-level results (remaining lines): pass@k, pass^k, per-grader breakdown
- Per-criterion TPR and TNR (for LLM judge validation runs)
- Failure mode breakdown (which categories are failing most)
- Comparison to previous run (regression check)
- Transcript samples flagged for review

## Interpreting Results

**Capability evals:** Low pass rates are expected. Track improvement over time.
**Regression evals:** Pass rate should be near 100%. Any drop is urgent.
**Eval saturation:** If capability evals are >90% consistently, add harder tasks.
**0% pass rate on a task:** Likely a broken task, not an incapable agent.

## Naming
`{date}_{run_description}.jsonl` — e.g. `2025-01-15_pre-ship_5trials.jsonl`

## Reminder
These files are gitignored. They are generated artifacts and may contain
sensitive data. Do not commit without explicit approval.
