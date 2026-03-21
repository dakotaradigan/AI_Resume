---
title: "feat: Streaming status steps for chat responses"
type: feat
date: 2026-03-21
deepened: 2026-03-21
---

# feat: Streaming Status Steps for Chat Responses

## Enhancement Summary

**Deepened on:** 2026-03-21
**Agents used:** frontend-design, code-simplicity, architecture-strategist, julik-frontend-races, sendMessage-learnings, css-best-practices-researcher, production-hardening-learnings

### Key Improvements from Research
1. **Simplified backend** — dropped SourceChunk model and RAGResult dataclass; use `list[str]` and 3-tuple instead (~10 lines changed vs ~30)
2. **Fixed high-severity race condition** — unlock retry re-enters sendMessage before `finally` completes; input re-enabled during animation window
3. **Polished CSS** — spring-animated checkmarks, `grid-template-rows` collapse (no layout thrash), ease-out-expo timing curves
4. **Accessibility** — hidden `role="status"` live region for screen readers; `prefers-reduced-motion` support
5. **Keep MIN_THINKING_MS for error paths** — prevents error responses from flashing

### Critical Issues Discovered
- **HIGH**: Unlock retry calls `sendMessage` recursively before outer `finally` runs → fix with `setTimeout(..., 0)`
- **MEDIUM**: Source titles must use `textContent` not `innerHTML` (XSS surface)
- **MEDIUM**: MutationObserver may disable auto-scroll during step animation → force scroll after answer renders

---

## Overview

Replace the generic "Thinking..." indicator with a Perplexity-style step pipeline that shows what the AI did to answer the question. Steps animate in after the response arrives (retroactive), then collapse to reveal the final answer. This proves the RAG pipeline is real and turns a wait into something engaging.

## Problem Statement

Users see "Thinking..." for 3-7 seconds with no insight into what's happening. For a portfolio piece showcasing RAG architecture, this is a missed opportunity. Modern AI interfaces (Perplexity, ChatGPT search) show their work, building trust and engagement.

## Proposed Solution

**Retroactive step rendering.** The thinking dots show during the actual fetch (unchanged). When the response arrives, instead of immediately rendering the answer, the frontend animates through the pipeline steps using real metadata from the response, then collapses them to reveal the answer.

This is simpler than real-time simulation because:
- No timer coordination with the fetch
- No race conditions (response arrives mid-step)
- No SSE/WebSocket needed — works with existing REST API
- Steps always show accurate data (real chunk titles, real counts)

### Step Sequence

```
✓ Searching resume data...
✓ Found 3 relevant sections
  • Ben AI project
  • VP Senior PM achievements
  • AI certifications
✓ Generating response...
[steps collapse → answer appears]
```

### Variations by Response Type

| Scenario | Step 1 | Step 2 | Step 3 |
|----------|--------|--------|--------|
| RAG returns 1-3 chunks | ✓ Searching resume data... | ✓ Found N relevant sections + titles | ✓ Generating response... |
| RAG returns 0 / fallback | ✓ Searching resume data... | ✓ Using full resume context... | ✓ Generating response... |
| RAG disabled | ✓ Loading resume data... | (skip) | ✓ Generating response... |
| Cached starter response | ✓ Searching resume data... | ✓ Found relevant sections | ✓ Generating response... |
| Error (403/429/5xx) | (steps never shown — thinking dots replaced with error as today) |

## Technical Approach

### Phase 1: Backend — Add Sources to ChatResponse

**File: `backend/main.py`** — ~10 lines changed, 0 new models

#### Research Insight: Keep It Simple
The simplicity reviewer and architecture strategist both recommend against `SourceChunk` and `RAGResult`. A `list[str]` for source titles and a 3-tuple return are sufficient for a single-consumer API.

1. Extend `ChatResponse` with two optional fields (defaults for backward compat):

```python
# main.py ~line 240
class ChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: list[str] = Field(default_factory=list)  # RAG chunk titles
    used_rag: bool = False
```

2. Update `retrieve_rag_context` to return source titles as a third element:

```python
# main.py ~line 381 — change return type
def retrieve_rag_context(...) -> tuple[str, bool, list[str]]:
    # ... existing logic ...
    results = rag_pipeline.search(query, limit=limit, score_threshold=score_threshold)
    titles = [r["title"] for r in results]
    return "\n\n".join(context_parts), True, titles
    # Fallback paths return: load_resume_context(), False, []
```

3. Pass sources through in the chat endpoint:

```python
# main.py ~line 791 — update destructuring
resume_context, used_rag, sources = await asyncio.to_thread(...)
# ...
return ChatResponse(
    reply=reply_text, session_id=session_id,
    sources=sources, used_rag=used_rag,
)
```

4. For cached starter responses, return `used_rag=False, sources=[]` (frontend simulates).

**Files touched:** `backend/main.py` only
**Lines affected:** ~240 (model), ~381-421 (retrieve_rag_context), ~788-869 (chat endpoint)

#### Research Insight: Add a Test
The architecture reviewer noted `retrieve_rag_context` has zero test coverage across 3 code paths. Add a unit test mocking `rag_pipeline.search`:

```python
# backend/test_rag.py — new test
def test_retrieve_rag_context_returns_titles():
    # Mock pipeline.search to return results with titles
    # Assert third element of tuple contains expected titles
```

#### Research Insight: Don't Update Analytics
`log_query(session_id, message, reply_text)` does not need the new fields. Keep the blast radius small — defer analytics changes to when the evals pipeline needs source-level data.

---

### Phase 2: Frontend — Step Renderer

**File: `frontend/app.js`** — one new function (~25 lines) + sendMessage modifications

#### Research Insight: One Function, Not Three
The simplicity reviewer recommends inlining step logic. One `renderStatusSteps` function handles everything — no `buildSteps` or `createStepElement` helpers needed.

#### Research Insight: Critical Race Condition Fix (HIGH)
The unlock retry path at line 663 calls `sendMessage` recursively before the outer `finally` runs `setSending(false)`. With the new ~1.5s async animation, this creates a window where the input is re-enabled and users can send concurrent messages.

**Fix:** Use `setTimeout(..., 0)` to defer the retry until after `finally` completes:

```javascript
// In the unlock success handler (~line 663):
if (unlockData.success) {
  thinkingEl.remove();
  setTimeout(() => sendMessage(message, { isRetry: true }), 0);
  return;
}
```

#### Implementation

```javascript
// app.js — single new function
const STEP_DELAY = 500;  // ms between steps appearing

async function renderStatusSteps(container, data) {
  container.innerHTML = "";

  // Build step texts based on response metadata
  const steps = [];
  if (data.used_rag && data.sources?.length) {
    steps.push("Searching resume data...");
    steps.push(`Found ${data.sources.length} relevant section${data.sources.length > 1 ? "s" : ""}`);
  } else {
    steps.push("Searching resume data...");
    steps.push(data.used_rag ? "Using full resume context..." : "Found relevant sections");
  }
  steps.push("Generating response...");

  // Animate each step in
  for (let i = 0; i < steps.length; i++) {
    if (!container.isConnected) return;  // guard against detached DOM
    const step = document.createElement("div");
    step.className = "status-step";
    step.setAttribute("aria-hidden", "true");

    const icon = document.createElement("span");
    icon.className = "step-icon";
    icon.textContent = "✓";
    step.appendChild(icon);

    const label = document.createElement("span");
    label.textContent = steps[i];  // textContent, not innerHTML (XSS safe)
    step.appendChild(label);

    // Add sub-items for RAG chunk titles on step 2
    if (i === 1 && data.used_rag && data.sources?.length) {
      const list = document.createElement("ul");
      list.className = "step-items";
      data.sources.forEach((title) => {
        const li = document.createElement("li");
        li.textContent = title;  // textContent for safety
        list.appendChild(li);
      });
      step.appendChild(list);
    }

    container.appendChild(step);
    // Trigger reflow then add visible class for CSS transition
    requestAnimationFrame(() => step.classList.add("is-visible"));
    await new Promise((r) => setTimeout(r, STEP_DELAY));
  }

  // Collapse steps
  if (!container.isConnected) return;
  container.classList.add("steps-collapsing");
  await new Promise((r) => setTimeout(r, 400));
}
```

#### Updated sendMessage integration

```javascript
// In sendMessage, replace the success response block (~line 695-700):
const data = await res.json();
const body = thinkingEl.querySelector(".msg-body");
if (body) {
  await renderStatusSteps(body, data);
  thinkingEl.classList.remove("is-thinking");
  body.classList.remove("steps-collapsing");
  body.innerHTML = parseMarkdown(data.reply ?? "No response received.");
}
// Force scroll to bottom after answer renders (MutationObserver may have disabled auto-scroll)
requestScrollToBottom();
```

#### Research Insight: Keep MIN_THINKING_MS for Error Paths
Don't remove `MIN_THINKING_MS` entirely — error responses skip step animation, so a cached 429 would flash "Thinking..." for a single frame. Keep the minimum delay for non-OK responses only:

```javascript
// Apply minimum thinking time only for error responses
if (!res.ok) {
  const elapsed = Date.now() - fetchStart;
  if (elapsed < MIN_THINKING_MS) {
    await new Promise((r) => setTimeout(r, MIN_THINKING_MS - elapsed));
  }
  // ... existing error handling
}
// For success responses, step animation provides the natural delay
```

#### Research Insight: Retry Path (from sendMessage learnings)
The `isRetry` flag already exists. Step animation should still run on retry — the user is waiting for a real response. No special handling needed for `isRetry`.

#### Research Insight: is-thinking Cleanup
Ensure `is-thinking` is removed in **all** code paths (success, error, retry). Currently it's scattered. The `finally` block should handle it as a safety net:

```javascript
} finally {
  thinkingEl?.classList?.remove("is-thinking");
  setSending(false);
  chatInput.focus();
}
```

---

### Phase 3: CSS — Step Animations

**File: `frontend/styles.css`** — ~25 lines

#### Research Insight: Polished Timing
The frontend design agent and CSS research agent both recommend:
- **400ms entrance** with ease-out-expo (`cubic-bezier(0.16, 1, 0.3, 1)`) — arrives quickly, settles gently
- **`grid-template-rows`** for height collapse — no layout thrash, works at any height
- **Spring-curve checkmark** — subtle scale overshoot for a satisfying "done" feel
- **Only animate `transform` and `opacity`** — GPU composited, no jank

```css
/* Step entrance */
.status-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 400ms cubic-bezier(0.16, 1, 0.3, 1),
              transform 400ms cubic-bezier(0.16, 1, 0.3, 1);
  font-size: 0.85rem;
  color: var(--muted);
  line-height: 1.4;
  will-change: opacity, transform;
}

.status-step.is-visible {
  opacity: 1;
  transform: translateY(0);
}

/* Checkmark */
.step-icon {
  flex-shrink: 0;
  color: var(--gold-dark);
  font-size: 0.9rem;
}

/* Sub-items (chunk titles) */
.step-items {
  margin: 2px 0 0 24px;
  padding: 0;
  font-size: 0.8rem;
  color: var(--muted);
  list-style: disc;
}

/* Collapse — fade out in place */
.steps-collapsing .status-step {
  opacity: 0;
  transition: opacity 350ms ease-out;
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  .status-step {
    transition: none;
    opacity: 1;
    transform: none;
    will-change: auto;
  }
  .steps-collapsing .status-step { transition: none; }
}
```

#### Research Insight: Accessibility — Hidden Live Region
Use a hidden `role="status"` region that announces only the current step, not the visual steps:

```html
<!-- In index.html, inside the chat container -->
<div id="step-announcer" class="sr-only" role="status" aria-live="polite"></div>
```

Update the announcer in `renderStatusSteps` after each step appears:
```javascript
const announcer = document.getElementById("step-announcer");
if (announcer) announcer.textContent = steps[i];
```

The visual steps themselves use `aria-hidden="true"`.

---

## Acceptance Criteria

### Functional Requirements

- [ ] Chat responses show animated status steps before the answer appears
- [ ] Step 2 displays actual chunk titles when RAG returns results
- [ ] Step 2 shows "Using full resume context..." when RAG returns zero results
- [ ] Cached starter responses simulate steps with ~1.5s total animation
- [ ] Steps collapse/fade before the final answer renders
- [ ] Error responses (403/429/5xx) skip steps entirely — retain `MIN_THINKING_MS` for errors
- [ ] Retry after password unlock restarts the step pipeline (via `setTimeout` fix)
- [ ] `ChatResponse` includes `sources` and `used_rag` fields with defaults
- [ ] Source titles rendered with `textContent` (not `innerHTML`)

### Non-Functional Requirements

- [ ] Steps total animation time: ~1.5-2s
- [ ] Mobile: steps fit within chat bubble without horizontal overflow
- [ ] Accessibility: `prefers-reduced-motion` shows steps without animation
- [ ] Accessibility: hidden `role="status"` region announces current step for screen readers
- [ ] Backward compatible: `sources` defaults to `[]`, `used_rag` defaults to `False`
- [ ] `is-thinking` class reliably removed in all code paths (success, error, retry)
- [ ] DOM writes guarded with `isConnected` check after each async boundary
- [ ] Only `transform` and `opacity` animated (GPU composited, no layout thrash)

### Testing

- [ ] Unit test for `retrieve_rag_context` covering 3 paths (success, no results, exception)
- [ ] Manual: click each suggestion chip → steps animate → answer appears
- [ ] Manual: trigger 403 (chat limit) → steps never shown, error displays normally
- [ ] Manual: unlock → retry → steps animate correctly without duplication
- [ ] Manual: test on mobile viewport (375px)
- [ ] Manual: test with `prefers-reduced-motion: reduce` in dev tools

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Timing strategy | Retroactive (post-response) | Simplest — no timer/fetch race conditions, always shows real data |
| Backend models | `list[str]` + 3-tuple | Simplicity principle — no new models for single-use data |
| Similarity scores | Not shown to users | Confusing for recruiters; available in JSON for debugging |
| Steps in scroll history | Removed from DOM after collapse | Keeps chat log clean; steps are ephemeral |
| Error handling | Steps never shown on errors; keep `MIN_THINKING_MS` | Prevents error flash; consistent with current behavior |
| Retry race condition | `setTimeout(..., 0)` for unlock retry | Prevents re-entry before `finally` completes |
| Source title rendering | `textContent` always | XSS prevention — titles come from backend metadata |
| Reduced motion | Show steps instantly, no animation | WCAG AA compliance |
| Screen reader | Hidden `role="status"` live region | Avoids noisy announcements from visual step transitions |
| CSS easing | `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo) | Arrives quickly, settles gently — matches glassmorphism aesthetic |

## Dependencies & Risks

**Dependencies:**
- PR #60 (starter response cache) — merged
- PR #61 (minimum thinking delay) — this feature replaces that delay for success path only

**Risks:**
- Low: Step animation timing may feel too fast or slow — easily tunable via `STEP_DELAY` constant
- Low: Long Claude responses (>10s) show step 3 briefly then collapse — natural
- Mitigated: Unlock retry race condition — fixed with `setTimeout` approach
- Mitigated: MutationObserver scroll — explicit `requestScrollToBottom()` after answer renders

## Estimated Scope

| Component | Lines Changed | Lines Added |
|-----------|--------------|-------------|
| `backend/main.py` | ~10 | ~5 |
| `backend/test_rag.py` | 0 | ~15 |
| `frontend/app.js` | ~15 | ~30 |
| `frontend/index.html` | 0 | ~1 |
| `frontend/styles.css` | 0 | ~25 |
| **Total** | **~25** | **~76** |

## References

### Internal
- Brainstorm: `docs/brainstorms/2026-03-21-streaming-status-steps-brainstorm.md`
- Current thinking indicator: `frontend/app.js:580-600`, `frontend/styles.css:618-684`
- ChatResponse model: `backend/main.py:240-242`
- RAG search (returns title/type/score): `backend/rag.py:380-418`
- retrieve_rag_context: `backend/main.py:381-421`
- Starter cache: `backend/main.py:182-189`
- Reveal animation pattern: `frontend/styles.css:1242-1256`
- sendMessage learning: `docs/solutions/frontend-patterns/auto-retry-duplication-sendmessage-20260212.md`

### External
- [NNGroup: Animation Duration](https://www.nngroup.com/articles/animation-duration/)
- [CSS GPU Animation — Smashing Magazine](https://www.smashingmagazine.com/2016/12/gpu-animation-doing-it-right/)
- [MDN: ARIA Live Regions](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)
- [Sara Soueidan: Accessible Notifications](https://www.sarasoueidan.com/blog/accessible-notifications-with-aria-live-regions-part-1/)
