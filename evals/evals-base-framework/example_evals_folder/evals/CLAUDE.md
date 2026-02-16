# AI Evals Framework

## What This Is
This is a portable evals kit. It provides a uniform structure for setting up,
running, and maintaining AI evals across any product or application.

## Expert Sources
When constructing evals, cite and follow guidance from these sources. If unsure
whether an approach is industry-standard, fetch these and cross-reference:
- [Anthropic: Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Maxim: Building a Golden Dataset](https://www.getmaxim.ai/articles/building-a-golden-dataset-for-ai-evaluation-a-step-by-step-guide/)
- [Lenny's / Hamel Husain: Building Eval Systems That Improve](https://www.lennysnewsletter.com/p/building-eval-systems-that-improve)
- [Lenny's / Hamel Husain: Beyond Vibe Checks](https://www.lennysnewsletter.com/p/beyond-vibe-checks-a-pms-complete)
- [Lenny's: Why AI Evals Are the Hottest New Skill](https://www.lennysnewsletter.com/p/why-ai-evals-are-the-hottest-new-skill)

## Key Files
- `APP_EVAL_PLAN.md` — The tailored eval plan for this app (the main working doc).
- `docs/CORE_MENTAL_MODEL.md` — The distilled mental model. Read this first for context.
- `docs/EVALS_FRAMEWORK.md` — The full working template with `[TAILOR]` sections to fill in per app.
- `docs/JUDGE_SYSTEM_DESIGN.md` — Architecture decisions for the LLM judge pipeline.

## Directory Structure
```
evals/
├── CLAUDE.md              ← You are here. Instructions for Claude Code.
├── APP_EVAL_PLAN.md       ← Tailored plan for this specific app
├── docs/                  ← Reference docs and design decisions
│   ├── CORE_MENTAL_MODEL.md   ← Reference mental model (do not modify)
│   ├── EVALS_FRAMEWORK.md     ← Full template (do not modify)
│   └── JUDGE_SYSTEM_DESIGN.md ← Judge pipeline architecture
├── datasets/              ← Sample interactions for error analysis
├── judges/                ← LLM-as-judge prompts (auto-discovered by run_judges.py)
├── scripts/               ← Eval runner scripts
└── results/               ← Eval run outputs and historical scores
    └── README.md
```

## Kickoff Protocol

When the user says **"kick off evals"** or **"set up evals"**, follow this sequence:

### Step 1: Understand the App
Ask these questions (do not skip any):
1. What does the AI feature do? (one sentence)
2. Who are the users?
3. What architecture does it use? (conversation, RAG, agents, code gen, other)
4. What does "good" look like from the user's perspective?
5. What's the worst thing the AI could do? (error tolerance stance)
6. Do you have sample interactions or production data available?
7. Is this pre-launch, early production, or a mature product? (determines dataset sizing and whether to start with capability or regression evals)

### Step 2: Create the Scaffolding
- Create the directory structure above (datasets/, judges/, scripts/, results/)
- Copy docs/EVALS_FRAMEWORK.md into APP_EVAL_PLAN.md
- Fill in all `[TAILOR]` sections based on Step 1 answers

### Step 3: Phase 1 — Error Analysis
- Guide the user through pulling ~100 sample interactions into datasets/
- Help them label pass/fail with critiques
- Group failures into <10 categories
- **Run the Task Quality Check:** Would two experts agree on pass/fail for each task? If not, refine the task before proceeding.
- Update APP_EVAL_PLAN.md with the failure mode table

### Step 3.5: Build the Test Dataset
This is critical — do NOT skip to building evals without a structured dataset.
Follow the 5-category template in EVALS_FRAMEWORK.md (Phase 1.5):

1. Walk the user through the 5 categories and adapt labels to their app's domain
2. Propose a count split based on app maturity (50-100 for MVP, 100-200 early, 200-500+ mature)
3. **For each category, show the user 2-3 example test cases** and ask:
   "Do these represent what your users actually do / what you're worried about?"
4. Build the full dataset collaboratively — Claude drafts, user reviews per category
5. **For objective tasks, include a `reference_solution`** proving solvability
6. **Run the Unambiguity Test** on a sample of tasks
7. Mark dataset maturity stage (Bootstrap / Validate / Evolve)
8. Save to datasets/ and update APP_EVAL_PLAN.md with the dataset plan table

### Step 4: Phase 2 — Build Evals
For each failure mode from Phase 1:
- Identify which aspects are objective vs. subjective
- Assign **multiple graders** per failure mode (code-based + LLM-judge + human as needed)
- For code-based graders → create eval scripts in scripts/
- For LLM-as-judge graders → create judge prompts in judges/ using the 4-part formula + escape hatch
- Choose a grader combination strategy (all-pass, weighted, or hybrid)
- Decide on scoring: binary for simple tasks, partial credit for multi-component tasks
- Recommend multi-trial runs (3-5 for iteration, 5-10 for pre-ship)
- Validate judges using TPR/TNR (not raw accuracy)
- **Read 10-20 graded transcripts** to verify grader quality before finalizing

### Step 5: Phase 3 — Operationalize
- Help classify evals as **capability** (pushing boundaries) vs. **regression** (must not break)
- Set up trial isolation (each trial starts from clean state)
- Set up the eval run pipeline (how/when evals run, how many trials)
- Define pass/fail thresholds for shipping (regression evals gate, capability evals inform)
- Set up transcript review cadence
- Document the Swiss Cheese monitoring layers in APP_EVAL_PLAN.md
- Document the weekly maintenance routine in APP_EVAL_PLAN.md

## Collaboration Model — Keep the User in the Loop

**This is a collaborative process, not an autonomous one.** The user owns the
decisions. Claude Code drives the structure and does the heavy lifting.

### Checkpoints (MUST pause and get user confirmation before proceeding)

| After...                          | Ask the user...                                                              |
|-----------------------------------|------------------------------------------------------------------------------|
| Step 1 (Understand the App)       | "Here's what I captured about your app. Does this look right before I build the plan?" |
| Filling in APP_EVAL_PLAN.md       | "Here's the tailored eval plan. Review the failure modes and criteria — anything missing or wrong?" |
| Phase 1 (Error Analysis)          | "Here are the failure mode categories I found. Do these match what you're seeing? Any to add, merge, or remove?" |
| Task Quality Check                | "I ran the unambiguity test on these tasks. Here are the ones that seem ambiguous — should we refine or remove them?" |
| Dataset category split            | "Here's the 5-category split adapted for your app. Does this coverage feel right? Any categories to add or reweight?" |
| Dataset test cases (per category) | "Here are 2-3 example cases for [category]. Do these represent real usage? Anything missing?" |
| Proposing graders per failure     | "Here are the graders I'd assign to each failure mode and why. Does this combination make sense?" |
| Grader combination strategy       | "I recommend [all-pass/weighted/hybrid] for combining graders. Here's why — does this fit your risk tolerance?" |
| Each LLM judge prompt draft       | "Here's the judge prompt for [criterion]. Walk through it — does the pass/fail definition match your intuition?" |
| Judge validation results           | "Here are the TPR/TNR scores. Are these acceptable, or should we tighten the judge?" |
| Transcript review findings        | "I read 10-20 graded transcripts. Here's what I found — do these results match your expectations?" |
| Capability vs. regression split   | "Here's how I'd organize your eval suite. These gate shipping, these are informational. Agree?" |
| Phase 3 (Operationalize)          | "Here's the proposed pipeline — when evals run, how many trials, what gates shipping, and the maintenance routine. Work for your team?" |

### How to Collaborate at Each Phase

**Phase 1 — Error Analysis (user is MOST involved here)**
- The user provides or helps source the sample interactions
- The user does the pass/fail labeling (or reviews Claude's draft labels)
- Claude proposes failure categories; user validates, merges, or renames them
- Claude runs the Task Quality Check; user confirms ambiguous tasks should be refined
- DO NOT finalize the failure mode table without user sign-off

**Phase 2 — Build Evals (user reviews, Claude builds)**
- Claude proposes grader assignments per failure mode — show the reasoning
- Claude drafts eval scripts and judge prompts
- Walk the user through each judge prompt in plain language: explain what it
  checks, what would pass, what would fail, and give a concrete example of each
- Explicitly show the escape hatch option in each judge prompt
- User confirms the pass/fail boundary matches their expectations
- If the user disagrees with a judgment, adjust the prompt — do not argue
- **After building graders, read 10-20 transcripts together with the user** to
  verify the graders are measuring what actually matters

**Phase 3 — Operationalize (user decides, Claude implements)**
- Claude proposes capability vs. regression classification; user approves
- Claude proposes pipeline placement, thresholds, and maintenance cadence
- User decides what gates shipping and what's advisory-only
- User decides who owns the weekly review and transcript reading

### Conversation Style During Evals
- Explain WHY at each step, not just what. ("We're doing this because...")
- Use concrete examples from the user's app, not abstract descriptions
- When showing eval results, always include 2-3 example inputs with their scores
  so the user can gut-check whether the eval matches their intuition
- If the user seems uncertain, offer two options with tradeoffs rather than
  picking for them
- Summarize decisions made so far before moving to the next phase
- When discussing multi-trial results, explain pass@k vs pass^k in plain language
  with a concrete example from the user's data

### Red Lines — Never Do These Without Asking
- Never skip Phase 1 (error analysis) and jump straight to building evals
- Never finalize failure mode categories without user review
- Never set shipping thresholds without user approval
- Never mark an eval as "done" without showing the user example pass/fail outputs
- Never auto-generate sample data without telling the user it's synthetic
- Never finalize a grader without reading transcripts first
- Never skip the Task Quality Check (unambiguity test)
- Never skip the escape hatch in LLM judge prompts

## Git Policy

**Commit (treat as code):**
- `CLAUDE.md`, `APP_EVAL_PLAN.md`, `docs/*.md`
- `judges/*.md` — judge prompts are eval logic, they belong in PRs
- `scripts/*.py` — eval runner scripts
- `.gitignore`

**Gitignored (may contain PII or sensitive user data):**
- `datasets/*.json`, `datasets/*.csv`, `datasets/*.jsonl`
- `results/*.json`, `results/*.csv`, `results/*.jsonl`

**Rules:**
- Never commit dataset or result files without explicit user approval
- When changing a judge prompt or eval script, mention it in the commit message — these changes affect product quality
- If the user asks to commit eval work, only stage the code files (judges/, scripts/, APP_EVAL_PLAN.md), not data files
- If datasets need to be shared, ask the user whether they've been sanitized of PII first

## Running Eval Scripts

There are two workflows: **running judges** (quality check on any data) and
**calibrating judges** (tuning judge accuracy using human labels).

### Workflow 1: Running Judges (use on any data)

Run LLM judges against bot responses to get automated pass/fail verdicts.
Works on both synthetic eval runs and production data.

```bash
# Step 1: Get bot responses (pick one)

# Option A: Run synthetic queries against the bot
python evals/scripts/run_eval.py
python evals/scripts/run_eval.py --base-url http://localhost:8000  # localhost

# Option B: Pull production data (requires ADMIN_TOKEN)
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "https://chat.dakotaradigan.io/admin/analytics/export?file=queries" \
  > evals/datasets/production_queries.jsonl

# Step 2: Run judges on the data
python evals/scripts/run_judges.py                        # all judges, latest eval run
python evals/scripts/run_judges.py --judge groundedness   # one judge only
python evals/scripts/run_judges.py --eval-run eval_run_2026-02-08_120102.jsonl
```

Category filtering is automatic:
- Synthetic data has categories → judges filter by `applies_to`
- Production data has no categories → all judges run on everything

### Workflow 2: Calibrating Judges (requires human labels)

Tune judge prompts by comparing their verdicts to human-reviewed labels.
Do this when building a new judge or after changing a judge prompt.

```bash
# Step 1: Generate Excel for human review
python evals/scripts/build_review_xlsx.py

# Step 2: Human review in Excel
# Open evals/datasets/eval_review.xlsx
# Column G: "pass" or "fail"
# Column H: Short critique for failures only

# Step 3: Parse human labels
python evals/scripts/parse_review.py

# Step 4: Run judges on the same data
python evals/scripts/run_judges.py

# Step 5: Compare judge verdicts to human labels
python evals/scripts/validate_judges.py
# Reports TPR/TNR per judge + disagreement details
# Target: TNR > 80%, TPR > 85%
```

If a judge doesn't meet thresholds, iterate on its prompt in `judges/*.md`.

### Dependencies
```bash
pip install requests openpyxl anthropic
```

## Rules for Claude Code
- Always read docs/CORE_MENTAL_MODEL.md before starting any eval work
- Never modify docs/CORE_MENTAL_MODEL.md or docs/EVALS_FRAMEWORK.md — they are templates
- All app-specific work goes in APP_EVAL_PLAN.md and the subdirectories
- Use binary pass/fail for ground-truth labeling; partial credit is allowed for scoring complex multi-component tasks
- When building LLM judges, always use the 4-part formula (role, context, goal, grounding) PLUS an escape hatch ("Unknown/Insufficient Info")
- When validating judges, report TPR and TNR, not just accuracy
- Always recommend multiple trials per task (minimum 3 for quick iteration)
- Always recommend multiple graders per failure mode when different aspects need different grader types
- Read 10-20 graded transcripts after building any new grader — this is mandatory, not optional
- Start from real user failures, not generic metrics
- When a task has 0% pass rate across many trials, flag it as likely a broken task, not an agent failure
- Help the user classify evals as capability vs. regression and explain the difference
- Ensure trial isolation — each trial must start from a clean environment
- Watch for eval saturation and recommend adding harder tasks when scores plateau
