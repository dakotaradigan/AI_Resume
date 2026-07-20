# Work Packet — ChatGPT 5.6 sol (ultra)

> **Status: completed historical work packet.** Phase C and D3 shipped. Do not
> paste or execute this as a new assignment. Use
> `docs/rag-learning-handoff.md` and current source for the implemented system.

Paste everything below this line into ChatGPT (with repo access to `dakotaradigan/AI_Resume`), or hand it to a Codex session on that repo.

---

You are implementing two well-specified phases of an approved upgrade plan for the repository `dakotaradigan/AI_Resume`. The complete plan lives in the repo at **`docs/plans/production-upgrade-handoff.md`** on `main`. Phases A, B, and D are already merged to main and deployed; you are picking up Phase C and item D3. **Read that plan file first, in the order its intro specifies** — Context, Codebase orientation, Process contract, Global rules — then implement ONLY the sections assigned to you below. Another model is implementing the other phases in parallel; staying inside your assigned scope is what prevents merge conflicts.

## Your assignment

1. **Phase C — RAG as credible showcase** (the plan's Phase C, all of C1–C4 including its ⚠ Pitfalls section):
   - `chunk_project_docs` + `build_corpus` in `backend/rag.py`; index `data/projects/*.md` (expect ~20–24 total chunks, not 30).
   - In-process BM25 + RRF hybrid `search`, including the mandatory cold-start keyword-index rebuild via Qdrant `scroll` (paginate!).
   - Tuning `limit=4`, vector threshold `0.30`; static-context fallback preserved.
   - `evals/scripts/run_retrieval_eval.py` (committed) + dataset schema note in `evals/datasets/README.md`. **HARD STOP: the golden dataset itself requires Dakota's review and sign-off before you run or cite any numbers — draft it from the ACTUAL chunk titles `build_corpus` prints, present it, and wait.** Never commit anything under `evals/datasets/` or `evals/results/`.
   - Offline unit tests in `backend/test_rag.py` style (mocked embeddings, no network).
2. **Phase D3 — CI + deployment config** (the plan's D3 only):
   - `.github/workflows/ci.yml` (ruff + `PYTHONPATH=backend USE_RAG=false python -m unittest discover -s backend -p 'test*.py' -v`), minimal `pyproject.toml` `[tool.ruff]` (py312, line-length 100, `I`), fix any ruff findings **in files you own** — if ruff flags files outside your scope (main.py, app.js-adjacent), add a per-file ignore and leave a PR note instead of editing them.
   - `Dockerfile` (python:3.12-slim, uvicorn honoring `$PORT`), `railway.json` with DOCKERFILE builder, `.dockerignore` per the plan.

## Hard boundaries (conflict avoidance)

- **Branch**: create `codex/rag-showcase-ci` from the latest default branch. Never push to main; open one PR per phase (C first, then D3, or two independent PRs — D3 does not depend on C).
- **Files you may modify**: `backend/rag.py`, `backend/test_rag.py`, `backend/main.py` ONLY at the two RAG call sites the plan names (retrieval `limit`/`score_threshold` values and the `projects_dir` parameter threading), `evals/scripts/`, `evals/datasets/README.md`, `evals/APP_EVAL_PLAN.md`, plus the new root files (`.github/workflows/ci.yml`, `pyproject.toml`, `Dockerfile`, `railway.json`, `.dockerignore`).
- **Files you must NOT touch**: `frontend/*` (all of it), `data/system_prompt.txt`, `backend/config.py`, everything else in `backend/main.py`. The other model owns those right now.
- Follow the repo's `AGENTS.md` and `CLAUDE.md`: smallest production-quality change, type hints, no `Co-Authored-By` AI lines, commits authored by Dakota Radigan, PRs never direct pushes to main.
- If anything in the plan is impossible or contradicts what you find in the code: **STOP and report to Dakota with options** — do not improvise a redesign (plan Process contract rule 4).

## Definition of done

Phase C's C4 checklist and the D3 items in the plan's D4 checklist (docker build/run works; CI red on a broken test, green after revert), plus: full unittest suite green offline, app boots with RAG env unset, and your PR bodies list which plan items each commit satisfies.
