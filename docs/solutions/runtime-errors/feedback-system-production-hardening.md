# Feedback System Production Hardening

---
title: Feedback System Production Hardening
category: runtime-errors
tags:
  - async
  - pydantic
  - validation
  - double-click
  - file-io
  - fastapi
module: feedback
symptoms:
  - blocking event loop
  - double submissions
  - invalid input accepted
date_solved: 2026-02-06
severity: medium
---

## Problem Statement

The feedback system for the resume assistant chatbot had several production-readiness issues:

1. **Blocking I/O** - Synchronous file writes in async endpoint blocked the event loop
2. **Double-click vulnerability** - Users could submit feedback multiple times rapidly
3. **Weak input validation** - Manual string checks instead of type-safe validation

## Root Cause Analysis

### Issue 1: Blocking Event Loop
The `log_feedback()` function performed synchronous file I/O directly in an async FastAPI endpoint, blocking the entire event loop during writes.

### Issue 2: Double Submissions
Feedback buttons remained enabled during the async submission, allowing rapid clicks to create duplicate entries.

### Issue 3: Input Validation Gaps
Used manual if-statements to validate rating values instead of leveraging Pydantic's built-in type system.

## Solution

### 1. Async File I/O with `asyncio.to_thread()`

Wrapped the synchronous `log_feedback()` call in `asyncio.to_thread()` to offload to a thread pool:

```python
@app.post("/api/feedback")
async def submit_feedback(payload: FeedbackRequest):
    """Log user feedback (thumbs up/down)."""
    await asyncio.to_thread(
        log_feedback,
        payload.session_id,
        payload.rating,
        payload.comment,
        payload.trigger
    )
    return {"success": True}
```

### 2. Double-Click Guard

Disable buttons immediately on click before any async work:

```javascript
feedback.querySelectorAll(".feedback-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (btn.disabled) return;
    feedback.querySelectorAll(".feedback-btn").forEach(b => b.disabled = true);
    // ... rest of handler
  });
});
```

### 3. Pydantic Literal Types for Validation

Replaced manual validation with type-safe Pydantic constraints:

```python
from typing import Literal
from pydantic import BaseModel, Field

class FeedbackRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=500)
    trigger: Literal["first_response", "password_unlock", ""] = ""
```

Benefits:
- Invalid ratings rejected at parse time with 422 response
- No manual if-statements needed
- Self-documenting API contract
- Type hints for IDE support

## Prevention Strategies

### Best Practices Established

1. **Always use `asyncio.to_thread()` for sync I/O in async endpoints**
2. **Disable UI elements immediately on click** - before any async operations
3. **Use Pydantic `Literal` types** for enum-like fields instead of string validation
4. **Use `Field()` constraints** for length limits (`min_length`, `max_length`)

### Testing Checklist

Before deployment, verify:
- [ ] Health check endpoint responds
- [ ] Chat API returns valid responses
- [ ] Feedback API accepts valid payloads
- [ ] Validation rejects invalid ratings
- [ ] Validation rejects empty session_id
- [ ] Validation rejects oversized comments
- [ ] Validation rejects invalid triggers
- [ ] Concurrent requests handled correctly
- [ ] Data integrity maintained under load

## Related Documentation

- [Feedback System Brainstorm](../../brainstorms/2026-02-06-feedback-system-brainstorm.md)
- [Fix Feedback Production Plan](../../plans/2026-02-06-fix-feedback-system-production-hardening-plan.md)

## Files Modified

- `backend/main.py` - FeedbackRequest model, /api/feedback endpoint
- `frontend/app.js` - addFeedbackUI, submitFeedback functions
- `backend/analytics/analytics.py` - log_feedback function (file locking)

## Key Learnings

1. **SIMPLE WINS** - Skipped rate limiting as over-engineering for portfolio scale (~50 visitors/day)
2. **Pydantic does the work** - Let the framework handle validation instead of manual checks
3. **Guard early** - Disable buttons at the start of handlers, not after async work
4. **Thread pool for sync** - `asyncio.to_thread()` is the clean way to handle sync I/O in async code
