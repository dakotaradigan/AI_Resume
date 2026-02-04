---
id: "002"
status: pending
priority: p1
type: fix
title: Wrap RAG retrieval in asyncio.to_thread
created: 2026-02-03
tags: [performance, async, rag]
---

# 002-P1: Wrap RAG Retrieval in asyncio.to_thread

## Problem Statement

The `retrieve_rag_context()` function makes synchronous HTTP calls to OpenAI (embedding) and Qdrant (vector search) within an async endpoint. This blocks the event loop, causing all concurrent requests to stall.

**File:** `backend/main.py:703-708`

```python
# Current code - BLOCKING in async context
resume_context, used_rag = retrieve_rag_context(
    rag_pipeline,
    message,
    limit=3,
    score_threshold=0.5
)
```

**Risk:** Under concurrent load, a single slow OpenAI call (1-3s) blocks all other requests.

---

## Proposed Solution

**Simple fix:** Wrap the synchronous call in `asyncio.to_thread()` to run it in a thread pool.

```python
# backend/main.py - Lines 703-708
resume_context, used_rag = await asyncio.to_thread(
    retrieve_rag_context,
    rag_pipeline,
    message,
    3,       # limit
    0.5      # score_threshold
)
```

**Why this is elegant:**
- Single line change (wrap existing call)
- No refactoring of RAG pipeline needed
- Uses Python's built-in thread pool
- Follows pattern already used at line 596 for `rag_pipeline.reindex`

---

## Implementation Steps

1. Edit `backend/main.py`
2. Locate lines 703-708 (the `retrieve_rag_context` call)
3. Wrap in `asyncio.to_thread()` with positional args
4. Verify `asyncio` is already imported (it is, line 3)

---

## Testing

### Manual Test 1: Verify Responses Still Work
```bash
# Start backend
cd backend && uvicorn main:app --reload --port 8000

# Open http://localhost:8000
# Ask: "What are Dakota's skills?"
# Expected: Normal response, no errors
```

### Manual Test 2: Verify Concurrent Requests
```bash
# In terminal 1: Start a slow query
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me everything about Dakota"}' &

# In terminal 2: Immediately send another query
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hi"}'

# Expected: Second query should NOT wait for first to complete
# Both should return (first may take longer, that's fine)
```

### Manual Test 3: Health Check During Load
```bash
# While a chat query is running:
curl http://localhost:8000/health

# Expected: Immediate response {"status": "ok"}
# (If health check stalls, the fix isn't working)
```

---

## Acceptance Criteria

- [ ] RAG retrieval wrapped in `asyncio.to_thread()`
- [ ] Chat responses work correctly with RAG enabled
- [ ] Concurrent requests don't block each other
- [ ] Health check responds immediately during chat processing
- [ ] No regressions in chat functionality

---

## Files Modified

- `backend/main.py` (lines 703-708 - wrap in asyncio.to_thread)

---

## Technical Notes

**Why asyncio.to_thread works here:**
- The RAG retrieval is CPU-light but I/O-heavy (API calls)
- Running in thread pool frees the event loop for other coroutines
- Python's GIL isn't a concern for I/O-bound operations

**Alternative considered:**
- Making RAG pipeline fully async with aiohttp
- Rejected: Much larger refactor, thread pool is sufficient for this traffic level

---

## Commit Message

```
fix: wrap RAG retrieval in asyncio.to_thread to prevent event loop blocking

Synchronous OpenAI/Qdrant calls were blocking all concurrent requests.
Now runs in thread pool, allowing health checks and other requests
to proceed during RAG retrieval.

Closes #002
```
