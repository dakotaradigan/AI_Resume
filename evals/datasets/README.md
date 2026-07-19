# Datasets

Test datasets live here. See `docs/EVALS_FRAMEWORK.md` (Phase 1.5) for the
full methodology on building datasets (5-category template, sizing, maturity).

## File Format: JSONL

One JSON object per line. Enables `wc -l` counting, `grep` filtering,
streaming, and clean git diffs.

## Naming
`{date}_{description}.jsonl` — e.g. `2026-01-15_initial_100_bootstrap.jsonl`

## Retrieval Golden Dataset

`retrieval_golden_v1.jsonl` uses one object per query:

```json
{"id":"retrieval_001","query":"What vector DB did Ben AI use?","expected_titles":["Ben AI: Intelligent Benchmark Assistant — Key Technical Features"],"category":"project_fact"}
```

- `id`: unique, stable case identifier
- `query`: recruiter-style search query
- `expected_titles`: one or more exact titles printed by `build_corpus`
- `category`: category used for per-category retrieval metrics

The dataset requires Dakota's review and sign-off before use. It remains
gitignored and must not be committed; only this schema documentation is tracked.

## Reminder
These files are gitignored. They may contain real user data / PII.
Do not commit without explicit approval and PII sanitization.
