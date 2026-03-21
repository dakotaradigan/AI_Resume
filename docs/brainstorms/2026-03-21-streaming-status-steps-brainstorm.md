# Streaming Status Steps — Brainstorm

**Date:** 2026-03-21
**Status:** Ready for planning

## What We're Building

Replace the generic "Thinking..." indicator with a Perplexity-style streaming status pipeline that shows users each step of the RAG process in real-time:

1. **"Searching resume data..."** — while RAG embeds the query and searches Qdrant
2. **"Found N relevant sections"** — with actual chunk titles (e.g., "Ben AI project", "VP Senior PM achievements")
3. **"Generating response..."** — while Claude processes the context and generates the reply

Steps animate in sequentially, then collapse/fade away when the final answer renders. The steps serve their purpose (transparency + delight) and get out of the way.

## Why This Approach

- **Portfolio showcase**: Proves the RAG pipeline is real — not just a chatbot wrapper. Showing actual retrieved chunk names demonstrates semantic search in action.
- **User engagement**: Turns a 4-7 second wait into an interesting process to watch. Perplexity proved this pattern drives higher engagement.
- **Collapse transition**: Steps fade out after rendering so the chat log stays clean. No visual noise on scroll-back.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Style | Streaming status steps | Most impressive for portfolio; Perplexity-style |
| Transition | Collapse then answer | Steps fade out, keeping chat clean |
| Detail level | Names + count | Show actual RAG chunk titles; proves pipeline is real |
| Cached responses | Simulate steps | Consistent UX; same principle as 1.5s thinking delay |

## Implementation Approach (High-Level)

### Backend Changes
- Extend `ChatResponse` to include RAG metadata: chunk titles, count, and whether cache was used
- Return this metadata alongside the reply so the frontend can display real section names

### Frontend Changes
- Replace static "Thinking..." with a step-by-step renderer
- Each step animates in with a checkmark when complete
- Step 2 ("Found N sections") includes bullet list of chunk titles
- After response arrives, steps collapse with a fade-out transition, then answer renders
- For cached responses: simulate the same step sequence with timed delays (~1.5s total)

### CSS
- Step-in animation (slide + fade)
- Collapse/fade-out transition
- Checkmark styling consistent with glassmorphism aesthetic

## Open Questions

- Should the step timing be proportional to actual backend time, or use fixed delays for consistency?
- Should we show relevance scores alongside chunk titles (e.g., "Ben AI project — 94% match")?

## What's NOT in Scope

- SSE/WebSocket streaming of the actual response text (separate feature)
- Showing the raw system prompt or full context (security concern)
- Changing the backend RAG logic itself
