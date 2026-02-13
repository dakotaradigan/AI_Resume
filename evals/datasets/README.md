# Datasets

Test datasets live here. See `docs/EVALS_FRAMEWORK.md` (Phase 1.5) for the
full methodology on building datasets (5-category template, sizing, maturity).

## File Format: JSONL

One JSON object per line. Enables `wc -l` counting, `grep` filtering,
streaming, and clean git diffs.

## Naming
`{date}_{description}.jsonl` — e.g. `2026-01-15_initial_100_bootstrap.jsonl`

## Reminder
These files are gitignored. They may contain real user data / PII.
Do not commit without explicit approval and PII sanitization.
