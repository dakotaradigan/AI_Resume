# CLAUDE.md

Development documentation for the Resume Assistant chatbot project.

## Project Overview

Resume Assistant is an interactive chatbot showcasing Dakota Radigan's professional experience, skills, and projects. Built as a portfolio piece, it demonstrates practical expertise in RAG (Retrieval Augmented Generation), vector search, and production-ready web development.

**Live Site:** https://chat.dakotaradigan.io

**Purpose:**
1. Provide an interactive way for recruiters and hiring managers to learn about professional background
2. Demonstrate technical proficiency in modern AI/ML systems, backend architecture, and clean code practices

**Target Audience:** Recruiters, hiring managers, potential collaborators

---

## Recent Updates (January 2026)

### Chat Limit Protection
- Implemented free tier with 2 exchange limit before password unlock
- Password-based unlimited access for serious inquiries
- Protects API costs while maintaining accessibility

### Response Quality Improvements
- Strengthened formatting rules to ensure tight bullet spacing
- Added conciseness guidelines (2-4 sentences for simple queries, 1-2 paragraphs for complex)
- Fixed markdown parser to prevent extra line breaks in lists

### Production Features
- Live deployment on Railway with custom domain
- CORS security properly configured for production
- Rate limiting and session management guardrails active

---

## Architecture Decisions

### Tech Stack

**Backend:**
- **Framework:** FastAPI with async session management
- **AI Model:** Anthropic Claude (configurable via `ANTHROPIC_MODEL`)
- **Vector DB:** Qdrant with OpenAI embeddings for semantic search
- **Session Management:** In-memory (pluggable for Redis migration)
- **Guardrails:** Rate limiting, message compaction, timeout protection

**Frontend:**
- **Framework:** Vanilla JavaScript (zero dependencies)
- **Design:** Warm green/sage color scheme with dark mode support
- **Accessibility:** WCAG AA compliant
- **API Integration:** REST calls to `/api/chat`

**Data Layer:**
- **Primary:** `data/resume.json` (structured career data)
- **Projects:** `data/projects/*.md` (detailed project writeups)
- **Vector Index:** Qdrant collection with chunked documents + metadata

**Deployment:**
- **Hosting:** Railway (all-in-one backend + frontend)
- **Database:** Qdrant Cloud
- **Domain:** chat.dakotaradigan.io

### Technical Choices Rationale

**Why Qdrant over Pinecone?**
- Free tier supports 1GB storage (sufficient for resume data)
- Better for small-scale deployments
- Docker support for self-hosting option
- Lower latency for small datasets

**Why Claude over GPT-4?**
- Better conversational nuance
- 200k context window (handles large resume corpus)
- Demonstrates diversity in AI model experience

**Why REST API over WebSocket?**
- Simpler deployment and maintenance
- Excellent UX for this use case
- Lower infrastructure complexity
- WebSocket remains optional future enhancement

---

## Development Philosophy

### Simple Wins Over Complex

**This is the #1 principle for this codebase.**

- Prefer the simplest solution that works
- No over-engineering - solve the problem, nothing more
- No tech debt - every change should be production-quality
- If a fix requires more than ~50 lines of new code, reconsider the approach
- All plans MUST be reviewed for simplicity before implementation
- When in doubt, delete code rather than add complexity

**Questions to ask before any change:**
1. Is this the simplest way to solve the problem?
2. Am I adding complexity that isn't strictly necessary?
3. Could I delete something instead of adding something?
4. Will someone understand this in 6 months without context?

**Anti-patterns to avoid:**
- "Future-proofing" that adds complexity now
- Abstractions for single-use cases
- Configuration options nobody will change
- Defensive code for scenarios that can't happen

### Incremental Development
This project was built in discrete phases. Each phase was completable in 1-2 focused work sessions and fully functional before moving to the next.

**Phases Completed:**
1. Foundation & Data Structure
2. Basic FastAPI Backend with REST API
3. Vector Search Implementation (RAG Layer)
4. Frontend Development
5. Deployment & Public Access

**Phase Skipped:**
- Multimodal Support (text-only approach chosen for simplicity)

**Optional Future Enhancement:**
- WebSocket Real-Time Communication (REST API currently provides excellent UX)

### Code Quality Standards

**Core Principles:**
- Write code as if someone will read it in 6 months with no context
- No "temporary" hacks or "we'll fix this later" solutions
- Refactor immediately if something feels messy
- Delete unused code - don't comment it out
- Every function/class should have a single, clear purpose

**Project Organization:**
1. Minimal file structure - avoid unnecessary abstractions
2. Clear, self-explanatory naming
3. Logical grouping of related code
4. Build for clarity first, optimize only when needed
5. Comments explain WHY, not WHAT (code should be self-documenting)

**Code Patterns to Follow:**
- Clear variable naming (`user_message`, `resume_data`)
- Modular design with separated concerns
- Specific, helpful error messages
- Strategic logging for debugging
- Type hints where they add clarity

**Code Patterns to Avoid:**
- Deeply nested folder structures
- Overly abstract classes
- Unused imports or dead code
- Magic numbers or strings
- God functions doing too many things

**Remember:** This is a portfolio piece. Every file demonstrates clean, professional engineering.

---

## Production & Scalability Guardrails

- **State & Sessions:** Memory-backed for single instance; pluggable design enables Redis migration for multi-worker deployments
- **Config:** All secrets via environment variables; `.env.example` documents required configuration
- **Model Selection:** Configurable via `ANTHROPIC_MODEL` environment variable
- **Timeouts/Retries:** Sensible defaults with user-friendly error messages
- **CORS/Security:** Restricted origins in production; wildcard only in development without credentials
- **Logging/Metrics:** Structured logs without PII; health check endpoints included
- **RAG Layer:** Interface-based design allows swapping Qdrant backends without touching chat handlers
- **Rate Limits:** Per-session/IP limits prevent abuse (20 req/min default)

---

## Content Structure

### resume.json Schema
```json
{
  "personal": {"name", "title", "location", "contact", "links", "summary"},
  "experience": [{"company", "role", "duration", "achievements", "technologies"}],
  "projects": [{"name", "tech_stack", "description", "highlights", "links"}],
  "skills": {"languages", "frameworks", "ai_ml", "databases", "tools"},
  "education": [{"degree", "school", "graduation", "details"}],
  "certifications": [{"name", "issuer", "date"}]
}
```

### Project Markdown Template
```markdown
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

## Common Queries Optimized For

The assistant excels at answering:
- "What experience does Dakota have with [technology]?"
- "Tell me about Dakota's AI/ML projects"
- "What companies has Dakota worked for?"
- "Does Dakota know [programming language/framework]?"
- "Show me examples of Dakota's full-stack work"
- "What's Dakota's experience with vector databases?"

---

## Update Workflow

When updating content:
1. Edit `data/resume.json` or create new project markdown file
2. **If RAG disabled (`USE_RAG=false`):** Restart backend or call `/admin/cache/clear`
3. **If RAG enabled (`USE_RAG=true`):** May need re-indexing depending on Qdrant mode
   - In-memory: Restart backend (re-indexes on startup if collection empty)
   - Persistent: Explicit re-index via admin endpoint or CLI script
4. Test locally to verify changes
5. Deploy updates

Content updates should take less than 5 minutes end-to-end.

---

## Success Metrics

**Technical Performance:**
- RAG retrieval accuracy for skill/project queries
- Response time under 3 seconds
- Session management with automatic compaction
- Rate limiting prevents abuse (20 req/min per IP)

**User Experience Goals:**
- Recruiters spend 2-5 minutes exploring vs 30 seconds on traditional resume
- Positive feedback on uniqueness/innovation
- Generates interview conversations about technical implementation

**Deployment:**
- 99%+ uptime
- Mobile device compatibility
- Fast page load (under 2 seconds)

---

## Key Features

### Core Functionality
- Session-based conversation with context retention
- RAG-powered semantic search over resume and project documents
- Chat limits with password unlock (configurable)
- Markdown rendering with proper formatting
- Theme toggle (light/dark mode)

### Production Guardrails
- Rate limiting (20 req/min per IP by default)
- Message compaction to prevent token exhaustion
- Timeout protection (30s default)
- Input validation (2000 char limit)
- Graceful degradation (RAG to static context fallback)

### Security Features
- Prompt injection defenses
- XSS protection via HTML escaping
- Environment-aware CORS configuration
- Admin endpoint authentication

### UX Features
- WCAG AA accessibility compliance
- SVG icons for professional appearance
- Reveal-on-scroll animations
- Collapsible content sections
- Intelligent auto-scroll behavior
- Responsive design for all devices

---

## Development Guidelines

**Preferred Workflow:**
1. **Incremental Development:** Build one phase at a time, verify functionality before proceeding
2. **Explain Before Coding:** Justify changes and explain why they're necessary
3. **Reviewable Chunks:** Break large changes into small, understandable pieces
4. **Test Each Phase:** Ensure everything works before moving to the next task

**When Writing Code:**
1. **Think:** Is this the simplest solution?
2. **Write:** Implement cleanly with clear naming
3. **Review:** Would a stranger understand this?
4. **Refactor:** If it feels messy, clean it up now
5. **Test:** Verify it works before moving on

---

## Current Status: Production Deployed

**Live Site:** https://chat.dakotaradigan.io

**Completed:**
- Backend: FastAPI + Claude + RAG pipeline operational
- Frontend: Professional UI with warm green/sage branding
- Security: Prompt injection defenses, rate limiting, input validation
- Scalability: Session management, message compaction, timeout protection
- Deployment: Railway hosting with custom domain and SSL
- Chat Protection: 2 exchange limit with password unlock for unlimited access

**Future Enhancements (Optional):**
- WebSocket support for real-time communication
- Analytics integration for visitor insights
- "How this was built" explainer section
- Usage dashboard for monitoring

---

## Notes

- **Portfolio Piece:** Prioritize showcasing technical skills alongside functionality
- **Professional Tone:** Maintain professional presentation while allowing personality to show
- **Cost Monitoring:** Target under $10/month with free tiers (Qdrant Cloud, Railway)
- **Documentation:** Consider creating blog post or case study about the build process
