# Results

Eval run outputs and historical scores live here. See
`docs/EVALS_FRAMEWORK.md` (Phase 3) for interpreting results.

## File Format: JSONL

All results use **JSONL** (one JSON object per line). Each run produces a
timestamped result file: `{date}_{run_description}.jsonl`

## Naming
`{date}_{run_description}.jsonl` — e.g. `2026-01-15_pre-ship_5trials.jsonl`

## Reminder
These files are gitignored. They are generated artifacts and may contain
sensitive data. Do not commit without explicit approval.
