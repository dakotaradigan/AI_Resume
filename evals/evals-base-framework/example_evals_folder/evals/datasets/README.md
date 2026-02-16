# Datasets

Store sample interactions here for error analysis (Phase 1).

## Format
Each dataset should be a JSON or CSV file with at minimum:
- `input` — The user query or trigger
- `output` — The AI response
- `pass_fail` — Binary label (pass/fail)
- `critique` — Free-form explanation of what went wrong (for failures)

## Naming
`{date}_{description}.json` — e.g. `2025-01-15_initial_100_samples.json`
