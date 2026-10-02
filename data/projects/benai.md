# Ben AI: Intelligent Benchmark Assistant
## From Personal PoC to Production Deployment

**The Journey:** Personal project (early 2025) → Production deployment at Parametric Portfolio (Morgan Stanley)

## What It Does
AI-powered chatbot that helps financial advisors instantly determine benchmark eligibility for client portfolios. Reduces complex research queries from 30+ minutes to seconds. Grounded in Salesforce data, so answers come from the system of record instead of email threads and manual searches across multiple sources.

## The Evolution Story

### Phase 1: Personal Proof-of-Concept (Home Project)
Built initial version at home to validate whether RAG architecture could effectively handle complex financial benchmark queries. Proved technical viability of:
- Semantic search across benchmark documentation
- Hybrid intelligence combining RAG retrieval with LLM reasoning
- Intent classification for routing different query types
- Real-time conversation with context retention

### Phase 2: Production Scaling (Parametric Deployment)
After validating the architecture, brought Ben AI to Parametric and scaled it for production use:
- Hardened for enterprise reliability and security
- Optimized for production workload (projected 1,800+ annual client inquiries)
- Added advanced features: iterative function calling, multi-benchmark comparisons
- Integrated with existing advisor workflows
- Built comprehensive error handling and logging

## Tech Stack
**Backend:** FastAPI, Python
**AI/ML:** OpenAI Responses API, RAG Pipeline, Pinecone Vector Database, text-embedding-3-small
**Communication:** WebSockets (with REST API fallback)
**Frontend:** JavaScript, Claude-inspired UI

## Key Technical Features
- **RAG Architecture**: Semantic search with Pinecone vector database for accurate benchmark retrieval
- **Intent Classification**: Smart routing to appropriate functions based on query type
- **Iterative Function Calling**: Safety guardrails preventing infinite loops and timeout protection
- **Connection Management**: WebSocket with automatic REST fallback for reliability
- **Security**: Prompt injection protection, input/output sanitization
- **Session Handling**: Context-aware conversation memory with intelligent compression

## Evaluation: How We Know It Works
Ben AI's quality is measured with a human-first evaluation loop modeled on Hamel Husain's error-analysis approach, not vibe checks:
- **Error analysis with human judgment**: real advisor queries and Ben AI's answers are reviewed by hand and labeled pass or fail, with a written critique for every failure.
- **Categorize and rank**: the critiques are grouped into a small set of failure modes and ranked by how often they occur and how much damage they do. A wrong eligibility answer outranks an awkward tone.
- **Refine against the top categories**: prompts, retrieval, and function-calling logic are changed to fix the most frequent and severe failures first, then the review is repeated.
- **LLM judges calibrated to people**: once a failure mode is well understood, an LLM-as-judge grader is written for it and validated against the human labels using true-positive and true-negative rates, so a judge that misses real failures never gates a release.
- **Regression gates and feedback**: validated judges run before each release, and new failure patterns from production feed the next round of error analysis.

The same loop is codified as a reusable evals framework (error analysis, then judges, then operation), so new AI features start from real failures rather than generic metrics.

## Business Impact
- **Time Savings**: Reduced advisor research from 30+ minutes to <5 seconds per query
- **Scale**: Projected to autonomously resolve 1,800+ client inquiries a year
- **Response Time**: Client inquiries resolved in minutes instead of hours
- **Internal Email Reduction**: Reduces internal email across teams that previously answered questions by hand
- **Hours Saved**: ~2,000 hours a year saved across multiple teams that no longer search several sources manually
- **Catalog as Strategic Advantage**: Matches client criteria to the best-fit solution rather than the familiar default, unlocking Parametric's full offering catalog that teams historically underused
- **Innovation**: Visible client-facing AI capability demonstrating technical leadership
- **Retention**: Enabled organic SMAP ecosystem retention through better service

## Technical Highlights
- Built end-to-end: architecture design, implementation, testing, deployment
- Demonstrates full-stack AI development capabilities
- Production-ready error handling and monitoring
- Modular design enabling future enhancements
- Real-time communication with fallback mechanisms

**This project showcases the complete lifecycle of AI product development: from initial concept validation through production scaling and measurable business impact.**
