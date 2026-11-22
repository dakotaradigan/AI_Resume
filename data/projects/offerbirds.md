# OfferBirds: Agent-Native Hiring

## The Pitch

For decades, hiring has run on static documents: resumes as paper, then PDFs, then PDF uploads into applicant tracking systems. The tools changed but the model never did — candidates compress themselves into two pages, and recruiters skim those pages in seconds. Even most "AI hiring" today is just an LLM scanning the same PDF faster.

OfferBirds is Dakota's bet that agents change the model itself. Instead of a document, every candidate gets a hosted AI agent that represents them — one that recruiters, and recruiters' own AI tools, can actually interrogate: chat with it, run a job description against it for an honest fit analysis, connect to it over MCP. Hiring becomes a conversation with agents on both sides of the table — candidate agents that can advocate and be questioned in depth, and recruiting agents that can search and screen with real context — replacing the seconds-long PDF skim with genuine two-way matching: the right candidate finding the right employer.

When asked "what is OfferBirds," lead with this vision, then the mechanics.

## Status

OfferBirds is a side project Dakota builds in his free time. It is not an employer: his only employer is Parametric Portfolio (Morgan Stanley).

It has been **live in production since September 2026** at https://offerbirds.com, running on Railway with Postgres and Redis, in **prelaunch mode**: the landing page is public, sign-up is limited to an early-access list, and it does not charge money yet. Describe it as "live in prelaunch," never as a public launch, and never claim user numbers. It is feature-complete for a closed beta and finishing a Production Readiness v1 milestone before public signup opens.

## How It Works

Dakota's own AI resume site (this one) is the proof of concept: recruiters chat with it, compare job descriptions against it, and connect their own AI tools to it over MCP. OfferBirds generalizes that into a platform — anyone uploads their resume and gets a hosted AI agent at their own handle (their personal subdomain), and shares that link instead of a PDF.

A recruiter opening someone's OfferBirds link can chat with an AI grounded in that person's actual background, paste a job description for a structured fit analysis, or download a PDF resume gated behind an owner-set access code — the same interaction model as Dakota's own site, available to everyone.

## The Product Today

- **Onboarding**: sign in with a magic link or Google, upload a resume (PDF, Word, or pasted text), review and edit the AI-extracted profile, pick a handle, and publish an agent at {handle}.offerbirds.com
- **The agent page**: chat grounded in the person's background, job description fit analysis, an access-code-gated PDF resume, llms.txt, and eight page themes
- **Recruiter-side agents**: each agent has its own MCP server (get_resume, ask, analyze_fit), so a recruiter can load several candidates' agents into one AI chat and compare them
- **Owner dashboard**: visitor analytics and usage, a private "Test your bird" chat to check answers against the draft profile before publishing, profile photo, and settings for personality, look, and privacy
- **Publishing model**: each publish is an immutable snapshot with its own staged search index, so a half-finished edit never reaches visitors

## Architecture

- **Multi-tenant RAG**: one deployment and one Qdrant collection serve every user ("tenant"), with tenant filtering enforced inside the retrieval layer on every operation. A cross-tenant leak test suite proves one tenant's data never reaches another's answers. Retrieval is hybrid: vector search fused with BM25 keyword search.
- **Data**: PostgreSQL with Alembic migrations (run automatically before each deploy), Redis for tenant-scoped sessions, quotas, budgets, and token metering
- **Synthetic data only in the repo**: real resume data never lands in the codebase

## Cost Controls

Dakota treats AI cost as a product requirement, not an afterthought:
- Plan-aware model routing: free plans can never reach the most expensive model
- Prompt caching on every model call site: about 90% fewer repeated input tokens, cutting a chat turn's cost by about 55-60%
- Per-call token budgets, input-size caps, metered quotas, and an AI policy module with a concurrency ceiling, a circuit breaker, and spend estimates

## Production Readiness

Before opening public signup, Dakota is running a full production-readiness program:
- Security: a written threat model, CSP hardening, CSRF origin checks, and pip-audit, bandit, gitleaks, and Trivy scans in CI
- Privacy: a data-retention program with scheduled jobs, plus account deletion that removes a tenant across Postgres, Qdrant, Redis, and caches, with a verification sweep
- Operations: 14 incident runbooks, metrics and alert thresholds, load testing, failure-injection testing, a log-redaction audit, and an uptime probe
- Quality: 500+ automated tests, browser tests at phone width with accessibility checks, and a prompt-injection test suite
- Evals: a golden-set eval harness that records and replays model calls (25 synthetic resumes, 40 chat cases, 20 job-fit cases) with blocking thresholds in CI. The first recordings are still pending, so there are no eval results to report yet.

## Why It Matters

OfferBirds shows Dakota doing end-to-end product work in his spare time: taking a proven single-user concept, re-architecting it for multi-tenancy, shipping it to production, and treating security, privacy, and cost controls as first-class product requirements. It is product strategy, system design, and hands-on AI engineering in one project.

## Tech Stack

Python, FastAPI, PostgreSQL, Alembic, Redis, Qdrant vector search, hybrid retrieval (vector + BM25), Anthropic Claude models with plan-aware routing and prompt caching, per-tenant MCP servers, Docker, Railway, and GitHub Actions CI.
