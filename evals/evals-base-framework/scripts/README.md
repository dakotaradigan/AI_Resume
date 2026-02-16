# Scripts

Code-based graders and eval runner automation live here.

## Code-Based Grader Sub-Types

| Sub-Type                  | What It Checks                                     | Example Script              |
|---------------------------|----------------------------------------------------|-----------------------------|
| **Exact Match**           | Output matches expected string exactly              | `eval_exact_match.py`       |
| **Regex Match**           | Output matches a pattern                           | `eval_pattern.py`           |
| **Fuzzy Match**           | Output is similar enough to expected               | `eval_fuzzy.py`             |
| **Schema Validation**     | Output conforms to expected structure              | `eval_schema.py`            |
| **Static Analysis**       | Code output passes linting/type checks             | `eval_static_analysis.py`   |
| **Outcome Verification**  | End state matches expected state                   | `eval_outcome.py`           |
| **Tool Call Verification** | Agent called the right tools with right params    | `eval_tool_calls.py`        |
| **Transcript Metrics**    | Quantitative measures (turns, tokens, latency)     | `eval_metrics.py`           |

## Trial Isolation

**Critical:** Each trial must start from a clean environment. Scripts must:
- Reset any shared state (DB, files, cache) before each trial
- Prevent the agent from accessing artifacts from previous trials
- Vary random seeds across trials
- Mock or reset external API state between runs

## Multi-Trial Support

Runner scripts should support configurable trial counts:
- Quick iteration: 3-5 trials per task
- Pre-ship validation: 5-10 trials per task
- Benchmark-grade: 10-20 trials per task

Report both **pass@k** and **pass^k** in results.

## Naming
- `eval_{criterion}.py` — Individual graders (e.g. `eval_schema.py`, `eval_tool_calls.py`)
- `run_all.py` — Main runner that executes the full eval suite with trial support

## Output Format: JSONL

All eval results use **JSONL** — one JSON object per line. This enables streaming,
appending, and clean git diffs.

**Task-level results** (one line per task):
```jsonl
{"task_id":"core-001","trials":5,"passes":4,"pass_at_1":0.80,"pass_at_3":0.99,"pass_pow_3":0.51,"graders":{"schema_valid":{"pass":5,"fail":0},"tool_calls":{"pass":4,"fail":1},"tone_judge":{"pass":4,"fail":0,"unknown":1}}}
{"task_id":"core-002","trials":5,"passes":5,"pass_at_1":1.00,"pass_at_3":1.00,"pass_pow_3":1.00,"graders":{"schema_valid":{"pass":5,"fail":0},"tool_calls":{"pass":5,"fail":0},"tone_judge":{"pass":5,"fail":0,"unknown":0}}}
```

**Run-level summary** (separate file or first line):
```jsonl
{"run_id":"2025-01-15_pre-ship","trials_per_task":5,"total_tasks":100,"overall_pass_at_1":0.85,"suite_type":"regression","timestamp":"2025-01-15T14:30:00Z"}
```

## Reference Implementation Patterns

These patterns come from working eval scripts. They are not prescriptive — adapt
to your stack. But they solve common problems well.

### Auto-Discovery Pattern
Judges (or graders) live as standalone `.md` files with YAML frontmatter. The
runner script discovers them at runtime via glob — no registration step needed.

```python
# Discover all judge files in judges/ directory
for path in sorted(JUDGES_DIR.glob("*.md")):
    if path.name.lower() == "readme.md":
        continue
    judge = parse_frontmatter_and_prompt(path)
    judges.append(judge)
```

**Why:** Adding a new judge is as simple as creating a file. No script changes,
no config updates, no imports. This keeps the iteration loop tight.

### Category Filtering Pattern
Judge frontmatter includes an `applies_to` list of test case categories. The
runner checks whether a judge should run on each case.

```python
def should_judge_run(judge, category):
    if not category:        # Production data (no categories) → run all judges
        return True
    if not judge["applies_to"]:  # Judge has no filter → run on everything
        return True
    return category in judge["applies_to"]
```

**Why:** Not every judge applies to every test case. A groundedness check on a
prompt injection test is meaningless. This avoids wasted API calls and noisy results.

### Incremental JSONL Write Pattern
Write each verdict to disk immediately after receiving it, rather than
accumulating results in memory and writing at the end.

```python
record = {"case_id": case_id, "judge": judge_name, "verdict": verdict, ...}
with open(output_path, "a") as f:
    f.write(json.dumps(record) + "\n")
```

**Why:** If the script crashes mid-run (API error, rate limit, network issue),
you keep all results so far. No lost work. Also enables tailing output in real time.

### Judge Validation Pattern (TPR/TNR)
Compare judge verdicts to human-labeled ground truth using TPR and TNR — not
raw accuracy.

```python
for judge_name in judge_names:
    tp = fn = fp = tn = 0
    for case in labeled_cases:
        human = case["human_verdict"]
        judge = case["judge_verdict"]
        if human == "pass" and judge == "pass": tp += 1
        if human == "pass" and judge == "fail": fn += 1
        if human == "fail" and judge == "pass": fp += 1
        if human == "fail" and judge == "fail": tn += 1
    tpr = tp / (tp + fn) if (tp + fn) else 0
    tnr = tn / (tn + fp) if (tn + fp) else 0
```

**Why:** A judge that always says "pass" gets 90% accuracy if 90% of data passes,
but catches zero failures. TPR/TNR reveals this. See CORE_MENTAL_MODEL.md for
target thresholds by error tolerance stance.
