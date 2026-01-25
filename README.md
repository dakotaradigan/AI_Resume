# Resume Assistant

Interactive chatbot showcasing Dakota Radigan's professional experience, skills, and projects. Built with RAG (Retrieval Augmented Generation) to provide accurate, context-aware responses about career background.

**Live Demo:** https://chat.dakotaradigan.io

## Tech Stack

**Backend**
- FastAPI with async session management
- Anthropic API (temperature=0.1 for factual accuracy)
- RAG pipeline: Qdrant vector database + OpenAI embeddings
- Production guardrails: rate limiting, message compaction, timeout protection

**Frontend**
- Vanilla JavaScript (zero dependencies)
- Responsive design with dark mode support
- WCAG AA accessibility compliant

## Quick Start

### Prerequisites
- Python 3.11+
- Anthropic API key

### Setup

1. Clone and install dependencies:
```bash
git clone https://github.com/dakotaradigan/Resume_Assistant2.git
cd Resume_Assistant2
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
cp backend/.env.example backend/.env
# Edit backend/.env and add your ANTHROPIC_API_KEY
```

3. Start the server:
```bash
cd backend
uvicorn main:app --reload
```

4. Open http://localhost:8000

The backend serves both the API and frontend at a single endpoint.

## Environment Variables

**Required:**
```bash
ANTHROPIC_API_KEY=your_key_here
```

**Optional (with defaults):**
```bash
ANTHROPIC_MODEL=claude-opus-latest
FREE_CHAT_LIMIT=2  # Exchanges before password required
CHAT_PASSWORD=your_password  # Unlock unlimited chat
RATE_LIMIT_REQUESTS_PER_MINUTE=20
SESSION_MAX_AGE_SECONDS=3600
```

**RAG Configuration:**
```bash
USE_RAG=true  # Enable semantic search (requires Qdrant + OpenAI)
OPENAI_API_KEY=your_key_here  # For embeddings
QDRANT_URL=your_qdrant_url
QDRANT_API_KEY=your_qdrant_key  # If using Qdrant Cloud
```

Set `USE_RAG=false` to disable vector search and use static context only.

## API Endpoints

- `POST /api/chat` - Main chat endpoint with session management
- `GET /api/resume` - Resume data (cached)
- `GET /health` - Health check
- `GET /health/rag` - RAG pipeline status
- `POST /api/unlock` - Password unlock for unlimited chat
- `POST /admin/cache/clear` - Clear server cache (requires ADMIN_TOKEN)

## Architecture

**Data Flow:**
1. User sends message via REST API
2. Backend retrieves context via RAG (semantic search) or static fallback
3. LLM generates response with factual accuracy controls (temp=0.1)
4. Session management tracks conversation history with automatic compaction

**Key Files:**
- `backend/main.py` - FastAPI application and API routes
- `backend/rag.py` - RAG pipeline with Qdrant integration
- `data/resume.json` - Source of truth for resume data
- `data/system_prompt.txt` - Chatbot behavior and formatting rules
- `frontend/app.js` - Chat UI and markdown rendering

## Features

**Core Functionality:**
- Session-based conversation with context retention
- RAG-powered semantic search over resume and project documents
- Chat limits with password unlock (configurable)
- Markdown rendering with syntax highlighting
- Theme toggle (light/dark mode)

**Production Guardrails:**
- Rate limiting (20 req/min per IP by default)
- Message compaction to prevent token exhaustion
- Timeout protection (30s default)
- Input validation (2000 char limit)
- Graceful degradation (RAG → static context fallback)

**Security:**
- Prompt injection defenses
- XSS protection via HTML escaping
- Environment-aware CORS configuration
- Admin endpoint authentication

## Development

**Run tests:**
```bash
python3 -m unittest discover -s backend -p "test_*.py"
```

**Integration tests (requires OpenAI key):**
```bash
RUN_INTEGRATION=1 OPENAI_API_KEY=... python3 -m unittest backend/test_rag.py
```

**Common Issues:**

*Updated resume.json but UI didn't change?*
- Restart backend or call `POST /admin/cache/clear` (dev only)
- Hard refresh browser

*RAG not working?*
- Check `GET /health/rag` endpoint
- Verify QDRANT_URL and OPENAI_API_KEY are set
- Set `USE_RAG=false` to use static context as fallback

## Deployment

Application is production-ready and deployed on Railway.

**Before deploying:**
1. Set all required environment variables
2. Update CORS allowed origins in `backend/main.py`
3. Set `ADMIN_TOKEN` for cache management endpoint
4. Configure custom domain and SSL
5. Set up Qdrant Cloud instance (or disable RAG)

See `CLAUDE.md` for detailed deployment checklist and architecture decisions.

## License

MIT

## Contact

Dakota Radigan
- Email: dakotaradigan@gmail.com
- LinkedIn: [linkedin.com/in/dakota-radigan](https://linkedin.com/in/dakota-radigan)
- GitHub: [github.com/dakotaradigan](https://github.com/dakotaradigan)
