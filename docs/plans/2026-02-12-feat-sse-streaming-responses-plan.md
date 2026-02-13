---
title: "feat: SSE Streaming Responses"
type: feat
date: 2026-02-12
---

# SSE Streaming Responses

## Overview

Add streaming "typing" effect to bot responses using Server-Sent Events. Tokens appear progressively instead of the full response loading at once. Goal: reduce perceived latency and make the chat feel more natural.

## Problem Statement

The current flow waits 2–5 seconds for the full Anthropic response, then renders it all at once. This creates a jarring UX — the thinking animation plays, then a wall of text appears instantly. Streaming shows text as it generates, making 3-second responses feel like 0.5 seconds.

---

## Key Architectural Decisions

### 1. POST + `fetch()` ReadableStream (not GET + EventSource)

`EventSource` only supports GET — that means user messages in URLs (security risk: server logs, proxy logs, browser history). `fetch()` with `response.body.getReader()` supports POST with JSON body, and critically allows reading the HTTP status code *before* processing the stream body. This is required for the 403 chat-limit flow.

### 2. Content negotiation on single `/api/chat` endpoint (not a second endpoint)

Instead of creating `/api/chat/stream`, the existing `/api/chat` endpoint checks the `Accept` header. If `text/event-stream`, it returns a `StreamingResponse`. Otherwise, the existing JSON response. This eliminates a second endpoint, eliminates guardrail duplication, and keeps one source of truth for all chat logic. The shared validation/limits/retrieval/message-assembly runs once — only the transport differs.

### 3. Plain text during stream, `parseMarkdown()` on completion

Incremental markdown parsing on partial tokens is fragile (a `**` could split across chunks). The simplest approach: append raw text via `textContent` during streaming (XSS-safe by default), then do a single `parseMarkdown(fullText)` swap on completion. The brief visual reformat is an acceptable tradeoff per "Simple Wins Over Complex."

### 4. Transactional stream completion

Session history and analytics are only persisted on successful stream completion (`done` event). If the stream aborts mid-response, neither the user message nor the partial assistant text is saved. This prevents corrupting conversation context — an orphaned user message without an assistant response would violate the Anthropic API's alternating-role requirement on the next call.

### 5. Explicit disconnect cancellation

The server-side generator checks `await request.is_disconnected()` and breaks the loop immediately on client disconnect. The `finally` block closes the Anthropic stream. This prevents wasted tokens/cost and orphaned server work when users close tabs or navigate away mid-stream.

---

## Phase 0: Verify Railway SSE Support (Do First)

Before writing any production code, deploy a trivial test endpoint to confirm Railway's proxy doesn't buffer SSE responses.

```python
# backend/main.py — temporary test endpoint (remove after verification)
@app.get("/api/test-stream")
async def test_stream():
    async def generate():
        for i in range(10):
            yield f"data: token {i}\n\n"
            await asyncio.sleep(0.3)
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

If tokens arrive progressively on `chat.dakotaradigan.io`, proceed. If they arrive all at once, investigate Railway proxy headers before continuing.

---

## MVP (Phase 1)

### Backend (~35 lines changed)

**Modify existing `/api/chat` to support streaming via `Accept` header:**

The existing guardrail logic (lines 730–817) stays exactly where it is. After the guardrails, the handler branches based on the `Accept` header:

```python
# backend/main.py — inside existing chat() handler, after line 817

if request.headers.get("accept") == "text/event-stream":
    return _stream_response(client, settings, system_message, messages,
                            session_id, message, store, request)

# ... existing non-streaming path continues unchanged below ...
```

**New `_stream_response()` helper (~30 lines):**

```python
def _stream_response(client, settings, system_message, messages,
                     session_id, message, store, request):
    """SSE streaming transport for the chat endpoint."""
    async def generate():
        full_text = ""
        try:
            async with client.messages.stream(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                temperature=0.1,
                system=system_message,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    if await request.is_disconnected():
                        return  # Cancel: stop consuming Anthropic tokens
                    full_text += text
                    yield f"data: {json.dumps({'text': text})}\n\n"
        except RateLimitError:
            yield f"data: {json.dumps({'error': 'Service is busy. Please try again shortly.'})}\n\n"
            return
        except AnthropicError:
            yield f"data: {json.dumps({'error': 'Unable to generate a response right now.'})}\n\n"
            return
        except Exception:
            logger.exception("Unexpected error during stream")
            yield f"data: {json.dumps({'error': 'Something went wrong.'})}\n\n"
            return

        # --- Transactional: only persist on successful completion ---
        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
        await store.append_message(session_id, "user", message)
        await store.append_message(session_id, "assistant", full_text)
        await _compact_session_history(session_id, store)
        log_query(session_id, message, full_text)
        today = date.today().isoformat()
        _daily_conversation_count[today] = _daily_conversation_count.get(today, 0) + 1

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Key details:**
- Structured exception handling: `RateLimitError` and `AnthropicError` yield user-safe messages. Raw exception strings are never leaked to the client.
- `await` on all async store/compaction calls (they are async in the actual codebase).
- Daily conversation counter incremented only on successful completion.
- `request.is_disconnected()` is best-effort behind reverse proxies — the `finally` in `client.messages.stream()` context manager handles cleanup if this misses.

### Frontend (~45 lines new)

**Streaming is always-on.** No feature flag, no config endpoint, no env var. If you need to disable it, revert the frontend code. The non-streaming backend path remains as-is for any non-SSE client.

**Modify `sendMessage()` to branch on streaming:**

```javascript
async function sendMessage(message, { isRetry = false } = {}) {
  suggestionsEl?.remove();
  if (!isRetry) addMessage(message, "user");
  const thinkingEl = addMessage("Thinking...", "bot");
  thinkingEl.classList.add("is-thinking");
  const body = thinkingEl.querySelector(".msg-body");
  setSending(true);

  try {
    await streamResponse(message, thinkingEl, body);
  } catch (err) {
    // Stream failed entirely (network error, etc.) — fall back to non-streaming
    await fetchResponse(message, thinkingEl, body);
  } finally {
    setSending(false);
    chatInput.focus();
  }
}
```

**New `streamResponse()` helper (~35 lines):**

```javascript
async function streamResponse(message, thinkingEl, body) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "text/event-stream",       // Request streaming
    },
    body: JSON.stringify({ message, session_id: sessionId }),
  });

  if (!res.ok) {
    // Handles 403 (chat limit), 429 (rate limit), etc.
    // Reuse existing error handling logic
    return handleHttpError(res, thinkingEl, body, message);
  }

  thinkingEl.classList.remove("is-thinking");
  body.textContent = "";
  let fullText = "";

  // Suppress per-token screen reader announcements
  chatLog.setAttribute("aria-live", "off");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";  // Line buffer for chunk boundary handling

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();  // Keep incomplete last line in buffer

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = JSON.parse(line.slice(6));

      if (data.text) {
        fullText += data.text;
        body.textContent = fullText;  // textContent = XSS-safe
        requestScrollToBottom();
      }
      if (data.done) {
        sessionId = data.session_id || sessionId;
      }
      if (data.error) {
        body.textContent = fullText
          ? fullText + "\n\n(Response interrupted)"
          : data.error;
        chatLog.setAttribute("aria-live", "polite");
        return;
      }
    }
  }

  // Re-enable screen reader announcements
  chatLog.setAttribute("aria-live", "polite");

  // Final markdown pass
  body.innerHTML = parseMarkdown(fullText || "No response received.");
  if (!firstResponseFeedbackShown) {
    firstResponseFeedbackShown = true;
    addFeedbackUI(thinkingEl, "first_response");
  }
  requestScrollToBottom();
}
```

**Key details:**
- **Line buffer** (`buffer` + `lines.pop()`) handles SSE data split across TCP chunks — prevents `JSON.parse` failures on partial lines.
- **`aria-live="off"`** during streaming, restored to `"polite"` on completion — screen readers get one announcement of the full response.
- **Fallback:** If `streamResponse()` throws (network error, unexpected failure), `sendMessage()` catches it and falls back to the existing `fetchResponse()` (the current non-streaming path, extracted into its own helper).
- **Same `/api/chat` URL** — the `Accept: text/event-stream` header is the only difference.

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| **Stream fails mid-response** | Keep partial text visible, append "(Response interrupted)". Neither message saved to session history (clean rollback). |
| **403 chat limit** | Returned as normal HTTP 403 before stream body — existing unlock flow works unchanged. |
| **Post-unlock retry** | `sendMessage(message, { isRetry: true })` — uses streaming (same path). |
| **Empty stream (zero tokens)** | `fullText` stays empty → "No response received." fallback in markdown pass. |
| **Client disconnects** | Server detects via `request.is_disconnected()`, stops consuming Anthropic tokens. No session history saved. |
| **Anthropic rate limit mid-stream** | Structured error event sent, user sees safe message. No raw exception details leaked. |
| **Stream entirely fails (network)** | `streamResponse()` throws → `sendMessage()` catches → falls back to `fetchResponse()`. |

### Files to Modify

| File | Change |
|------|--------|
| `backend/main.py` | Add `Accept` header check in `chat()`. Add `_stream_response()` helper function. |
| `frontend/app.js` | Add `streamResponse()` helper. Extract existing fetch logic into `fetchResponse()`. Add `Accept` header. Add line buffer. Aria-live toggle. |

No changes needed to: `backend/config.py`, `backend/.env.example`, `frontend/styles.css`, `frontend/index.html`.

### Acceptance Criteria

- [ ] Tokens appear progressively when `Accept: text/event-stream` is sent
- [ ] Existing non-streaming path works identically (no `Accept` header → JSON response)
- [ ] 403 chat limit + password unlock flow works identically
- [ ] Post-unlock retry streams correctly (no double message)
- [ ] Feedback UI appears after stream completes
- [ ] Auto-scroll follows streaming text
- [ ] `setSending` disables input during entire stream
- [ ] `chatInput.focus()` fires after stream completes
- [ ] Screen readers get a single announcement after completion (not per-token)
- [ ] Client disconnect stops server-side token consumption
- [ ] Stream failure preserves partial text with error notice, does NOT save to session history
- [ ] Anthropic errors yield user-safe messages (no raw exception strings)
- [ ] Falls back to non-streaming on network failure

### Implementation Sequence

Split into two commits to reduce risk:

1. **Commit 1 (refactor):** Extract existing fetch logic in `sendMessage()` into `fetchResponse()` helper. Pure refactor, no behavior change. Verify everything still works.
2. **Commit 2 (feature):** Add `_stream_response()` backend helper, `streamResponse()` frontend helper, `Accept` header branching, aria-live toggle.

---

## v2 (Future — only if streaming MVP proves stable)

| Feature | Why deferred |
|---------|-------------|
| Incremental markdown parsing | Complex, error-prone with partial tokens. Plain text + final parse is good enough. |
| Typing cursor indicator | Cosmetic polish. Text appearing is its own indicator. |
| TTFT / total time logging | Useful for optimization but not needed for initial launch. |
| Escape key to cancel stream | `reader.cancel()` + `AbortController.abort()` is ~5 lines. Add if users report frustration with long responses. |
| Retry button on stream failure | "(Response interrupted)" with manual re-type is sufficient for MVP. |
| Streaming-aware evals | Evals test final accumulated text. Streaming doesn't change content, just delivery. |
| Partial response persistence | Currently: abort = save nothing. Could persist with `status=partial` if users want to reference interrupted answers. |

---

## Dependencies & Risks

- **Dependency:** Railway must support unbuffered SSE (verify in Phase 0 before building)
- **Dependency:** Anthropic SDK `>=0.40.0` (already in requirements.txt) supports `client.messages.stream()`
- **Risk:** Markdown flicker on stream completion. Mitigated by accepting the tradeoff — users see raw text briefly, then formatted. ChatGPT uses the same pattern.
- **Risk:** `request.is_disconnected()` is best-effort behind reverse proxies. Mitigated by the Anthropic SDK's context manager cleanup in its `finally` block.

## References

- Current chat endpoint: `backend/main.py:725-869`
- Anthropic streaming API: `client.messages.stream()` context manager
- Frontend sendMessage: `frontend/app.js:527-649`
- Auto-retry solution doc: `docs/solutions/frontend-patterns/auto-retry-duplication-sendmessage-20260212.md`
- CLAUDE.md simplicity principle: "If a fix requires more than ~50 lines of new code, reconsider the approach"
