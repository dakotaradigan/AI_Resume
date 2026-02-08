# AI Evals — Core Mental Model

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
   ~100 samples      Match eval        Run in CI/CD
   Binary pass/fail  type to failure   Gate deploys
   Group into <10    mode              Monitor prod
   failure modes     Validate judges   Weekly 30-min review
```

---

## Phase 1: Discover Errors

**Start from real user pain, not industry buzzwords.**

1. Pull ~100 real user interactions
2. Domain expert labels each: **pass or fail** (binary, no scales)
3. Expert writes a **free-form critique** for each failure
4. Group failures into categories (open coding → axial coding)
5. Count and rank by frequency + severity

**Output:** A prioritized failure mode table (<10 categories)

**Anti-pattern:** Starting with "hallucination" or "toxicity" because they sound
important. If your users aren't hitting those problems, they're the wrong evals.

---

## Phase 2: Build Evals

**One eval type per failure mode. Ask one question:**

```
Is this failure OBJECTIVE?  ──────> Code-Based Eval
  (rule-based, deterministic)        Fast, cheap, no ambiguity
                                     e.g. JSON valid? API called correctly?

Is this failure SUBJECTIVE? ──────> LLM-as-Judge
  (requires judgment, nuance)        Scalable, PM-friendly (natural language)
                                     e.g. tone right? summary complete? helpful?

Need GROUND TRUTH signal?   ──────> Human Feedback Loop
  (user satisfaction, edge cases)    Thumbs up/down, expert labels
                                     Expensive but irreplaceable
```

### LLM-as-Judge: 4-Part Prompt Formula

```
┌─────────────────────────────────────────────────────┐
│  1. ROLE      → "You are an expert evaluator of..." │
│  2. CONTEXT   → Provide the actual app output       │
│  3. GOAL      → Define what pass vs. fail means     │
│  4. GROUNDING → Define YOUR terms (not generic)     │
└─────────────────────────────────────────────────────┘
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

```
  Development     → Run evals on every prompt/model change
  Pre-Ship Gate   → New version must score >= old version
  Production      → Sample live traffic, collect human feedback
  Weekly (30 min) → Review new failures, re-calibrate judges, check drift
```

---

## Architecture Cheat Sheet

| Architecture       | Key Eval Strategy                                              |
|--------------------|----------------------------------------------------------------|
| **Conversations**  | Eval at session level first, then isolate single-turn failures |
| **RAG**            | Eval retriever + generator separately. Fix retriever first.    |
| **Agents**         | Transition failure matrix — find where multi-step chains break |

---

## Three Eval Types at a Glance

| Type              | Speed  | Cost   | Handles Nuance | Best For                   |
|-------------------|--------|--------|-----------------|----------------------------|
| Code-Based        | Fast   | Cheap  | No              | Objective, structural checks |
| LLM-as-Judge      | Medium | Medium | Yes             | Subjective quality judgments |
| Human Feedback     | Slow   | High   | Yes             | Ground truth, UX signal      |

---

## The One Rule

> **Start from what's actually broken for your users.**
> Everything else follows from that.
