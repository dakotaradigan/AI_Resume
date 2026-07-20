# AI Resume

The resume that is alive. 

**[Try it live →](https://www.dakotaradigan.io/)**

---

## About

Traditional resumes are static PDFs that get skimmed in seconds. This is an AI-powered interactive resume where recruiters ask questions in natural language and get instant, contextual answers — powered by a RAG pipeline that searches across career data in real-time.

semantic search, vector databases, production guardrails, and a clean UI — built and deployed as a working product.

---

## Stack

**Claude** · **FastAPI** · **Qdrant** · **OpenAI Embeddings** · **Vanilla JS** · **Railway**

- Real SSE token streaming with a live pipeline status timeline
- Model router: a Haiku classifier sends simple lookups to Sonnet 5, synthesis to Opus 4.8, with fail-safe fallback
- Hybrid retrieval: dense vectors + in-process BM25 fused with reciprocal rank fusion, measured against an owner-approved golden dataset
- Recruiter tools: job-description fit analysis, screening briefs, password-gated PDF download
- Open interfaces: `/llms.txt` rendered live from resume data, MCP endpoint with a data-only `get_resume` tool
- Hardened: strict CSP, server-minted HttpOnly visitor quotas, atomic daily budgets, prompt-injection defense, HMAC-anonymized analytics
- Zero-dependency frontend (custom markdown parser, dark mode), CI test gate, Docker deploy

---

## Give it a shot

```bash
git clone https://github.com/dakotaradigan/AI_Resume.git
cd AI_Resume
pip install -r requirements.txt
cp backend/.env.example backend/.env
# Add your ANTHROPIC_API_KEY to backend/.env
cd backend && uvicorn main:app --reload
```

Open http://localhost:8000

Set `USE_RAG=false` in `.env` to run without vector search (no OpenAI/Qdrant keys needed).

Set `REDIS_URL` to use Railway Redis for shared sessions, rate limits, and daily counters across multiple app instances.

---

## Learn the RAG System

The [RAG technical learning handoff](docs/rag-learning-handoff.md) explains the
complete implementation: corpus construction, Qdrant vectors, in-process BM25,
RRF fusion, cold-start recovery, fallbacks, operations, tests, and evals.

---

## Make It Yours

1. Replace `data/resume.json` with your career data
2. Edit `data/system_prompt.txt` with your name and talking points
3. Update `frontend/index.html` hero section
4. Deploy to Railway and point your domain

---

**Built by [Dakota Radigan](https://linkedin.com/in/dakota-radigan)** · [dakotaradigan@gmail.com](mailto:dakotaradigan@gmail.com)
