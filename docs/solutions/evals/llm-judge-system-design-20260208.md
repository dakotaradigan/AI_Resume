# LLM-as-Judge System for Resume Assistant Evals

---
title: LLM-as-Judge System for Resume Assistant Evals
category: evals
tags:
  - llm-as-judge
  - eval-pipeline
  - claude-haiku
  - auto-discovery
module: evals
symptoms:
  - "Need automated quality checks on bot responses"
  - "Manual review doesn't scale for every deploy"
  - "Want to catch regressions before they hit production"
---

## Problem

After Phase 1 error analysis (100 synthetic queries, 58 failures), we needed
automated judges to catch quality issues without manual review on every change.

## Solution

Three LLM judges running Claude Haiku, auto-discovered from `evals/judges/*.md`.

### Architecture

```
eval_run_*.jsonl → run_judges.py → judge_run_*.jsonl → validate_judges.py
                       ↑                                       ↑
                  judges/*.md                        human_labeled_results.jsonl
                  data/resume.json
```

### Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Judge model | Claude Haiku | $0.04/full run, fast enough for serial |
| Judge format | Standalone .md files | Auto-discovery, no script changes to add a judge |
| Category filtering | Optional | Filters when categories exist, runs all when they don't |
| Output | Binary pass/fail JSON | Forces clarity, no ambiguous middle scores |
| Validation metric | TPR/TNR, not accuracy | Catches the difference between "too strict" vs "too lenient" |

### Category Filtering Pattern

The `applies_to` field in judge frontmatter is an optimization, not a requirement:
- Synthetic data has categories → only relevant judges run (saves API calls)
- Production data has no categories → all judges run on everything
- This is handled by one 12-line function (`should_judge_run`)

### Judges Built (mapped to failure modes)

| Judge | Failure Mode | applies_to | needs_source_data |
|---|---|---|---|
| groundedness | Hallucinated claims | core, edge_case | true |
| conciseness | Overly verbose (35+ failures) | all | false |
| redirect_behavior | Poor redirects | unanswerable, off_topic, adversarial | false |

### Judges Deferred

- **completeness**: Only 8 failures, fix data gaps first
- **tone**: Only 2 failures (emoji), not worth a judge yet
- **correctness**: Zero failures found in Phase 1

## Lessons Learned

1. **Start from failures, not buzzwords.** We didn't build a "correctness" judge
   because Phase 1 showed zero correctness failures. Build judges for problems
   you actually have.

2. **Categories are optional, not required.** Early design assumed all data would
   be categorized. Production data isn't. The script handles both by defaulting
   to "run everything" when no category exists.

3. **Production analytics need full responses.** Initially `log_query` only saved
   100 chars of the response. Fixed to store the full response so production data
   can be fed directly to judges.

4. **Keep the plan updated.** APP_EVAL_PLAN.md fell behind after Phase 1 completed.
   Stale docs create confusion about what's actually built vs. planned.

## Files

- `evals/judges/groundedness.md` — fact-checking judge
- `evals/judges/conciseness.md` — response length judge
- `evals/judges/redirect_behavior.md` — out-of-scope handling judge
- `evals/scripts/run_judges.py` — judge runner (auto-discovers judges)
- `evals/scripts/validate_judges.py` — compares judge verdicts to human labels
- `evals/JUDGE_SYSTEM_DESIGN.md` — full architecture doc
