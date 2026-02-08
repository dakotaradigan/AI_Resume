# AI Evals Framework — Base Template

> Reusable across products and applications. Tailor per app by filling in the
> product-specific sections marked with `[TAILOR]`.

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

## Phase 1: Error Analysis (Discover What's Actually Broken)

**Goal:** Find your real failure modes from real user data — not from fashionable metrics.

### Step 1: Open Coding
1. Pull ~100 representative user interactions from production (or realistic test data)
2. Have one domain expert review each and provide:
   - **Binary pass/fail** judgment (no Likert scales — binary forces clarity)
   - **Free-form critique** detailed enough that a new hire could understand it
3. Document every observation as a specific "open code" label

### Step 2: Axial Coding (Pattern Finding)
1. Group open codes into concrete failure mode categories
2. Aim for **<10 primary categories**
3. Build a pivot table counting occurrences per category
4. **Prioritize by frequency and severity**

### Anti-Pattern
Do NOT start with generic metrics like "hallucination" or "toxicity" unless your
data actually shows those are your problems. Start from user pain, not industry buzzwords.

### Output of Phase 1
```
[TAILOR] Your Failure Mode Table:

| Failure Mode          | Count | Severity | Example                        |
|-----------------------|-------|----------|--------------------------------|
| e.g. Wrong tool call  | 23    | High     | Called flight API for hotels    |
| e.g. Ignores context  | 18    | High     | Missed budget constraint        |
| e.g. Tone mismatch    | 7     | Medium   | Too casual for enterprise user  |
| ...                   |       |          |                                |
```

---

## Phase 2: Build the Eval Suite

### Decision Framework: Which Eval Type Per Failure Mode?

```
For each failure mode, ask:
Is this OBJECTIVE / RULE-BASED?  ──> Code-Based Eval
Is this SUBJECTIVE / JUDGMENT?   ──> LLM-as-Judge Eval
Is this about USER SATISFACTION? ──> Human Feedback Loop
```

### The Three Eval Types

#### 1. Code-Based Evals
- **What:** Automated deterministic checks (API calls valid? JSON parseable? Code runs?)
- **When:** Objective, rule-based failures
- **Pros:** Fast, cheap, deterministic
- **Cons:** Can't handle nuance or subjective quality
- **Examples:** Schema validation, regex checks, assertion on structured output

#### 2. LLM-as-Judge Evals
- **What:** A separate LLM grades your app's outputs using a structured prompt
- **When:** Subjective failures requiring judgment (tone, relevance, completeness)
- **Pros:** Scalable, uses natural language criteria (PM-friendly), generates explanations
- **Cons:** Requires calibration against human labels; probabilistic
- **Examples:** Grading summary quality, detecting hallucination, assessing helpfulness

#### 3. Human Feedback Loops
- **What:** Thumbs up/down, comment boxes, expert labeling
- **When:** Direct UX signal, ground truth generation, edge cases
- **Pros:** Tied to real user experience
- **Cons:** Sparse, expensive, sometimes ambiguous

### Building an LLM-as-Judge (The 4-Part Formula)

Every LLM judge prompt needs:

```
1. ROLE SETTING     → "You are an expert evaluator examining [domain]..."
2. CONTEXT          → Supply the actual app data being evaluated
3. GOAL DEFINITION  → Clearly state what pass vs. fail looks like
4. TERM GROUNDING   → Define your specific criteria (what "toxic" means for YOUR app)
```

### Validating Your Judge

1. **Split your labeled data:** 10-20% train | 40-45% dev | 40-45% test
2. **Iterate on dev set:** Refine the judge prompt until it matches expert labels
3. **Hold test set untouched** until final evaluation
4. **Measure TPR and TNR, not raw accuracy:**
   - **True Positive Rate (TPR):** Of examples that should pass, what % does judge label pass?
   - **True Negative Rate (TNR):** Of examples that should fail, what % does judge label fail?
   - Raw accuracy is misleading on imbalanced datasets (a judge that always says "pass" looks great if 90% of examples pass)

### Tradeoff: Which Errors Hurt More?

```
[TAILOR] For your product, which matters more?

  High-stakes (medical, legal, financial):
    → Prioritize TNR (catch every failure, tolerate some false alarms)

  Creative / generative (writing, brainstorming):
    → Prioritize TPR (don't over-reject good outputs)

  Your product stance: _______________
```

---

## Phase 3: Operationalize (Ship and Maintain)

### Eval Pipeline Integration

```
[TAILOR] Where evals run in your workflow:

  Development:
    ├── On every prompt/model change → run full eval suite
    ├── On new feature branches     → run relevant subset
    └── Weekly                      → re-sample production data, re-run Phase 1

  Pre-Ship Gate:
    ├── All evals must pass thresholds before deploy
    └── Regression check: new version >= old version on all metrics

  Production Monitoring:
    ├── Sample live traffic for ongoing eval
    ├── Human feedback collection (thumbs up/down)
    └── Alert on metric degradation
```

### Weekly Maintenance (~30 min)
1. Review new production failures
2. Update failure mode categories if needed
3. Re-calibrate judges against fresh labeled data
4. Check for metric drift

---

## Standard Eval Criteria Library

Pick the ones relevant to your product:

| Criteria              | What It Measures                                         | Eval Type     |
|-----------------------|----------------------------------------------------------|---------------|
| **Hallucination**     | Is the output grounded in provided context?              | LLM-as-Judge  |
| **Toxicity/Tone**     | Harmful, off-brand, or inappropriate language?           | LLM-as-Judge  |
| **Correctness**       | Does it accomplish the primary task goal?                 | LLM-as-Judge  |
| **Code Validity**     | Does generated code parse/run without errors?            | Code-Based    |
| **Summarization**     | Does condensed output preserve key information?          | LLM-as-Judge  |
| **Retrieval Relevance** | (RAG) Do retrieved docs match the query?               | Code + LLM    |
| **Tool Use Accuracy** | (Agents) Did it call the right tools with right params?  | Code-Based    |
| **Preference Match**  | Did it honor user constraints and preferences?           | LLM-as-Judge  |
| **Latency/Cost**      | Response time and token usage within budget?             | Code-Based    |

```
[TAILOR] Your product's eval criteria:

  □ Hallucination
  □ Toxicity/Tone
  □ Correctness
  □ Code Validity
  □ Summarization
  □ Retrieval Relevance
  □ Tool Use Accuracy
  □ Preference Match
  □ Latency/Cost
  □ Custom: _______________
  □ Custom: _______________
```

---

## Architecture-Specific Playbooks

### Multi-Turn Conversations
1. Evaluate at **session level first** (did the whole conversation achieve the user's goal?)
2. When failures occur, reproduce in **single-turn** to distinguish:
   - Simple knowledge gaps vs. conversational memory issues

### RAG Pipelines
1. Evaluate **retriever** and **generator** separately
2. Retriever metrics: Recall@k (% of relevant docs in top k results)
3. Generator metrics: Faithfulness (sticks to retrieved facts) + Answer Relevance (addresses intent)
4. **Fix retriever first** — generator optimization follows

### Agentic Workflows
1. Go beyond pass/fail outcomes
2. Build a **transition failure matrix**: map agent states as assembly-line stages
3. Identify **hotspot transitions** where failures concentrate
4. Eval each tool call independently + the orchestration logic

---

## Tools

| Tool             | Type        | Best For                              |
|------------------|-------------|---------------------------------------|
| **Arize Phoenix**| Open Source  | Pre-built evaluators, tracing, no vendor lock-in |
| **Ragas**        | Open Source  | RAG-specific eval metrics             |
| **Braintrust**   | Platform     | Eval management, logging, scoring     |
| **LangSmith**    | Platform     | Tracing, datasets, eval runs          |

---

## Per-Product Tailoring Checklist

When applying this framework to a new product, fill in:

1. **Product context:** What does the AI feature do? Who are the users?
2. **Failure mode table:** Run Phase 1 on real/realistic data
3. **Eval criteria selection:** Pick from the standard library + add custom
4. **Error tolerance stance:** High-stakes or creative? TNR vs TPR priority
5. **Eval pipeline placement:** Where do evals run? What gates shipping?
6. **Architecture playbook:** Conversation? RAG? Agents? Pick the right one
7. **Tools:** Which eval tooling fits your stack?
8. **Maintenance owner:** Who runs the weekly 30-min review?

---

## Quick Reference: The Core Mental Model

```
"Evals are the new PRDs"

  Traditional Software:  Requirements → Tests → Ship → Monitor
  AI Products:           Error Analysis → Evals → Ship → Monitor → Error Analysis → ...

The key difference: AI requirements EMERGE through the eval process.
People are bad at specifying AI requirements upfront.
The eval loop IS the requirements discovery process.
```

---

## One-Liner Summary

> Start from real user failures (not buzzwords), build binary pass/fail evals
> matched to each failure mode, validate your judges with TPR/TNR, and run
> the loop weekly.
