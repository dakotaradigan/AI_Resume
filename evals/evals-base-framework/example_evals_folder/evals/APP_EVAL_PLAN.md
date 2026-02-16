# Resume Assistant — Eval Plan

> Tailored from docs/EVALS_FRAMEWORK.md for the Resume Assistant chatbot.

---

## Product Context

**What it does:** Conversational AI assistant that answers questions about Dakota
Radigan's professional background using resume and project data.

**Users:** Recruiters and hiring managers — busy, low patience, 2-5 questions max.

**Architecture:** Conversational RAG — semantic search over chunked documents in
Qdrant, retrieved context fed to Claude for response generation.

**Error tolerance:** Conservative-flexible. Prioritize TNR (catch failures) over
TPR. One hallucinated job title or fabricated skill could cost an interview. But
the bot should still be helpful — when it doesn't have info, it should say so
honestly and direct the user to reach out to Dakota directly.

---

## Mental Map: The Big Picture

```
┌─────────────────────────────────────────────────────────────┐
│                    CONTINUOUS EVAL LOOP                      │
│                                                             │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐             │
│   │  PHASE 1 │───>│  PHASE 2 │───>│  PHASE 3 │──┐         │
│   │  Discover │    │  Build   │    │ Operate  │  │         │
│   │  Errors   │    │  Evals   │    │ & Ship   │  │         │
│   └──────────┘    └──────────┘    └──────────┘  │         │
│        ^                                         │         │
│        └─────────────────────────────────────────┘         │
│                  (weekly ~30 min maintenance)                │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Error Analysis

### Status: COMPLETE (2026-02-08)

### Data Source
- **Synthetic dataset:** 100 test cases across 5 categories (45 core, 15 edge_case, 15 unanswerable, 10 off_topic, 15 adversarial)
- File: `datasets/synthetic_eval_v1.jsonl`
- Eval run: `results/eval_run_2026-02-08_120102.jsonl`
- Human labels: `results/human_labeled_results.jsonl`

### Results Summary
- **41 pass, 58 fail, 1 unlabeled** out of 100 test cases
- **Avg response time:** 5.41s (88% over 3s target)
- **0 errors or timeouts** — the bot always responds, it's just often too verbose or slow

### Failure Mode Table (from human review)

| Failure Mode            | Count | Severity | Eval Type    | Todo  |
|-------------------------|-------|----------|--------------|-------|
| Overly verbose          | 35+   | P1       | LLM-as-Judge | #030  |
| High latency (>3s)      | 88    | P1       | Code-based   | —     |
| Missing resume data     | 8     | P2       | Data fix     | #032  |
| Phone number leaked     | 3     | P0       | Data fix     | FIXED |
| Adversarial too polite  | 5     | P1       | LLM-as-Judge | #031  |
| Unanswerable too wordy  | 7     | P2       | LLM-as-Judge | #033  |
| Tone (emoji in response)| 2     | P3       | —            | —     |

### Key Findings
- Verbosity is the #1 problem by count — drives both poor UX and high latency
- Phone number leak was critical — fixed immediately by scrubbing from resume.json
- Latency is mostly a symptom of verbosity (longer responses = more tokens = slower)
- No hallucinations detected in this run — groundedness is solid but needs ongoing monitoring

---

## Phase 2: Eval Suite

### Status: IN PROGRESS

### Judges Built (mapped to Phase 1 failure modes)

| Judge                | Failure Mode         | Eval Type    | Status | Applies To                                |
|----------------------|----------------------|--------------|--------|-------------------------------------------|
| **groundedness**     | Hallucinated claims  | LLM-as-Judge | Built  | core, edge_case                           |
| **conciseness**      | Overly verbose       | LLM-as-Judge | Built  | all categories                            |
| **redirect_behavior**| Poor redirects       | LLM-as-Judge | Built  | unanswerable, off_topic, adversarial      |

### Judges NOT Built Yet (and why)

| Judge          | Failure Count | Reason to Defer                                    |
|----------------|---------------|-----------------------------------------------------|
| completeness   | 8             | Fix the data gaps first (todo #032), then re-eval   |
| tone           | 2             | Low priority — only emoji issues detected            |
| correctness    | 0             | No failures found in Phase 1; monitor, don't build  |

Per the framework: "Start from real user failures, not industry buzzwords."

### Code-Based Metrics (captured by run_eval.py, no separate scripts needed)

| Metric         | How It's Measured                         | Status |
|----------------|-------------------------------------------|--------|
| **Latency**    | `response_time_s` in eval run output      | Built  |
| **Error rate** | `status` field in eval run output         | Built  |

### Architecture Playbook: RAG Pipeline

Eval the **retriever** and **generator** separately:

1. **Retriever evals** (fix these first):
   - Are the right chunks being pulled for each query?
   - Recall@k: what % of relevant docs appear in top k results?
   - Are irrelevant chunks diluting context?

2. **Generator evals** (after retriever is solid):
   - Given correct context, does Claude produce a faithful answer?
   - Is the response grounded in retrieved facts only?
   - Does it address the user's actual intent?

### Error Tolerance Stance

**Conservative-flexible.** Prioritize TNR — catch every failure, tolerate some
false alarms. The reasoning:

- A hallucinated skill on a resume bot destroys credibility → must catch
- A "I don't have that info" when the info exists is bad but recoverable
- A false alarm (flagging a good response) wastes dev time but doesn't hurt users

### Judge Design

Each judge is a standalone `.md` file in `judges/` with:
- YAML frontmatter: `name`, `description`, `applies_to`, `needs_source_data`
- 4-part system prompt: Role, Context, Goal, Grounding
- Output: `{"verdict": "pass"|"fail"|"unknown", "reason": "..."}`

Category filtering is optional — judges run on all data when no category exists
(production data), and filter by `applies_to` when categories are present
(synthetic data). See `docs/JUDGE_SYSTEM_DESIGN.md` for full architecture details.

### Judge Validation

Judges are validated against human labels using TPR/TNR (not raw accuracy):
- **TPR** (sensitivity): Of human-pass cases, how many did the judge pass?
- **TNR** (specificity): Of human-fail cases, how many did the judge fail?
- Target: TNR > 80%, TPR > 85%
- Script: `scripts/validate_judges.py`

---

## Phase 3: Operationalize

### Pipeline Placement

```
Development:
  ├── On prompt/system changes → run full eval suite
  ├── On model changes         → run full eval suite
  └── On data changes          → run retrieval evals

Pre-Ship:
  ├── All P0 evals must pass before deploy
  └── Regression check: new version >= old version

Production Monitoring:
  ├── Thumbs up/down feedback (already collecting)
  ├── Export and review weekly
  └── Alert threshold: >10% thumbs down in a day
```

### Weekly Maintenance (~30 min)

1. Pull latest production data via admin export endpoint
2. Review any thumbs-down feedback — what went wrong?
3. Update failure mode table if new patterns emerge
4. Re-run eval suite if prompt or data changed
5. Check latency and error rate trends

### Maintenance Owner

Dakota Radigan (solo project)

---

## Success Metrics (Three Layers)

### User Success (Recruiter)
- Query success rate: >90% of questions get a substantive answer
- Groundedness: zero hallucinated claims
- Session depth: average 3-5 exchanges per session

### Product Success (Dakota)
- Engagement: recruiters spend 2-5 minutes (vs 30 seconds on PDF)
- Coverage: bot can answer top 20 recruiter questions accurately
- Representation: bot says things Dakota would say about himself

### System Health
- P95 latency: <3 seconds
- Error rate: <1%
- Cost: <$10/month

---

## Tools

| Tool              | Status   | Use Case                                    |
|-------------------|----------|---------------------------------------------|
| run_eval.py       | Live     | Run queries against bot, collect responses  |
| build_review_xlsx | Live     | Generate Excel for human review             |
| parse_review.py   | Live     | Parse human labels into JSONL               |
| run_judges.py     | Live     | Run LLM judges on any eval data             |
| validate_judges.py| Live     | Compare judge verdicts to human labels      |
| LLM-as-Judge      | Live     | 3 judges: groundedness, conciseness, redirect |
| Thumbs up/down    | Live     | Human feedback signal from production       |
| Admin export API  | Live     | Pull production data for analysis           |

---

## Next Steps

1. **Run judges** on Phase 1 eval data and validate against human labels
2. **Tune judge prompts** if TPR/TNR below thresholds
3. **Fix P1 todos** (#030 verbosity, #031 adversarial redirect) and re-eval
4. **Fix P2 todos** (#032 resume data, #033 unanswerable redirect)
5. **Phase 3:** Establish baseline scores, set up pre-ship eval gate
