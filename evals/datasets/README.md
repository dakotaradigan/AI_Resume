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

Dakota reviewed and approved retrieval v1 on 2026-07-19 for its original
25-chunk corpus. Any edit to v1 or any replacement dataset requires renewed
review and sign-off before it is run. The source corpus has since grown to 26
chunks, so the original results are historical until the approved dataset is
rerun against the current corpus.

The dataset remains gitignored and must not be committed; only this schema
documentation is tracked.

## Reminder
These files are gitignored. They may contain real user data / PII.
Do not commit without explicit approval and PII sanitization.
