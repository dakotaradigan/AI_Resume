# Scripts

Eval runner scripts and code-based graders live here. See
`docs/EVALS_FRAMEWORK.md` (Phase 2) for the full grader taxonomy.

## Naming
- `run_eval.py` — Main eval runner (sends queries to bot, collects responses)
- `run_retrieval_eval.py` — Hybrid-retrieval evaluator (hit-rate@k, recall@k,
  MRR, per-category results, and misses against an approved golden dataset)
- `run_judges.py` — LLM judge executor (auto-discovers judges, runs them on responses)
- `build_review_xlsx.py` — Generate Excel for human review
- `parse_review.py` — Parse human labels from Excel back to JSONL
- `validate_judges.py` — Compare judge verdicts to human labels (TPR/TNR)
- `eval_{criterion}.py` — Individual code-based graders (as needed)

`run_retrieval_eval.py` is operationally stateful: it initializes an isolated
eval-prefixed collection, may rewrite that collection on corpus drift, spends
embedding calls, and writes an ignored result file. It refuses the production
`resume` collection. Run it only with owner approval for the dataset revision
and configure `EVAL_QDRANT_URL`/`EVAL_QDRANT_API_KEY` for a separate
non-production target. The runner never falls back to the app's Qdrant
credentials and rejects a matching app/eval URL.

## Output Format: JSONL

All eval results use **JSONL** — one JSON object per line. This enables
streaming, appending, and clean git diffs.

## Implementation Patterns

### Auto-Discovery
Judges live as standalone `.md` files with YAML frontmatter. The runner
discovers them at runtime via glob — no registration step needed.

### Category Filtering
Judge frontmatter includes an `applies_to` list. The runner checks whether
a judge should run on each case based on the test case's category.

### Incremental JSONL Write
Write each verdict to disk immediately after receiving it, rather than
accumulating results in memory and writing at the end. Crash-safe.
