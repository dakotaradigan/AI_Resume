# Resume Assistant

An AI-powered chatbot showcasing Dakota Radigan's professional experience, skills, and projects.

**Status**: Production-Ready | **Current Phase**: Deployment Pending | **Tech Showcase**: RAG + Vector Search + FastAPI

---

## Tech Stack

**Backend:**
- FastAPI (REST API with session management)
- Anthropic Claude Opus 4.5
- RAG Pipeline (Qdrant vector DB + OpenAI embeddings, toggleable via USE_RAG)
- Production guardrails (rate limiting, timeout protection, message compaction)

**Frontend:**
- Vanilla JavaScript (modular architecture)
- Custom CSS (Claude-inspired UI)

## What's Implemented

### Core Features
- **REST Chat API**: `POST /api/chat` with UUID-based session management
- **Frontend**: Claude-inspired UI served by backend at `http://127.0.0.1:8000/`
- **RAG Pipeline**: Semantic search with Qdrant + OpenAI embeddings (toggleable)
- **Health Endpoints**: `GET /health`, `GET /health/rag`

### Production Guardrails
- **Rate Limiting**: 20 requests/minute per IP with automatic cleanup
- **Session Management**: UUID-based with automatic expiration (1 hour default)
- **Message Compaction**: Summarizes old messages to prevent token exhaustion
- **Input Validation**: Message length limits (2000 chars), empty message checks
- **Timeout Protection**: 30s default timeout for API calls
- **Error Handling**: Graceful fallback from RAG to static context

### Security Features
- **Prompt Injection Defenses**: System prompt firewall with XML-style tags
- **XSS Protection**: HTML escaping in markdown parser
- **CORS Configuration**: Environment-aware allowed origins
- **Admin Endpoint Protection**: Token-based authentication for cache clearing

### UX Features
- **Markdown Rendering**: Rich text formatting in bot responses
- **Quick-Start Chips**: Suggested prompts for common queries
- **Professional Branding**: Terracotta accent colors, clean typography
- **Contact Links**: LinkedIn, GitHub, email in header
- **Auto-scroll**: Smooth scrolling to latest messages

## Deployment Readiness

**Status**: Production-Ready

The application is fully functional and ready for deployment:
- REST API tested and operational
- Frontend complete with professional UI
- RAG pipeline working with Qdrant Cloud support
- Security measures in place (rate limiting, prompt injection defenses)
- Scalability guardrails implemented (session cleanup, message compaction)

**Before Deployment:**
1. Configure environment variables (see `.env.example`)
2. Update CORS allowed origins in `backend/main.py:380`
3. Set up Qdrant Cloud instance (or Docker deployment)
4. Choose hosting platform (Railway, Render, Vercel)
5. Configure custom domain and SSL

See `CLAUDE.md` Phase 7 for detailed deployment checklist.

## Project Phases

- **Phase 1**: Foundation & Data Structure (Complete)
- **Phase 2**: Basic Chat with REST API (Complete)
- **Phase 3**: Vector Search (RAG Pipeline) (Complete)
- **Phase 4**: Multimodal Support (Removed - text-only approach)
- **Phase 5**: WebSocket Real-Time Communication (Optional - Not Started)
- **Phase 6**: Frontend Development (Complete - Polish Pending)
- **Phase 7**: Deployment & Public Access (Next Major Milestone)
- **Phase 8**: Post-Launch Enhancements (Future)

**Current Status**: Production-ready application at Phase 6, ready for deployment (Phase 7).

## Setup

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
# Create backend/.env (see env vars below)
uvicorn main:app --reload
```

#### Required environment variables

Create `backend/.env` with at least:

```bash
ANTHROPIC_API_KEY=...
```

Optional (recommended):

```bash
# App behavior
ENVIRONMENT=development
DEBUG=false

# Model config
ANTHROPIC_MODEL=claude-opus-4-5-20251101
ANTHROPIC_MAX_TOKENS=2048

# Abuse protection
RATE_LIMIT_REQUESTS_PER_MINUTE=20
SESSION_MAX_AGE_SECONDS=3600
API_TIMEOUT_SECONDS=30
MAX_USER_MESSAGE_CHARS=2000

# Admin endpoint protection (required in production)
ADMIN_TOKEN=...
```

#### RAG (Qdrant Cloud)

RAG is enabled by default (`USE_RAG=true`). It requires embeddings + a Qdrant endpoint; configure:

- `USE_RAG=true`
- `OPENAI_API_KEY=...` (for embeddings)
- `QDRANT_URL=...` (required for RAG)
- `QDRANT_API_KEY=...` (optional; needed for Qdrant Cloud)

To disable RAG and always use the local `data/resume.json` context:

- `USE_RAG=false`

### Frontend

**Recommended**: Backend serves the frontend at `/` (all-in-one deployment):

```bash
# Start backend (serves both API and frontend)
cd backend
uvicorn main:app --reload

# Open browser
open http://127.0.0.1:8000/
```

**Alternative**: Serve frontend separately (requires CORS configuration):

```bash
cd frontend
python3 -m http.server 3000
# Frontend will call backend at localhost:8000
```

Note: Separate serving requires updating `fetch()` calls in `app.js` to use full backend URL.

## Development

See `CLAUDE.md` for detailed development guide and architecture decisions.

### Tests

Offline unit tests (no OpenAI key required):

```bash
python3 -m unittest discover -s backend -p "test_*.py"
```

Optional integration test (uses real OpenAI embeddings; keep it off by default):

```bash
RUN_INTEGRATION=1 OPENAI_API_KEY=... python3 -m unittest backend/test_rag.py
```
