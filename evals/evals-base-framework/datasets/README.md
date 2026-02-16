# Datasets

Test datasets live here. Built using the 5-category template from
EVALS_FRAMEWORK.md (Phase 1.5).

## File Format: JSONL

All datasets use **JSONL** (JSON Lines) — one JSON object per line.

Why JSONL:
- `wc -l` to count tasks
- `grep` to filter by category
- Append new tasks without rewriting the file
- Clean diffs in git
- Stream/process large datasets line-by-line

## 5 Required Categories
1. **Core Use Case Queries** (40-50%) — happy path, real usage
2. **Edge Cases** (15-20%) — vague, multi-part, ambiguous inputs
3. **Unanswerable / On-Topic** (10-15%) — system should say "I don't know"
4. **Off-Topic / Out of Scope** (5-10%) — system should stay in its lane
5. **Adversarial / Red-Team** (5-10%) — prompt injection, manipulation

## Per-Task Format (one line per task)
```jsonl
{"id":"core-001","category":"core_use_case","input":"How do I reset my password?","expected_behavior":"Returns correct reset steps","reference_solution":"Go to Settings > Security > Reset Password...","source":"synthetic","difficulty":"easy","notes":"Happy path baseline"}
```

**Required fields:** `id`, `category`, `input`, `expected_behavior`, `source`
**Recommended fields:** `reference_solution`, `difficulty`, `notes`

## Task Quality Requirements
- **Unambiguity Test:** Two domain experts should independently agree on pass/fail
- **Solvability:** Include a `reference_solution` for objective tasks. If you can't
  write one, the task may be ambiguous or impossible.
- **0% pass rate across many trials** = almost always a broken task, not a broken agent

## Dataset Maturity
- **Bootstrap** — 100% synthetic, pre-launch
- **Validate** — replacing synthetic with real production data
- **Evolve** — living dataset, continuously updated from production

## Naming
`{date}_{description}.jsonl` — e.g. `2025-01-15_initial_100_bootstrap.jsonl`

## Reminder
These files are gitignored. They may contain real user data / PII.
Do not commit without explicit approval and PII sanitization.
