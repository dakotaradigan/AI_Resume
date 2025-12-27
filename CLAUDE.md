# CLAUDE.md

This file provides development guidance for the Resume Assistant chatbot project.

## CRITICAL: This is a NEW Project

**IMPORTANT**: This is a completely NEW chatbot project for Dakota's personal resume/portfolio.

**DO NOT:**
- Copy code from other projects (e.g., Ben AI chatbot in Documents folder)
- Reference other codebases except for learning architectural patterns
- Assume implementations from other projects apply here

**DO:**
- Build everything from scratch for THIS use case
- Reference other projects ONLY to understand patterns (e.g., "Ben AI used FastAPI, we can use that framework too")
- Ask before making assumptions based on other codebases

**Ben AI chatbot** exists in `/Users/dakotaradigan/Documents/chatbot_benai_enhanced_UI/` and can be referenced for:
- Understanding FastAPI structure
- Learning WebSocket patterns
- Seeing UI component organization
BUT: Do NOT copy code directly - this is a different use case with different requirements.

---

## Project Overview

**Resume Assistant** is a personal AI-powered chatbot designed to showcase Dakota Radigan's professional experience, skills, and projects to recruiters and hiring managers. This serves dual purposes:
1. **Functional**: Provide an interactive way for visitors to learn about Dakota's background
2. **Technical Showcase**: Demonstrate expertise in RAG (Retrieval Augmented Generation), vector search, and modern web development

**Deployment Target**: Public website accessible via LinkedIn profile link

**Target Audience**: Recruiters, hiring managers, potential collaborators visiting from LinkedIn

---

## Core Goals & Requirements

### Primary Objectives
1. **Personal Branding**: Create a unique, memorable way to present professional background
2. **Skill Demonstration**: Actively showcase RAG, vector search, and clean system design
3. **Accessibility**: Public deployment that handles concurrent visitors efficiently
4. **Ease of Updates**: Frequent content updates during active job search (weekly/bi-weekly)

### Technical Showcase Priorities
**Currently Demonstrated:**
- **RAG Architecture**: Semantic search over resume/project documents with intelligent chunking
- **Vector Database**: Qdrant integration with OpenAI embeddings
- **Production API**: FastAPI with session management, rate limiting, and scalability guardrails
- **Clean UI/UX**: Professional, Claude-inspired interface with markdown rendering

**Optional Enhancements:**
- **Real-time Communication**: WebSocket implementation (REST API currently production-ready)

### Content Types
- **Text Data**: Resume JSON, project descriptions (markdown), work experience narratives
- **Documents**: PDFs (can be processed and embedded)
- **Structured Data**: Skills taxonomy, timeline data, contact information

---

## Architecture Decisions

### Tech Stack (Final Decision)

**Backend:**
- **Framework**: FastAPI (proven from Ben AI chatbot)
- **Communication**: REST (`POST /api/chat`) today; WebSocket is optional later
 - **Vector DB**: Qdrant (Qdrant Cloud for demos; self-hosting optional)
- **AI Model**: Anthropic Claude (configured via `ANTHROPIC_MODEL`)
- **Embeddings**: OpenAI `text-embedding-3-small` (when RAG is enabled)
- **Session Management**: In-memory (easy migration path to Redis later)
- **Guardrails**: rate limiting, message bounds, session cleanup/compaction

**Frontend:**
- **Framework**: Vanilla JavaScript
- **UI Style**: Claude-inspired clean design with personal branding
- **API integration**: calls `fetch("/api/chat")` (assumes same-origin; backend can serve the frontend)

**Data Layer:**
- **Primary**: `data/resume.json` (structured career data)
- **Projects**: `data/projects/*.md` (detailed project writeups)
- **Vector Index**: Qdrant collection with chunked documents + metadata (Phase 3)

**Deployment:**
- **Hosting**: Railway or Render (backend), Vercel (frontend) OR all-in-one
- **Database**: Qdrant Cloud free tier OR self-hosted in Docker
- **Domain**: Custom subdomain (e.g., chat.dakotaradigan.com or assistant.dakotaradigan.com)

### Why These Choices?

**Why Qdrant over Pinecone?**
- Free tier supports 1GB storage (enough for this use case)
- Better for small-scale deployments
- Docker support for self-hosting option
- Lower latency for small datasets
- No $70/month minimum like Pinecone

**Why Claude over GPT-4?**
- Better for conversational, nuanced responses
- 200k context window (can handle large resume corpus)
- Showcases diversity in AI model experience

**Why Consider WebSocket Enhancement (Optional)?**
- Would demonstrate real-time system design skills
- Better UX (typing indicators, instant responses)
- Proven implementation pattern from Ben AI chatbot
- Would differentiate from simple chat interfaces

**Current Status:** REST API is production-ready and provides excellent UX. WebSocket would be an enhancement, not a requirement.

---

## Phase-Based Development Approach

### **CRITICAL: Incremental Development Philosophy**
This project will be built in discrete phases. **DO NOT attempt to build everything at once.** Each phase should be completable in 1-2 focused work sessions and fully functional before moving to the next.

---

### Phase 1: Project Foundation & Data Structure
**Goal**: Set up project skeleton and define data schemas

**Tasks:**
1. Create folder structure (backend/, frontend/, data/, docs/)
2. Define resume.json schema with Dakota's actual data
3. Create 2-3 sample project markdown files
4. Set up requirements.txt with core dependencies
5. Create .env.example template
6. Write initial system_prompt.txt

**Deliverables:**
- - Clean project structure
- - Populated resume.json with real data
- - Sample project descriptions
- - Dependencies documented

**Exit Criteria**: All data files created and validated, no code yet

**Status**: Complete

---

### Phase 2: Basic FastAPI Backend (No Vector DB Yet)
**Goal**: Get basic chat working with context-only approach first

**Tasks:**
1. Create minimal FastAPI app (health endpoint, basic chat endpoint)
2. Implement session management (copy from Ben AI)
3. Add Claude API integration with resume context in system prompt
4. Test basic conversational responses about resume
5. Add CORS configuration for frontend

**Deliverables:**
- - Working REST API endpoint /api/chat
- - Claude integration with full resume context
- - Basic conversational responses work

**Exit Criteria**: Can ask questions about Dakota's experience and get accurate responses via REST API

**Status**: Complete (REST chat endpoint implemented, frontend calls `/api/chat`)

---

### Phase 3: Vector Search Implementation (RAG Layer)
**Goal**: Add semantic search capability to showcase RAG skills

**Tasks:**
1. Set up Qdrant (local Docker first, then cloud)
2. Implement document chunking strategy for projects/resume sections
3. Create embedding pipeline (Voyage AI or OpenAI)
4. Build vector search function with metadata filtering
5. Integrate retrieval into chat endpoint (context + retrieved docs)
6. Add function calling for structured queries (optional)

**Deliverables:**
- - Qdrant collection populated with resume documents
- - Semantic search working ("Show me AI projects" returns relevant docs)
- - RAG pipeline integrated into responses

**Exit Criteria**: Questions about specific skills/projects retrieve relevant context from vector DB

**Status**: **Complete** - RAG pipeline fully operational with Qdrant integration, OpenAI embeddings, semantic search, and integration tests.

---

### Phase 4: Multimodal Support (REMOVED)
**Status**: **Explicitly Removed from Roadmap**

**Reason**: Project simplified to focus on streamlined text-based approach. Removed in commit d248856 ("Removed references to multimodal support in favor of a more streamlined approach").

**Decision**: Text-only RAG provides sufficient technical showcase without added complexity.

---

### Phase 5: WebSocket Real-Time Communication (Optional Enhancement)
**Goal**: Add WebSocket for better UX and technical showcase

**Status**: **Optional - Not Started** (REST API is production-ready)

**Tasks:**
1. Implement WebSocket endpoint (copy from Ben AI chatbot)
2. Add ConnectionManager class for session management
3. Create typing indicators
4. Add ping/pong heartbeat mechanism
5. Implement fallback to REST if WebSocket fails

**Deliverables:**
- - WebSocket endpoint /ws/{session_id}
- - Real-time message streaming
- - Typing indicators working

**Exit Criteria**: Chat feels responsive with instant feedback, degrades gracefully to REST

---

### Phase 6: Frontend Development
**Goal**: Build professional, branded chat interface

**Tasks:**
1. [DONE] Copy Ben AI frontend structure (HTML, CSS, JS modules)
2. [DONE] Customize branding (colors, logo, personal touches)
3. [DONE] Update sidebar with resume-specific quick queries
4. [DONE] Add header with Download Resume PDF, LinkedIn, GitHub links
5. [OPTIONAL] Create project gallery view (optional enhancement)
6. [OPTIONAL] Implement WebSocket client with fallback (depends on Phase 5)

**Deliverables:**
- - Responsive chat interface
- - Personal branding applied
- - Quick-start suggestions tailored to resume
- - Contact/social links in header

**Exit Criteria**: Fully functional UI that feels professional and personal

**Status**: **Complete** - Functional UI with personal branding, quick-start chips, markdown rendering, and contact links. Optional enhancements pending:
- "How this was built" explainer section
- Project gallery view
- Enhanced suggested prompts based on analytics
- WebSocket client (if Phase 5 implemented)

---

### Phase 7: Deployment & Public Access
**Goal**: Deploy to production and make publicly accessible

**Status**: **Pending** - Application is production-ready, awaiting deployment configuration

**Tasks:**
1. Set up Qdrant Cloud free tier (or Docker on Railway/Render)
2. Deploy backend to Railway/Render with environment variables
3. Deploy frontend to Vercel (or static hosting)
4. Configure custom domain/subdomain
5. Add analytics (optional: track visitor interactions)
6. Test from external network (not localhost)
7. Create LinkedIn post announcing the assistant

**Deliverables:**
- - Public URL live and accessible
- - SSL/HTTPS configured
- - Environment variables secured
- - LinkedIn profile updated with link

**Exit Criteria**: Can share URL with recruiters, fully functional from any device

---

### Phase 8: Polish & Enhancements (Post-Launch)
**Goal**: Iterative improvements based on usage

**Status**: **Future** - Only after successful deployment and user feedback

**Possible Enhancements:**
- Skill tag visualization (interactive word cloud)
- Timeline view of career progression
- "Ask about..." suggested queries based on visitor patterns
- PDF resume generation from chat ("Can you email me Dakota's resume?")
- A/B testing different system prompts
- Usage analytics dashboard

**Priority**: Low (only after core functionality proven)

---

## Development Workflow Preferences

### User's Preferences (DO NOT VIOLATE)
1. **Incremental Development**: Build one phase at a time, get it working before moving on
2. **Explain Before Coding**: Justify changes and explain why they're necessary
3. **No One-Shot Builds**: Break large changes into reviewable chunks
4. **Test Each Phase**: Ensure functionality before proceeding to next phase

## Production & Scalability Guardrails
- **State & Sessions**: Anything stateful (sessions/chat history/rate limits) must be pluggable. Default to memory-backed for local dev; plan to swap to a shared store (e.g., Redis) when running multiple workers/containers.
- **Config**: All secrets/URLs via environment variables; keep `.env.example` current. No hardcoded keys.
- **Model Selection**: Use `ANTHROPIC_MODEL` env; default `claude-opus-latest`. Pin a dated model only if you need deterministic behavior.
- **Timeouts/Retries**: Set sensible client/server timeouts and return user-friendly errors on upstream failures.
- **Streaming**: Prefer streaming responses for UX; keep REST fallback.
- **CORS/Security**: Tighten allowed origins for production; add security headers (CSP, etc.) before go-live.
- **Logging/Metrics**: Structured logs (omit PII); track latency/error rates. Include health and readiness probes.
- **Testing/CI**: Add smoke tests (`/health`) and mocked chat tests; run lint/format in CI.
- **Static Assets**: Frontend should build as static assets; avoid coupling to backend hostnames (use relative paths or configurable base URLs).
- **RAG Layer**: Keep retrieval behind a small interface so local/Qdrant/cloud backends can swap without touching chat handlers.
- **Rate Limits/Abuse**: Plan for simple per-session/IP rate limits in production.
- **Deploy Targets**: Default assumption—backend on Railway/Render + Qdrant Cloud or containerized Qdrant; frontend on Vercel/static hosting; custom domain with HTTPS.

### Code Quality Standards

**CRITICAL PRINCIPLE: Avoid Technical Debt from Day One**

This project must remain clean, organized, and maintainable throughout development. Dakota wants to avoid technical debt and keep the codebase easy to understand for anyone who reviews it.

**Technical Debt Prevention:**
- Write code as if someone will read it in 6 months with no context
- No "temporary" hacks or "we'll fix this later" solutions
- If something feels messy, refactor it immediately before moving forward
- Delete unused code immediately - don't comment it out "just in case"
- Every function/class should have a single, clear purpose

**Project Organization Principles:**
1. **Minimal File Structure**: Keep it simple - no unnecessary folders or abstractions
2. **Clear Naming**: File and variable names should be self-explanatory
3. **Logical Grouping**: Related code stays together, unrelated code stays separate
4. **No Premature Optimization**: Build for clarity first, optimize only when needed
5. **Documentation Where It Matters**: Comments explain WHY, not WHAT (code should be self-documenting)

**Code Patterns to Follow:**
- Clear variable naming (e.g., `user_message`, `resume_data`, not `msg`, `data`)
- Comments only for complex logic that isn't self-evident
- Modular design: separate concerns (routing, AI logic, data access)
- Error handling with specific, helpful messages
- Logging for debugging and monitoring (but not excessive)
- Type hints in Python where they add clarity

**Code Patterns to AVOID:**
- Deeply nested folders (backend/services/api/v1/handlers/... NO!)
- Overly abstract classes (e.g., BaseAbstractFactoryManager)
- Unused imports or dead code
- Magic numbers or strings (use constants with clear names)
- God functions (one function doing 10 different things)
- Copy-pasted code (create a reusable function instead)

**When Writing Code:**
1. **Think**: Is this the simplest solution that solves the problem?
2. **Write**: Implement cleanly with clear naming
3. **Review**: Would a stranger understand this code?
4. **Refactor**: If it feels messy, clean it up NOW (not later)
5. **Test**: Verify it works before moving to the next task

**Red Flags to Watch For:**
- "I'll clean this up later" ← Do it now
- "This is a temporary hack" ← Find the right solution now
- "I'm not sure what this does anymore" ← Refactor immediately
- "Let me just copy this function and modify it" ← Abstract the common logic
- "This file is getting long, but it's fine" ← Split it into logical modules

**Remember**: This is a portfolio piece. Every file someone looks at should demonstrate clean, professional engineering. Technical debt compounds quickly - prevent it from the start.

---

## Key Differentiators from Ben AI Chatbot

| Aspect | Ben AI Chatbot | Resume Assistant |
|--------|----------------|------------------|
| **Purpose** | Financial advisor tool (B2B) | Personal portfolio (B2C) |
| **Data Volume** | 40+ benchmarks, structured | 5-10 projects, semi-structured |
| **Query Style** | Deterministic lookups ("What's the minimum?") | Conversational exploration ("Tell me about...") |
| **Vector DB** | Pinecone (enterprise) | Qdrant (free tier, smaller scale) |
| **AI Model** | OpenAI GPT-4 | Anthropic Claude |
| **Function Calling** | 3 complex functions (required) | 1-2 simple functions (optional) |
| **Security** | High (prevent hallucination, financial context) | Moderate (personal data, no sensitive info) |
| **Updates** | Periodic (monthly benchmark data) | Frequent (weekly during job search) |
| **Access** | Internal tool | Public website |

---

## Content Structure

### resume.json Schema (Current Structure)
```
{
  "personal": {name, title, location, contact, links, summary},
  "experience": [{company, role, duration, achievements, technologies}],
  "projects": [{name, tech_stack, description, highlights, links}],
  "skills": {languages, frameworks, ai_ml, databases, tools},
  "education": [{degree, school, graduation, details}],
  "certifications": [{name, issuer, date}] (optional),
  "achievements": [{title, description, date}] (optional)
}
```

### Project Markdown Template
```
# Project Name

## Overview
Brief description of the project and its purpose

## Problem Solved
What challenge did this address?

## Technical Implementation
- Architecture decisions
- Key technologies used
- Interesting engineering challenges

## Impact/Results
Quantifiable outcomes if available
```

---

## Common Queries to Optimize For

The assistant should excel at answering:
- "What experience does Dakota have with [technology]?"
- "Tell me about Dakota's AI/ML projects"
- "What companies has Dakota worked for?"
- "Does Dakota know [programming language/framework]?"
- "Show me examples of Dakota's full-stack work"
- "What's Dakota's experience with vector databases?"
- "Walk me through the Ben AI chatbot architecture"
- "Can Dakota work with [tech stack]?"

---

## Update Workflow (During Job Search)

When updating content:
1. Edit `data/resume.json` or create new project markdown file
2. If RAG is disabled (`USE_RAG=false`): restart the backend (or call the cache clear endpoint in dev)
3. If RAG is enabled (`USE_RAG=true`): re-indexing may be needed depending on your Qdrant mode
   - In-memory Qdrant: restart the backend (it will index on startup if the collection is empty)
   - Persistent Qdrant: plan for an explicit re-index step (future: add an admin reindex endpoint or a CLI script)
4. Test locally to ensure changes reflected
5. Deploy updates (should be < 5 minutes end-to-end)

**DO NOT** require complex rebuild processes for content updates.

---

## Success Metrics

**Technical (Current Implementation):**
- RAG retrieval accuracy (returns relevant projects for skill queries)
- Response time < 3 seconds for typical queries
- Session management with automatic compaction
- Rate limiting prevents abuse (20 req/min per IP)

**Optional Future Metrics:**
- WebSocket connection stability (if Phase 5 implemented)
- Response streaming latency

**User Experience:**
- - Recruiters spend 2-5 minutes exploring vs 30 seconds on traditional resume
- - Positive feedback on uniqueness/innovation
- - Generates interview conversations about technical implementation

**Deployment:**
- - 99%+ uptime
- - Works on mobile devices
- - Fast page load (< 2 seconds)

---

## Notes & Reminders

- This is a **portfolio piece** as much as a functional tool - prioritize showcasing technical skills
- Keep it **professional** but inject personality (Dakota's voice should come through)
- **Document the build process** - could become a blog post or case study
- Consider adding a "How this was built" explainer section in the UI
- Monitor costs closely (should be < $10/month with free tiers)

---

## Current Status: **Production-Ready, Deployment Pending**

**What's Complete:**
- Backend: FastAPI + Claude + RAG pipeline fully operational
- Frontend: Functional UI with personal branding
- Data: resume.json populated, project descriptions written
- Security: Prompt injection defenses, rate limiting, input validation
- Scalability: Session management, message compaction, timeout protection

**Next Major Milestone: Deployment (Phase 7)**
1. Set up Qdrant Cloud free tier
2. Deploy backend to Railway/Render with environment variables
3. Configure custom domain/subdomain
4. Update CORS allowed origins for production
5. Test from external network
6. Update LinkedIn profile with link

**Optional Enhancements (Post-Deployment):**
- WebSocket support (Phase 5)
- "How this was built" section
- Analytics integration
- Frontend polish items from Phase 6