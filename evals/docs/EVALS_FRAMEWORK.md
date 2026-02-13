# AI Evals Framework — Base Template

> Reusable across products and applications. Tailor per app by filling in the
> product-specific sections marked with `[TAILOR]`.

---

## Expert Sources

This framework synthesizes guidance from:
- [Anthropic: Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Maxim: Building a Golden Dataset](https://www.getmaxim.ai/articles/building-a-golden-dataset-for-ai-evaluation-a-step-by-step-guide/)
- [Lenny's / Hamel Husain: Building Eval Systems That Improve](https://www.lennysnewsletter.com/p/building-eval-systems-that-improve)
- [Lenny's / Hamel Husain: Beyond Vibe Checks](https://www.lennysnewsletter.com/p/beyond-vibe-checks-a-pms-complete)
- [Lenny's: Why AI Evals Are the Hottest New Skill](https://www.lennysnewsletter.com/p/why-ai-evals-are-the-hottest-new-skill)

---

## Glossary

Consistent terminology across the framework. Based on Anthropic's definitions.

| Term                | Definition                                                                 |
|---------------------|----------------------------------------------------------------------------|
| **Task**            | A single test case with defined inputs and success criteria                |
| **Trial**           | One attempt at a task. Run multiple trials to account for model variance   |
| **Grader**          | Logic that scores one aspect of agent performance. Tasks can have multiple |
| **Transcript**      | Complete record of a trial: outputs, tool calls, reasoning, intermediate steps |
| **Outcome**         | The final environment state at trial end (distinct from what the agent claims) |
| **Eval Harness**    | Infrastructure that runs evals end-to-end                                  |
| **Agent Scaffold**  | The system that enables a model to act as an agent (tools, memory, etc.)   |
| **Eval Suite**      | A collection of tasks measuring specific capabilities or behaviors         |
| **Capability Eval** | Measures "what can this agent do?" — starts at low pass rates              |
| **Regression Eval** | Measures "does it still do what it used to?" — should be near 100%         |

---

## Mental Map: The Big Picture

```
┌──────────────────────────────────────────────────────────────────┐
│                     CONTINUOUS EVAL LOOP                          │
│                                                                  │
│   ┌───────────┐    ┌───────────┐    ┌───────────┐               │
│   │  PHASE 1  │───>│  PHASE 2  │───>│  PHASE 3  │──┐           │
│   │  Discover │    │   Build   │    │  Operate  │  │           │
│   │  Errors   │    │   Evals   │    │  & Ship   │  │           │
│   └───────────┘    └───────────┘    └───────────┘  │           │
│        ^                                            │           │
│        └────────────────────────────────────────────┘           │
│                                                                  │
│   Phase 1.5: Build Test Dataset (between Phase 1 and 2)         │
│   Transcript reading happens continuously across all phases      │
│                                                                  │
│   Capability evals ──(high pass rate)──> graduate to Regression  │
│   Regression evals ──(saturated)──> add harder Capability evals  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Error Analysis (Discover What's Actually Broken)

**Goal:** Find your real failure modes from real user data — not from fashionable metrics.

### Step 1: Open Coding
1. Pull ~100 representative user interactions from production (or realistic test data)
2. Have one domain expert review each and provide:
   - **Binary pass/fail** judgment (binary forces clarity for labeling ground truth)
   - **Free-form critique** detailed enough that a new hire could understand it
3. Document every observation as a specific "open code" label

### Step 2: Axial Coding (Pattern Finding)
1. Group open codes into concrete failure mode categories
2. Aim for **<10 primary categories**
3. Build a pivot table counting occurrences per category
4. **Prioritize by frequency and severity**

### Step 3: Task Quality Check

Before building evals from your failure modes, verify each task is well-defined:

**The Unambiguity Test:** Two domain experts should independently reach the same
pass/fail verdict on any given task. If they wouldn't agree, the task needs
refinement — not the agent.

**The Solvability Check:** A 0% pass rate across many trials (0% pass@100) almost
always means the task is broken, not the agent. Include a reference solution for
each task proving it can be solved.

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

## Phase 1.5: Build the Test Dataset (Golden Dataset Construction)

**Goal:** Construct a structured, balanced dataset that covers real usage AND edge
cases. This is the foundation everything else is built on.

### The 5-Category Dataset Template

Every eval dataset should cover these five categories. Adjust the labels to
match your app's domain, but keep the structure.

| #  | Category                     | What It Tests                                    | % of Dataset | Source              |
|----|------------------------------|--------------------------------------------------|--------------|---------------------|
| 1  | **Core Use Case Queries**    | Happy path — the actual thing users do           | 40-50%       | Production + Synthetic |
| 2  | **Edge Cases**               | Vague, multi-part, ambiguous, or tricky inputs   | 15-20%       | Synthetic           |
| 3  | **Unanswerable (On-Topic)**  | Questions the system shouldn't have answers for  | 10-15%       | Synthetic           |
| 4  | **Off-Topic / Out of Scope** | Inputs outside the system's intended purpose     | 5-10%        | Synthetic           |
| 5  | **Adversarial / Red-Team**   | Prompt injection, jailbreaks, manipulation       | 5-10%        | Synthetic           |

**Why this split:**
- Anthropic recommends starting from real failures, with BOTH positive and negative
  cases. One-sided testing creates blind spots — "if you only test whether the agent
  searches when it should, you might end up with an agent that searches for everything."
- Maxim identifies 5 golden dataset properties: Defined Scope, Production Fidelity,
  Diversity, Decontamination, and Dynamic Evolution.
- The framework (Hamel Husain) says start from real interactions and group into
  failure modes. Categories 2-5 surface failures you won't see in happy-path-only testing.

### Sizing Guide

| App Maturity            | Recommended Dataset Size | Notes                                    |
|-------------------------|--------------------------|------------------------------------------|
| **Pre-launch / MVP**    | 50-100 tasks             | Mostly synthetic, bootstrap quality      |
| **Early production**    | 100-200 tasks            | Mix of real + synthetic                  |
| **Mature product**      | 200-500+ tasks           | Mostly real, synthetic for edge/adversarial |

### Dataset Maturity Lifecycle (Silver to Gold)

Datasets are living artifacts. They evolve through three stages:

```
Stage 1: BOOTSTRAP (Silver)
  └── 100% synthetic — you make up realistic inputs
  └── Purpose: get evals running before you have real data
  └── Label: mark every case as "synthetic" in metadata

Stage 2: VALIDATE (Silver → Gold)
  └── Replace core use case queries with real production interactions
  └── Keep synthetic edge/adversarial cases (hard to find in the wild)
  └── Validate: do synthetic cases still represent real failure modes?
  └── Target: 50%+ real data in core category

Stage 3: EVOLVE (Gold)
  └── Continuously sample production traffic
  └── Add new cases when you discover new failure modes
  └── Retire cases that no longer represent real usage
  └── Refresh adversarial cases as attack patterns evolve
  └── Target: living dataset that reflects current product reality
```

**Key principle:** Real data beats synthetic every time. Synthetic is a bootstrap,
not a destination.

### Decontamination

Check that your eval dataset doesn't overlap with the model's training data.
If the model has "seen" your test cases during training, eval scores will be
inflated. Strategies:
- Use real production data (post-training) rather than public benchmarks
- If using synthetic data, verify it wasn't generated from the same model being evaluated
- Rotate eval cases periodically so they don't leak into fine-tuning sets
- When in doubt, hold out a fresh test set that has never been used for training or prompt engineering

### Per-Task Format (JSONL)

All datasets use **JSONL** (one JSON object per line). This enables streaming,
line-by-line processing, clean git diffs, and easy appending without rewriting files.

Each line should contain:

```jsonl
{"id":"core-001","category":"core","input":"The user query or trigger","expected_behavior":"What the system SHOULD do (behavior description, not exact text)","reference_solution":"A known-good response proving this task is solvable (optional for subjective tasks)","source":"synthetic","difficulty":"easy","notes":"Any context about why this case matters"}
```

**Required fields:** `id`, `category`, `input`, `expected_behavior`, `source`
**Recommended fields:** `reference_solution`, `difficulty`, `notes`

### Building the Dataset: Step by Step

1. **Start with the 5-category table above.** Adapt the category labels to your app's domain.
2. **Write core use case queries first** (40-50%). These are the real thing your users do.
3. **Add edge cases** (15-20%). Think: what would a confused or demanding user ask?
4. **Add unanswerable cases** (10-15%). Test whether the system says "I don't know" when it should.
5. **Add off-topic cases** (5-10%). Test whether it stays in its lane.
6. **Add adversarial cases** (5-10%). Prompt injection, role-play attacks, boundary testing.
7. **For each case, write `expected_behavior`** — not exact output text, but what the system should DO.
8. **Write `reference_solution`** for objective tasks. Skip for purely subjective ones.
9. **Run the Unambiguity Test** on a sample: would two experts agree on pass/fail?
10. **Mark every case as synthetic.** Replace with real data as it becomes available.

```
[TAILOR] Your dataset plan:

| Category                | Label for Your App     | Count | Status     |
|-------------------------|------------------------|-------|------------|
| Core Use Case Queries   | e.g. "Order questions" | ___   | □ Draft    |
| Edge Cases              | e.g. "Multi-issue asks"| ___   | □ Draft    |
| Unanswerable (On-Topic) | e.g. "Internal-only info"| ___  | □ Draft    |
| Off-Topic               | e.g. "Non-product asks"| ___   | □ Draft    |
| Adversarial / Red-Team  | e.g. "Prompt injection"| ___   | □ Draft    |
| TOTAL                   |                        | ___   |            |

Dataset maturity stage: □ Bootstrap  □ Validate  □ Evolve
```

---

## Phase 2: Build the Eval Suite

### Decision Framework: Which Grader Types Per Failure Mode?

A single failure mode often needs **multiple graders** working together. Ask:

```
What aspects of this failure are OBJECTIVE?  ──> Code-Based Grader(s)
What aspects require JUDGMENT?               ──> LLM-as-Judge Grader(s)
Do you need GROUND TRUTH calibration?        ──> Human Grading

Example — "Agent gives wrong answer" might need:
  ├── Code grader:    Did it call the right tool?
  ├── Code grader:    Is the response valid JSON?
  ├── LLM judge:      Is the content accurate?
  └── LLM judge:      Is the tone appropriate?
```

### Grader Types (Detailed)

#### 1. Code-Based Graders
- **What:** Automated deterministic checks
- **Pros:** Fast, cheap, deterministic, reproducible, debuggable
- **Cons:** Brittle to valid variations, can't handle nuance
- **Anti-pattern:** Rigid grading that penalizes valid alternative solutions

| Sub-Type                | What It Checks                                      | Example                                    |
|-------------------------|-----------------------------------------------------|--------------------------------------------|
| **Exact Match**         | Output matches expected string exactly               | API returned correct status code            |
| **Regex Match**         | Output matches a pattern                             | Email format validation                     |
| **Fuzzy Match**         | Output is similar enough to expected                 | Name matching with typo tolerance           |
| **Schema Validation**   | Output conforms to expected structure                | JSON schema, required fields present        |
| **Static Analysis**     | Code output passes linting/type checks               | ruff, mypy, bandit on generated code        |
| **Outcome Verification**| End state matches expected state                     | Database row created, file written           |
| **Tool Call Verification** | Agent called the right tools with right params    | Called search API, not delete API            |
| **Transcript Metrics**  | Quantitative measures of the trial                   | Turn count, token usage, latency            |

#### 2. LLM-as-Judge Graders
- **What:** A separate LLM grades outputs using a structured prompt
- **Pros:** Flexible, scalable, captures nuance, handles open-ended tasks
- **Cons:** Non-deterministic, more expensive, requires calibration
- **Anti-pattern:** Vague rubrics that different judges interpret differently

| Sub-Type                   | What It Does                                        | When to Use                               |
|----------------------------|-----------------------------------------------------|-------------------------------------------|
| **Rubric-Based Scoring**   | Grades against defined criteria with score levels   | Most common; tone, quality, completeness  |
| **Natural Language Assertions** | Checks if specific claims are true/false       | "Does the response mention the return policy?" |
| **Pairwise Comparison**    | Compares two outputs, picks the better one          | A/B testing prompt changes                |
| **Reference-Based**        | Compares output to a known-good reference           | When you have gold-standard answers       |
| **Multi-Judge Consensus**  | Multiple judge prompts vote on the same output      | High-stakes decisions, reducing bias      |

#### 3. Human Graders
- **What:** Expert review of outputs
- **Pros:** Gold standard quality, matches real user judgment
- **Cons:** Expensive, slow, requires expert access

| Sub-Type                   | What It Does                                        | When to Use                               |
|----------------------------|-----------------------------------------------------|-------------------------------------------|
| **SME Review**             | Domain expert evaluates quality                     | Calibrating LLM judges, ground truth      |
| **Crowdsourced Judgment**  | Multiple non-expert raters                          | Subjective quality at scale               |
| **Spot-Check Sampling**    | Random sample review of auto-graded results         | Ongoing validation of grader accuracy     |
| **A/B Testing**            | Real users interact with two versions               | Measuring actual user preference          |
| **Inter-Annotator Agreement** | Multiple experts grade same items, measure agreement | Validating labeling consistency        |

### Combining Multiple Graders Per Task

When a task has multiple graders, decide how to combine scores:

| Strategy     | How It Works                                         | When to Use                               |
|--------------|------------------------------------------------------|-------------------------------------------|
| **All-Pass** | Every grader must pass for the task to pass          | Safety-critical: no grader can be wrong   |
| **Weighted** | Each grader contributes a weighted score to a total  | Multi-dimensional quality assessment      |
| **Hybrid**   | Some graders are hard gates, others contribute score | Mix of must-pass safety + quality scoring |

```
[TAILOR] Your grader combination strategy: □ All-Pass  □ Weighted  □ Hybrid
```

### Building an LLM-as-Judge (The 4-Part Formula)

Every LLM judge prompt needs:

```
1. ROLE SETTING     → "You are an expert evaluator examining [domain]..."
2. CONTEXT          → Supply the actual app data being evaluated
3. GOAL DEFINITION  → Clearly state what pass vs. fail looks like
4. TERM GROUNDING   → Define your specific criteria (what "toxic" means for YOUR app)
```

**Escape Hatch (Required):** Always give the judge an "Unknown" or "Insufficient
Information" option. This prevents the judge from hallucinating a grade when it
doesn't have enough context to decide. Without this, judges will confidently
score things they can't actually evaluate.

### Scoring: Binary Default, Partial Credit When Needed

**For ground-truth labeling:** Use binary pass/fail. Binary forces clarity and
scales well for consistent labeling. Nuance goes in the critique, not the label.

**For grading complex tasks:** Use partial credit when tasks have multiple
independent components. A travel agent that books the right flight but wrong
hotel deserves a different score than one that gets everything wrong.

```
Simple task (single-component):     Binary pass/fail
Complex task (multi-component):     Partial credit (e.g., 0.0 to 1.0)
                                    or component-level binary (3/5 subtasks passed)
```

### Multi-Trial Scoring: pass@k and pass^k

AI outputs are non-deterministic. Running a task once tells you very little.
Run each task **multiple trials** to get reliable signal.

**pass@k** — Probability of at least 1 success in k trials.
As k increases, pass@k rises. Answers: "Can the agent do this at all?"

**pass^k** — Probability of ALL k trials succeeding.
As k increases, pass^k falls. Answers: "Can the agent do this reliably?"

```
Example: Agent passes 7 out of 10 trials on a task.

  pass@1  = 70%    (any single attempt has 70% chance)
  pass@3  = 97%    (very likely to get at least 1 success in 3 tries)
  pass^3  = 34%    (only 34% chance ALL 3 attempts succeed)

  Interpretation: Agent CAN do this task, but can't do it RELIABLY.
```

**Recommended trials per task:**

| Context              | Trials | Why                                              |
|----------------------|--------|--------------------------------------------------|
| Quick iteration      | 3-5    | Fast signal, catches obvious issues              |
| Pre-ship validation  | 5-10   | Reliable pass rates for gating decisions         |
| Benchmark-grade      | 10-20  | High-confidence scores for capability claims     |

### Validating Your LLM Judge

1. **Split your labeled data:** 10-20% train | 40-45% dev | 40-45% test
2. **Iterate on dev set:** Refine the judge prompt until it matches expert labels
3. **Hold test set untouched** until final evaluation
4. **Measure TPR and TNR, not raw accuracy:**
   - **True Positive Rate (TPR):** Of examples that should pass, what % does judge label pass?
   - **True Negative Rate (TNR):** Of examples that should fail, what % does judge label fail?
   - Raw accuracy is misleading on imbalanced datasets (a judge that always says "pass"
     looks great if 90% of examples pass, but catches zero failures)
5. **Spot-check with transcript reading:** Read 10-20 graded transcripts to verify
   the judge's reasoning makes sense, not just its final score

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

### Capability Evals vs. Regression Evals

This distinction changes how you interpret scores and organize your suite:

| Dimension      | Capability Eval                        | Regression Eval                         |
|----------------|----------------------------------------|-----------------------------------------|
| **Question**   | "What can this agent do?"              | "Does it still do what it used to?"     |
| **Starting pass rate** | Low (that's the point)           | Near 100% (that's the requirement)      |
| **Purpose**    | Measure improvement, push boundaries   | Catch breakage, prevent regressions     |
| **When to add tasks** | When you want to test new abilities | When capability evals hit high pass rates |
| **Failure signal** | Expected — shows room to improve    | Urgent — something broke                |

**The graduation flow:**
```
Capability eval (new, hard tasks)
  │
  │  pass rate rises over time
  │
  ▼
High pass rate (>90% consistently)
  │
  │  graduate to regression suite
  │
  ▼
Regression eval (must stay near 100%)
  │
  │  if saturated, no more signal
  │
  ▼
Add new, harder Capability evals
```

```
[TAILOR] Your eval suite organization:

  Capability evals (pushing boundaries):
    - _______________
    - _______________

  Regression evals (must not break):
    - _______________
    - _______________
```

### Trial Isolation

**Each trial must start from a clean environment.** Shared state between runs
causes correlated failures and unreliable scores.

Checklist:
- [ ] Each trial gets a fresh environment (no leftover files, DB rows, or cache)
- [ ] Agent cannot access artifacts from previous trials
- [ ] External API state is reset or mocked between runs
- [ ] Random seeds are varied across trials (don't test the same lucky path)

### Eval Pipeline Integration

```
[TAILOR] Where evals run in your workflow:

  Development:
    ├── On every prompt/model change → run full eval suite (3-5 trials per task)
    ├── On new feature branches     → run relevant subset
    └── Weekly                      → re-sample production data, re-run Phase 1

  Pre-Ship Gate:
    ├── Regression evals must pass threshold (e.g., >95%) before deploy
    ├── Capability evals tracked but not gating (informational)
    └── Regression check: new version >= old version on all regression metrics

  Production Monitoring:
    ├── Sample live traffic for ongoing eval
    ├── Human feedback collection (thumbs up/down)
    └── Alert on regression metric degradation
```

### The Swiss Cheese Model

No single evaluation layer catches every problem. Stack multiple layers so
failures slipping through one are caught by another:

```
┌─────────────────────────────────────┐
│  Layer 1: Automated evals (pre-ship)│  ← Fast iteration, reproducible
├─────────────────────────────────────┤
│  Layer 2: Production monitoring     │  ← Real behavior, ground truth
├─────────────────────────────────────┤
│  Layer 3: User feedback             │  ← Surfaces unanticipated issues
├─────────────────────────────────────┤
│  Layer 4: Manual transcript review  │  ← Builds intuition, catches subtlety
├─────────────────────────────────────┤
│  Layer 5: Periodic human studies    │  ← Gold standard for subjective tasks
└─────────────────────────────────────┘

Each layer has holes. Together, the holes don't line up.
```

### Transcript Reading

**This is not optional.** You won't know if your graders are working unless you
read the actual transcripts.

**When to read transcripts:**
- After building any new grader — read 10-20 graded transcripts
- After any eval score changes unexpectedly — read the failures
- Periodically during maintenance — spot-check 5-10 per week

**What to look for:**
- Do failures seem fair? (Agent actually failed, not a broken task)
- Do passes seem deserved? (Agent actually succeeded, not a grader loophole)
- Is the grader measuring what actually matters to users?
- Are there failure patterns the graders don't catch?

### Eval Saturation

When your agent passes nearly all tasks in a suite, the suite stops providing
useful signal. Watch for:
- Regression suite consistently at 100% — healthy, keep monitoring
- Capability suite consistently at >90% — time to add harder tasks
- No score movement after prompt/model changes — suite may be too easy

**Response:** Add new capability tasks at the frontier of what your agent can't
do yet. Retire or archive tasks that have been trivially passing for months.

### Weekly Maintenance (~30 min)
1. Review new production failures → do they map to existing eval tasks?
2. Read 5-10 transcripts from recent eval runs (spot-check grader quality)
3. Check for eval saturation (scores stuck at ceiling)
4. Update failure mode categories if new patterns emerge
5. Re-calibrate LLM judges against fresh labeled data if drift detected
6. Graduate high-performing capability evals to regression suite

---

## Standard Eval Criteria Library

Pick the ones relevant to your product. Most tasks need **multiple graders**
from this list working together.

| Criteria              | What It Measures                                         | Grader Type   |
|-----------------------|----------------------------------------------------------|---------------|
| **Hallucination**     | Is the output grounded in provided context?              | LLM Judge     |
| **Toxicity/Tone**     | Harmful, off-brand, or inappropriate language?           | LLM Judge     |
| **Correctness**       | Does it accomplish the primary task goal?                 | LLM Judge     |
| **Code Validity**     | Does generated code parse/run without errors?            | Code-Based    |
| **Summarization**     | Does condensed output preserve key information?          | LLM Judge     |
| **Retrieval Relevance** | (RAG) Do retrieved docs match the query?               | Code + LLM    |
| **Tool Use Accuracy** | (Agents) Did it call the right tools with right params?  | Code-Based    |
| **Preference Match**  | Did it honor user constraints and preferences?           | LLM Judge     |
| **Latency/Cost**      | Response time and token usage within budget?             | Code-Based    |
| **Groundedness**      | Are all claims supported by cited sources?               | LLM Judge     |
| **Completeness**      | Does the response cover all requested aspects?           | LLM Judge     |
| **Safety/Boundaries** | Does it refuse out-of-scope or dangerous requests?       | Code + LLM    |

```
[TAILOR] Your product's eval criteria:

  □ Hallucination        □ Toxicity/Tone       □ Correctness
  □ Code Validity        □ Summarization        □ Retrieval Relevance
  □ Tool Use Accuracy    □ Preference Match     □ Latency/Cost
  □ Groundedness         □ Completeness         □ Safety/Boundaries
  □ Custom: _______________
  □ Custom: _______________
```

---

## Architecture-Specific Playbooks

### Multi-Turn Conversations

**Challenge:** The quality of the interaction itself is part of what you're evaluating.

**Approach:**
1. Evaluate at **session level first** — did the whole conversation achieve the user's goal?
2. When failures occur, reproduce in **single-turn** to distinguish:
   - Simple knowledge gaps vs. conversational memory issues
3. Consider using a second LLM to simulate the user in multi-turn test scenarios

**Grader Recipe:**
| Grader                     | Type       | What It Checks                            |
|----------------------------|------------|-------------------------------------------|
| State check                | Code       | Was the ticket resolved? Refund processed? |
| Turn limit                 | Code       | Finished within N turns?                   |
| Tool call verification     | Code       | Called required tools (verify identity, etc.)? |
| Tone/empathy rubric        | LLM Judge  | Appropriate, empathetic, clear?           |
| Groundedness               | LLM Judge  | Responses grounded in actual data?        |
| Transcript metrics         | Code       | Turn count, token usage, latency          |

### RAG Pipelines

**Approach:** Evaluate retriever and generator **separately**. Fix retriever first.

**Retriever graders:**
| Grader                     | Type       | What It Checks                            |
|----------------------------|------------|-------------------------------------------|
| Recall@k                   | Code       | % of relevant docs in top k results       |
| Precision@k                | Code       | % of top k results that are relevant      |
| Source relevance            | LLM Judge  | Are retrieved docs actually useful?        |

**Generator graders:**
| Grader                     | Type       | What It Checks                            |
|----------------------------|------------|-------------------------------------------|
| Faithfulness               | LLM Judge  | Sticks to retrieved facts (no hallucination) |
| Answer relevance           | LLM Judge  | Addresses the user's actual intent        |
| Completeness               | LLM Judge  | Covers all key info from retrieved docs   |
| Citation accuracy          | Code       | References point to actual retrieved passages |

### Agentic Workflows

**Approach:** Go beyond pass/fail outcomes. Map the agent's decision chain.

1. Build a **transition failure matrix**: map agent states as assembly-line stages
2. Identify **hotspot transitions** where failures concentrate
3. Eval each tool call independently AND the orchestration logic
4. Grade outcomes, not paths — don't penalize valid alternative approaches

**Grader Recipe:**
| Grader                     | Type       | What It Checks                            |
|----------------------------|------------|-------------------------------------------|
| Outcome verification       | Code       | Final state matches expected state        |
| Tool call sequence         | Code       | Required tools called (order flexible)    |
| No forbidden calls         | Code       | Didn't call dangerous/wrong tools         |
| Reasoning quality          | LLM Judge  | Logical approach, good decision-making    |
| Efficiency                 | Code       | Steps taken, tokens used, latency         |
| Error recovery             | LLM Judge  | Handled errors gracefully                 |

### Coding Agents

**Approach:** Well-specified tasks with stable test environments.

**Grader Recipe:**
| Grader                     | Type       | What It Checks                            |
|----------------------------|------------|-------------------------------------------|
| Unit tests pass            | Code       | Generated code passes the test suite      |
| Static analysis            | Code       | Linting (ruff), type checking (mypy), security (bandit) |
| Code quality               | LLM Judge  | Readable, idiomatic, well-structured      |
| Behavior assessment        | LLM Judge  | Good tool usage, appropriate user interaction |
| Transcript metrics         | Code       | Turns, token usage, latency               |

**Anti-pattern:** Rigid grading that penalizes valid alternative solutions. Grade
whether the code WORKS, not whether it matches your expected implementation.

### Research Agents

**Challenge:** Experts may disagree on whether a synthesis is comprehensive.
Ground truth shifts as information changes.

**Grader Recipe:**
| Grader                     | Type       | What It Checks                            |
|----------------------------|------------|-------------------------------------------|
| Factual accuracy           | Code + LLM | Exact match for objective facts, LLM for nuance |
| Groundedness               | LLM Judge  | All claims supported by cited sources     |
| Coverage                   | LLM Judge  | Key topics and perspectives included      |
| Source quality              | LLM Judge  | Cited credible, relevant sources          |
| Coherence                  | LLM Judge  | Logical flow, well-structured             |

**Critical:** LLM-based rubrics for research should be frequently calibrated
against expert human judgment. What counts as "comprehensive" evolves.

---

## Tools

| Tool              | Type         | Best For                                          |
|-------------------|--------------|---------------------------------------------------|
| **Arize Phoenix** | Open Source   | Pre-built evaluators, tracing, no vendor lock-in  |
| **Ragas**         | Open Source   | RAG-specific eval metrics                         |
| **Promptfoo**     | Open Source   | Lightweight, YAML-based config, fast iteration    |
| **Langfuse**      | Open Source   | Self-hosted, data residency compliance            |
| **Harbor**        | Open Source   | Containerized environments, cloud-scale trials    |
| **Braintrust**    | Platform      | Eval management, logging, experiment tracking     |
| **LangSmith**     | Platform      | Tracing, datasets, online + offline eval          |

---

## Per-Product Tailoring Checklist

When applying this framework to a new product, fill in:

1. **Product context:** What does the AI feature do? Who are the users?
2. **Failure mode table:** Run Phase 1 on real/realistic data
3. **Test dataset:** Build using the 5-category template, mark maturity stage
4. **Eval criteria selection:** Pick from the standard library + add custom
5. **Grader combination strategy:** All-pass, weighted, or hybrid?
6. **Scoring approach:** Binary, partial credit, or per-component?
7. **Multi-trial plan:** How many trials per task? pass@k or pass^k?
8. **Error tolerance stance:** High-stakes or creative? TNR vs TPR priority
9. **Eval suite organization:** Which evals are capability vs. regression?
10. **Eval pipeline placement:** Where do evals run? What gates shipping?
11. **Trial isolation:** How are clean environments created per trial?
12. **Architecture playbook:** Conversation? RAG? Agents? Pick the grader recipe
13. **Swiss Cheese layers:** Which monitoring layers are active?
14. **Transcript review cadence:** Who reads transcripts and how often?
15. **Tools:** Which eval tooling fits your stack?
16. **Maintenance owner:** Who runs the weekly 30-min review?

---

## Quick Reference: The Core Mental Model

```
"Evals are the new PRDs"

  Traditional Software:  Requirements → Tests → Ship → Monitor
  AI Products:           Error Analysis → Evals → Ship → Monitor → Error Analysis → ...

The key difference: AI requirements EMERGE through the eval process.
People are bad at specifying AI requirements upfront.
The eval loop IS the requirements discovery process.

Capability evals push the frontier. Regression evals guard the baseline.
Multiple graders per task. Multiple trials per task. Read the transcripts.
No single layer catches everything — stack them (Swiss Cheese).
```

---

## One-Liner Summary

> Start from real user failures, build multi-grader evals with multiple trials,
> validate judges with TPR/TNR, read transcripts, graduate capability evals to
> regression, and run the loop weekly.
