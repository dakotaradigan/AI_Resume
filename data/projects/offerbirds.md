# OfferBirds: Agent-Native Hiring

## The Pitch

For decades, hiring has run on static documents: resumes as paper, then PDFs, then PDF uploads into applicant tracking systems. The tools changed but the model never did — candidates compress themselves into two pages, and recruiters skim those pages in seconds. Even most "AI hiring" today is just an LLM scanning the same PDF faster.

OfferBirds is Dakota's bet that agents change the model itself. Instead of a document, every candidate gets a hosted AI agent that represents them — one that recruiters, and recruiters' own AI tools, can actually interrogate: chat with it, run a job description against it for an honest fit analysis, connect to it over MCP. Hiring becomes a conversation with agents on both sides of the table — candidate agents that can advocate and be questioned in depth, and recruiting agents that can search and screen with real context — replacing the seconds-long PDF skim with genuine two-way matching: the right candidate finding the right employer.

When asked "what is OfferBirds," lead with this vision, then the mechanics.

## Status

OfferBirds is a side project Dakota is building in his free time. It is **in development and not live yet** — nothing is deployed publicly and it has no users. Frame it as "what Dakota is building," never as a launched product. Code: https://github.com/dakotaradigan/offerbirds

## How It Works

Dakota's own AI resume site (this one) is the proof of concept: recruiters chat with it, compare job descriptions against it, and connect their own AI tools to it over MCP. OfferBirds generalizes that into a platform — anyone uploads their resume and gets a hosted AI agent at their own handle (their personal subdomain), and shares that link instead of a PDF.

A recruiter opening someone's OfferBirds link can chat with an AI grounded in that person's actual background, paste a job description for a structured fit analysis, or download a PDF resume gated behind an owner-set access code — the same interaction model as Dakota's own site, available to everyone.

## What's Built So Far

The project is in its early build phase, ported carefully from the architecture of Dakota's single-tenant AI resume site:

- Multi-tenant RAG core: one deployment and one vector collection serve every user ("tenant"), with tenant filtering enforced inside the retrieval layer on every operation — a tenant-isolation regression test suite proves one tenant's data can never leak into another's answers
- Tenant-scoped session, quota, and budget storage
- Plan-aware model routing (free plans are capped and never route to the most expensive models)
- A local onboarding flow: sign in by email, upload or paste a resume, review the extracted profile, pick a handle, and publish an agent page
- Per-tenant endpoints for chat, JD fit analysis, resume JSON, llms.txt, and a tenant-scoped MCP server
- Synthetic seed tenants only — real resume data never lands in the repository

## Why It Matters

OfferBirds shows Dakota doing end-to-end product work in his spare time: taking a proven single-user concept, re-architecting it for multi-tenancy, and treating security and cost controls (tenant isolation, metered budgets, plan-based routing) as first-class product requirements rather than afterthoughts. It is product strategy, system design, and hands-on AI engineering in one project.

## Tech Stack

Python, FastAPI, PostgreSQL, Redis, Qdrant vector search, hybrid retrieval (semantic + BM25), Anthropic models with plan-aware routing, Alembic migrations, Docker, and per-tenant MCP endpoints.
