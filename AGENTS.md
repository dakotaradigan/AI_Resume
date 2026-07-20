# AGENTS.md

Model-agnostic working guide for AI coding agents in this repository.

## Project Overview

Resume Assistant is an interactive AI resume site for Dakota Radigan. It serves a static frontend from a FastAPI backend, answers recruiter-style questions through an LLM, and can optionally retrieve focused context from a Qdrant vector database using OpenAI embeddings.

Live site: https://chat.dakotaradigan.io

Primary goals:
- Help recruiters and hiring managers explore Dakota's background faster than a static PDF.
- Showcase practical AI product engineering: RAG, vector search, guardrails, evals, and clean web delivery.
- Keep the implementation simple, production-quality, and easy to inspect.

## Architecture

Backend:
- `backend/main.py`: FastAPI app, routes, session storage, rate limits, chat flow, admin endpoints, static frontend mount.
- `backend/config.py`: environment-backed settings.
- `backend/rag.py`: Qdrant/OpenAI embedding pipeline.
- `backend/analytics/analytics.py`: local/Redis analytics logging and export helpers.
- `backend/test_rag.py`: unit tests plus optional Qdrant integration test.

Frontend:
- `frontend/index.html`: static page shell.
- `frontend/app.js`: chat UX, resume rendering, feedback UI, markdown rendering.
- `frontend/styles.css`: visual system and responsive layout.

Data and evals:
- `data/resume.json`: structured public resume source data.
- `data/system_prompt.txt`: system prompt used for chat responses.
- `data/projects/*.md`: detailed project notes indexed into the RAG corpus by `build_corpus`.
- `evals/`: eval framework, judge prompts, scripts, datasets, and results.

## Local Run

```bash
pip install -r requirements.txt
cp backend/.env.example backend/.env
cd backend
uvicorn main:app --reload
```

Open http://localhost:8000.

## Tests

Run backend tests:

```bash
./venv/bin/python -m unittest discover -s backend -p 'test*.py'
```

Run the Qdrant integration test only when a reachable vector database is configured:

```bash
RUN_INTEGRATION=1 QDRANT_URL="$QDRANT_URL" ./venv/bin/python -m unittest backend.test_rag
```

## Environment

Required for chat:
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `ANTHROPIC_MAX_TOKENS`

Model routing (optional, defaults provided):
- `ANTHROPIC_MODEL_SIMPLE` — answers simple factual queries
- `ANTHROPIC_ROUTER_MODEL` — small classifier that picks the tier

Optional RAG:
- `USE_RAG=true`
- `OPENAI_API_KEY`
- `QDRANT_URL`
- `QDRANT_API_KEY`

Optional infrastructure and controls:
- `REDIS_URL`
- `ADMIN_TOKEN`
- `CHAT_PASSWORD`
- `FREE_CHAT_LIMIT`
- `PER_IP_DAILY_LIMIT` (per-client-IP daily cap on token-spending requests; needs `TRUST_PROXY_HEADERS=true` to take effect)
- `RATE_LIMIT_REQUESTS_PER_MINUTE`
- `SESSION_MAX_AGE_SECONDS`
- `API_TIMEOUT_SECONDS`
- `MAX_USER_MESSAGE_CHARS`
- `MAX_JD_CHARS` / `JD_DAILY_LIMIT` (JD fit analysis)
- `VISITOR_COOKIE_NAME` / `VISITOR_TTL_SECONDS` (server-minted quota identity)
- `SESSION_HASH_SECRET` (stable HMAC key for anonymized analytics ids; set in production)
- `ENVIRONMENT`
- `DATA_DIR`

Without `REDIS_URL`, sessions/quotas are in-memory per process and reset on
restart — that is the supported dev mode. See `docs/redis-integration.md` for
how the Redis backend hooks in.

Do not print, copy, or commit real values from `backend/.env`.

## RAG / Vector Database

RAG is enabled only when `USE_RAG=true`, `OPENAI_API_KEY` is set, and `QDRANT_URL` is set. Startup attempts to initialize `RAGPipeline`; if that fails, the app logs the failure and falls back to static resume context.

Before assuming vector search is live:
- Check `/health/rag`.
- Verify the configured Qdrant endpoint is reachable.
- Verify the `resume` collection exists and has points.
- Confirm a chat response returns `used_rag=true` and source titles when relevant.

Startup performs a best-effort title/text drift check and auto-reindexes when a
new process finds changed source data. Use `/admin/rag/reindex` when a running
deployment must refresh immediately. Admin endpoints must stay protected.

## Update Workflow

When updating resume or prompt content:
1. Edit `data/resume.json` or `data/system_prompt.txt`.
2. If RAG is disabled, restart the backend or call `/admin/cache/clear`.
3. If RAG is enabled, reindex Qdrant when source data should update retrieval.
4. Test locally.
5. Open a PR for review instead of pushing directly to main.

## Engineering Standards

Simple wins over complex:
- Prefer the smallest production-quality change that solves the problem.
- Delete dead code instead of commenting it out.
- Avoid abstractions for single-use cases.
- Avoid broad configuration knobs nobody will use.
- Keep functions and files easy to understand without external context.

Code quality:
- Use clear names and specific error messages.
- Add comments only to explain non-obvious reasons, not obvious behavior.
- Keep frontend dependency-free unless there is a strong reason to change that.
- Use type hints in Python where they improve clarity.
- Keep changes reviewable and closely scoped.

Security and privacy:
- Never expose secrets from `.env`.
- Treat analytics logs and eval datasets/results as sensitive user data.
- Do not commit generated analytics, local caches, `.DS_Store`, virtualenvs, or ignored eval artifacts.
- Avoid query-string admin tokens; prefer `X-Admin-Token`.
- Keep admin endpoints authenticated in deployed environments.
- Do not trust `X-Forwarded-For` unless a trusted proxy overwrites it.
- Keep dependencies current, especially FastAPI, Starlette, and multipart/form parsing packages.
- Preserve XSS protections in the frontend markdown rendering path.

## Git Policy

- Default to a PR instead of pushing directly to main.
- Ask before pushing to main, including hotfixes.
- Before adding commits to an existing branch, check whether its PR was already merged.
- Do not add `Co-Authored-By` lines for AI assistants.
- All commits should be authored by Dakota Radigan unless the user explicitly asks otherwise.

## Evals

The eval framework lives under `evals/`. For eval work, read:
- `evals/CLAUDE.md`
- `evals/docs/CORE_MENTAL_MODEL.md`
- Relevant docs in `evals/docs/`

Judge prompts and eval scripts are code and should be included in commits/PRs. Dataset and result files may contain PII and are gitignored; never commit files in `evals/datasets/` or `evals/results/` without explicit approval.

`evals/scripts/run_retrieval_eval.py` initializes the configured `resume`
collection and may destructively auto-reindex it on drift. It has no collection
override: never run it with production Qdrant credentials. Require owner
approval for the dataset revision and use an isolated non-production cluster.

To export production analytics for evals, use the admin header:

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" "https://chat.dakotaradigan.io/admin/analytics/export?file=queries" > evals/datasets/production_queries.jsonl
curl -H "X-Admin-Token: $ADMIN_TOKEN" "https://chat.dakotaradigan.io/admin/analytics/export?file=feedback" > evals/datasets/production_feedback.jsonl
```

## Current Status

Production-deployed portfolio app with:
- FastAPI backend and static frontend.
- Configurable Anthropic chat model.
- Optional Qdrant/OpenAI RAG pipeline with static-context fallback.
- Session handling, message compaction, rate limiting, chat unlock flow, and analytics export.
- Evals framework with judge prompts and historical result artifacts.
