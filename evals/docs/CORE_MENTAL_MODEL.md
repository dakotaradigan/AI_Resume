# AI Evals — Core Mental Model

> Quick reference. For full details see `EVALS_FRAMEWORK.md`.
> For Claude Code behavior rules see `CLAUDE.md`.

---

## The Fundamental Shift

```
Traditional Software:  Requirements → Tests → Ship → Monitor
AI Products:           Error Analysis → Evals → Ship → Monitor → Error Analysis → ...
```

**"Evals are the new PRDs."**

AI requirements don't exist upfront — they EMERGE through the eval process.
People are bad at specifying what they want from AI. The eval loop IS the
requirements discovery process.

---

## The Loop (3 Phases, Continuous)

```
        ┌──────────────────────────────────────────────┐
        │                                              │
        v                                              │
  ┌───────────┐     ┌───────────┐     ┌───────────┐   │
  │  DISCOVER │────>│   BUILD   │────>│  OPERATE  │───┘
  │  ERRORS   │     │   EVALS   │     │  & SHIP   │
  └───────────┘     └───────────┘     └───────────┘
   ~100 samples      Multiple graders   Capability vs
   Binary pass/fail  per failure mode   Regression suites
   Group into <10    Multiple trials    Read transcripts
   failure modes     per task           Swiss Cheese layers
   Quality-check     Validate judges    Weekly 30-min review
   tasks             Partial credit ok
```

---

## Key Terms

| Term              | Meaning                                                    |
|-------------------|------------------------------------------------------------|
| **Task**          | A single test case with inputs and success criteria        |
| **Trial**         | One attempt at a task. Run many for reliable signal        |
| **Grader**        | Logic scoring one aspect. Tasks can have multiple graders  |
| **Transcript**    | Full record of a trial (outputs, tool calls, reasoning)    |
| **Capability Eval** | "What can it do?" — starts low, measures improvement    |
| **Regression Eval** | "Does it still work?" — must stay near 100%             |

---

## Phase 1: Discover Errors

**Start from real user pain, not industry buzzwords.**

1. Pull ~100 real user interactions
2. Domain expert labels each: **pass or fail** (binary for labeling ground truth)
3. Expert writes a **free-form critique** for each failure
4. Group failures into categories (open coding → axial coding)
5. Count and rank by frequency + severity
6. **Quality-check tasks:** Would two experts agree on pass/fail? If not, refine the task.

**Output:** A prioritized failure mode table (<10 categories)

**Anti-pattern:** Starting with "hallucination" or "toxicity" because they sound
important. If your users aren't hitting those problems, they're the wrong evals.

---

## Phase 2: Build Evals

**Multiple graders per failure mode. Ask for each aspect:**

```
Is this aspect OBJECTIVE?   ──────> Code-Based Grader
  (rule-based, deterministic)        e.g. JSON valid? Right tool called?

Is this aspect SUBJECTIVE?  ──────> LLM-as-Judge
  (requires judgment, nuance)        e.g. tone right? summary complete?

Need GROUND TRUTH?          ──────> Human Grading
  (calibration, edge cases)          e.g. expert review, spot-check

Example — "Wrong answer" failure mode:
  ├── Code grader:   Did it call the right tool?
  ├── Code grader:   Valid response structure?
  ├── LLM judge:     Content accurate?
  └── LLM judge:     Tone appropriate?
```

### LLM-as-Judge: 4-Part Prompt + Escape Hatch

```
┌─────────────────────────────────────────────────────────────┐
│  1. ROLE      → "You are an expert evaluator of..."         │
│  2. CONTEXT   → Provide the actual app output               │
│  3. GOAL      → Define what pass vs. fail means             │
│  4. GROUNDING → Define YOUR terms (not generic)             │
│  + ESCAPE     → Always include "Unknown / Insufficient Info" │
└─────────────────────────────────────────────────────────────┘
```

### Scoring

```
  Ground-truth labeling:  Binary pass/fail (forces clarity)
  Complex task grading:   Partial credit allowed (3/5 subtasks, 0.0-1.0 scale)
  Multiple graders:       All-pass, weighted, or hybrid combination
```

### Multi-Trial: pass@k and pass^k

```
  AI is non-deterministic. One run tells you very little.

  pass@k  →  "Can it do this AT ALL?"     (≥1 success in k trials, goes UP)
  pass^k  →  "Can it do this RELIABLY?"   (all k succeed, goes DOWN)

  Example: 7/10 trials pass
    pass@1 = 70%   pass@3 = 97%   pass^3 = 34%
    → Agent CAN do it, but NOT reliably.

  Quick iteration: 3-5 trials | Pre-ship: 5-10 | Benchmark: 10-20
```

### Validating Judges: TPR/TNR, Not Accuracy

```
  TPR (True Positive Rate):  Of things that should PASS, how many does the judge get right?
  TNR (True Negative Rate):  Of things that should FAIL, how many does the judge catch?

  Why not accuracy? → A judge that always says "pass" gets 90% accuracy
                      if 90% of data passes. But it catches ZERO failures.
```

### Error Tolerance: Know Your Product's Stance

```
  High-stakes (medical, legal, financial):
    → Maximize TNR — catch every failure, tolerate false alarms

  Creative (writing, brainstorming, exploration):
    → Maximize TPR — don't over-reject good outputs
```

---

## Phase 3: Operate & Ship

### Capability vs. Regression

```
  Capability evals → "What can it do?" → starts low → measures improvement
       │
       │  pass rate rises to >90%
       ▼
  Graduate to Regression → "Does it still work?" → must stay near 100%
       │
       │  saturated (no signal)
       ▼
  Add harder Capability evals at the frontier
```

### Trial Isolation
Each trial must start from a clean environment. No shared state between runs.

### The Swiss Cheese Model
No single layer catches everything. Stack them:
```
  Automated evals → Production monitoring → User feedback
  → Manual transcript review → Periodic human studies
```

### Transcript Reading (Not Optional)
Read 10-20 transcripts after every new grader. Spot-check 5-10 weekly.
Verify: failures are fair, passes are deserved, grader measures what matters.

### Eval Saturation
When scores stop moving, the suite is too easy. Add harder tasks.

### Pipeline

```
  Development     → Run evals on every prompt/model change (3-5 trials)
  Pre-Ship Gate   → Regression evals must pass threshold
  Production      → Sample live traffic, collect human feedback
  Weekly (30 min) → Read transcripts, check saturation, graduate evals
```

---

## Architecture Cheat Sheet

| Architecture         | Key Eval Strategy                                                |
|----------------------|------------------------------------------------------------------|
| **Conversations**    | Session-level first, isolate single-turn. Simulate users with LLM |
| **RAG**              | Eval retriever + generator separately. Fix retriever first        |
| **Agents**           | Transition failure matrix. Grade outcomes, not paths              |
| **Coding**           | Unit tests + static analysis + LLM quality review                 |
| **Research**         | Groundedness + coverage + source quality. Calibrate often         |

---

## Grader Types at a Glance

| Type              | Speed  | Cost   | Handles Nuance | Best For                      |
|-------------------|--------|--------|----------------|-------------------------------|
| Code-Based        | Fast   | Cheap  | No             | Objective, structural checks  |
| LLM-as-Judge      | Medium | Medium | Yes            | Subjective quality judgments   |
| Human Grading     | Slow   | High   | Yes            | Ground truth, calibration      |

*Use multiple graders per task. They complement each other.*

---

## Key Metrics

| Metric    | What It Measures                          | Direction       |
|-----------|-------------------------------------------|-----------------|
| **pass@k**| Can the agent do this at all?             | Higher = better |
| **pass^k**| Can the agent do this reliably?           | Higher = better |
| **TPR**   | Of real passes, how many does judge catch?| Higher = better |
| **TNR**   | Of real failures, how many does judge catch?| Higher = better |

---

## Expert Sources

- [Anthropic: Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Maxim: Building a Golden Dataset](https://www.getmaxim.ai/articles/building-a-golden-dataset-for-ai-evaluation-a-step-by-step-guide/)
- [Lenny's / Hamel Husain: Building Eval Systems That Improve](https://www.lennysnewsletter.com/p/building-eval-systems-that-improve)
- [Lenny's / Hamel Husain: Beyond Vibe Checks](https://www.lennysnewsletter.com/p/beyond-vibe-checks-a-pms-complete)
- [Lenny's: Why AI Evals Are the Hottest New Skill](https://www.lennysnewsletter.com/p/why-ai-evals-are-the-hottest-new-skill)

---

## The One Rule

> **Start from what's actually broken for your users.**
> Everything else follows from that.
