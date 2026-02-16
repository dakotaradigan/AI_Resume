---
title: "feat: Citation Grounding UI"
type: feat
date: 2026-02-12
updated: 2026-02-15
status: reverted — needs new approach
---

# Citation Grounding UI

## Overview

Add a collapsible "Sources (N)" section below each bot response that links to resume sections on the same page. Clicking a source chip scrolls to the section with a brief highlight. Goal: build recruiter trust by showing every claim is grounded in real resume data.

## Current Status: REVERTED

**PR #51** implemented the MVP below and was merged, but sources showed RAG retrieval chunks (generic titles like "Personal Information") rather than what the bot actually referenced. Reverted in **PR #54**. The qdrant-client fix (`search()` → `query_points()`) was preserved independently. See the brainstorm doc for full post-mortem and future approaches.

## Problem Statement

The chatbot answers questions about Dakota's resume but provides no visible link between its claims and the actual data. Citation grounding closes this trust gap by showing which resume sections backed each answer.

---

## MVP (Phase 1)

### Backend (~10 lines changed)

Pass through existing RAG metadata in the API response. No new models — just forward what `rag.py` already returns (minus the large `text` field).

```python
# backend/main.py — extend ChatResponse
class ChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: list[dict] = []  # [{title, type}] from RAG results
```

Modify `retrieve_rag_context()` return type from `tuple[str, bool]` to `tuple[str, bool, list[dict]]`. Return the raw results list (title + type only) alongside the context string. No formatting — pass through what RAG already returns. The frontend handles display via CSS truncation.

### Frontend (~50 lines)

Use native `<details>` element for collapse/expand (free accessibility — `aria-expanded` handled by browser).

```
┌─────────────────────────┐
│ Bot message body         │
├─────────────────────────┤
│ ▶ Sources (2)           │  ← <details> collapsed by default
│   [Experience]  [Skills] │  ← chips (expanded)
├─────────────────────────┤
│ 👍 👎                    │  ← existing feedback UI
└─────────────────────────┘
```

Create a standalone `addSourcesUI(messageEl, sources)` function (same pattern as `addFeedbackUI`). Insert between message body and feedback buttons. Do NOT grow `sendMessage()`.

On chip click:
- `document.getElementById(sectionId).scrollIntoView({ behavior: 'smooth' })`
- Add a CSS class for gold glow, remove after animation ends

### Chunk type → section ID mapping (frontend-owned)

```javascript
const SECTION_MAP = {
    experience: "experience",
    project: "experience",       // projects map to experience (no #projects section on page)
    skills: "skills",
    education: "education",
    certifications: "education", // certs are inside education section
    personal: null               // suppress from sources
};
```

### CSS (~20 lines)

- `.source-chip` pill styles (min-height 36px for mobile tap targets)
- `.section-highlighted` keyframe: gold glow using `::after` pseudo-element with `opacity` animation (same pattern as thinking pulse), 1.8s duration
- `@media (prefers-reduced-motion: reduce)` — suppress animation, keep static highlight

### Edge cases

- **Empty sources / RAG disabled:** Hide section entirely (never show `Sources (0)`)
- **Intro/error/unlock messages:** Never show sources (only on successful API responses with RAG)
- **Duplicate chips:** Deduplicate by `(section_id, title)` pair — two project chunks mapping to `#experience` with different titles ("Ben AI" vs "Resume Assistant") show as separate chips, but two experience chunks with the same title collapse to one
- **Chip labels:** Use raw `title` from RAG, truncated with CSS `text-overflow: ellipsis`. No backend formatting.

### Files to modify

| File | Change |
|------|--------|
| `backend/main.py` | Add `sources: list[dict] = []` to `ChatResponse`. Thread sources from `retrieve_rag_context()` to response. |
| `backend/rag.py` | No changes needed — `search()` already returns `{title, type, score, timeframe}`. The change is in `retrieve_rag_context()` (in `main.py`) which currently discards raw results after building the context string. |
| `frontend/app.js` | New `addSourcesUI()` function. Call it in `sendMessage()` success path. |
| `frontend/styles.css` | `.source-chip`, `.section-highlighted` glow animation, reduced-motion query. |

No changes needed to `frontend/index.html` (section IDs already exist).

### Acceptance criteria

- [ ] Bot responses with RAG results show a collapsed "Sources (N)" section
- [ ] Sources hidden when no RAG results, RAG disabled, or non-grounded messages
- [ ] Clicking a chip smooth-scrolls to the matching resume section with a brief gold highlight
- [ ] `prefers-reduced-motion` suppresses the glow animation
- [ ] Chips are readable and tappable on mobile (36px min height, full-width wrap)

---

## v2 (Future — only if user testing shows demand)

These were considered for MVP but cut per the "Simple Wins Over Complex" principle. Add them only if real usage data justifies the complexity.

| Feature | Why deferred |
|---------|-------------|
| `low_confidence` auto-expand | Premature — no evidence recruiters need this. Drawing attention to uncertainty undermines trust. |
| `display_title` backend formatting | Start with CSS truncation. Add server-side shortening only if raw titles look bad in practice. |
| Per-role targeting (`role_index`) | Scrolling to `#experience` is enough — the section has 3-4 entries, easy to scan. |
| "Referenced" pill near section title | Redundant with gold glow — two simultaneous indicators for the same thing. |
| Click debouncing | Browser `scrollIntoView` handles rapid clicks naturally. Cancel-previous-glow via CSS class toggle is sufficient. |
| `score` exposure to frontend | No UI purpose in MVP. Useful for debugging but not for recruiters. |
| Project-to-specific-role mapping | Simple `project → #experience` fallback is fine. Elaborate mapping adds fragile coupling. |

---

## Dependencies & Risks

- **Dependency:** RAG must be enabled (`USE_RAG=true`) for sources to appear. Static context fallback produces no sources.
- **Risk:** Project chunks linking to "Experience" could feel imprecise. Mitigated by keeping the project name in the chip label (e.g., chip says "Ben AI" with type "experience").
- **Risk:** Sources add height to chat messages. Mitigated by collapsed-by-default behavior.

## References

- Brainstorm: `docs/brainstorms/2026-02-12-citation-grounding-brainstorm.md`
- RAG search results: `backend/rag.py` — `search()` returns `{title, type, score, timeframe}` per chunk
- Current API response: `backend/main.py` — `ChatResponse(reply, session_id)`
- Feedback UI pattern: `frontend/app.js` — `addFeedbackUI(messageEl, trigger)`
- Resume section IDs: `frontend/index.html` — `#experience`, `#education`, `#skills`
- Thinking glow pattern: `frontend/styles.css` — `::after` with `opacity` animation
