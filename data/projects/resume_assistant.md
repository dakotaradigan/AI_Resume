# Resume Assistant: Reimagining Professional Discovery

## The Problem
Traditional resumes are static, one-size-fits-all documents that force recruiters to linearly parse information, often missing relevant details buried in dense text. For candidates with diverse technical backgrounds, this creates a mismatch: recruiters spend seconds skimming when they need minutes exploring, and the best-fit information often gets overlooked.

## A New Way of Thinking
What if instead of presenting a document, we created a **conversation**? What if recruiters could simply ask "What's your AI experience?" or "Show me full-stack projects" and get instant, contextual answers? This shifts the paradigm from **passive presentation** to **interactive discovery**.

More importantly, what if the portfolio piece itself demonstrated the technical capabilities being showcased? The chatbot becomes both the medium and the message—proving AI/ML expertise by being a working AI product.

## The Solution
Built an AI-powered chatbot that serves as an interactive professional portfolio. Recruiters and hiring managers can have natural conversations about experience, skills, and projects instead of reading a static resume. The assistant intelligently retrieves relevant context using RAG (Retrieval Augmented Generation) and responds with accurate, conversational answers.

## Tech Stack
**Backend:** FastAPI, Python
**AI/ML:** Anthropic Claude Opus 4.5, RAG Pipeline, Qdrant Vector Database, OpenAI Embeddings
**Frontend:** JavaScript with custom CSS design system
**Key Features:** Semantic search, session management, rate limiting, prompt injection protection, dark mode UI

## Why It Matters

### For Recruiters
- **Interactive Discovery**: Ask specific questions rather than scanning pages
- **Time Efficient**: Get answers in seconds instead of parsing dense text
- **Memorable**: Stands out from hundreds of traditional resumes
- **Technical Validation**: The assistant itself proves AI/ML capabilities

### For Dakota
- **Innovation Showcase**: Demonstrates forward-thinking approach to professional branding
- **Technical Proof**: Working example of RAG architecture, vector search, and AI integration
- **Differentiation**: Unique in a competitive market
- **Conversation Starter**: Creates natural talking points for interviews

## Key Technical Highlights
- **RAG Architecture**: Semantic search over resume documents with intelligent chunking and context retrieval
- **Production-Ready**: Rate limiting, session management, hallucination prevention (temperature=0.1), security guardrails
- **Full-Stack**: Backend (FastAPI), Frontend (JavaScript + CSS), Data Layer (Vector DB)
- **Accessibility**: WCAG AA compliant with dark mode support
- **Scalable**: Designed for concurrent users with pluggable state management

## The Impact
This project transforms the traditional resume into an **interactive experience** that showcases both technical expertise and innovative thinking. It answers the question "Can you build AI products?" by providing working proof—a production-quality chatbot accessible 24/7 from a LinkedIn profile link.

Beyond functionality, it signals **forward-thinking product development**: identifying a user pain point (static resumes), reimagining the solution (conversational interface), and executing with production-quality engineering.

**The portfolio piece becomes the portfolio proof.**
