# fix: Feedback System Production Hardening

**Date:** 2026-02-06
**Type:** fix
**Status:** Ready for implementation

## Overview

The feedback system implementation passed architectural and simplicity reviews but has 4 critical issues identified by security, performance, and frontend race condition reviewers that must be fixed before production deployment.

## Problem Statement

Six review agents analyzed the feedback system and identified these production-blocking issues:

1. **Missing rate limiting** - `/api/feedback` endpoint can be spammed
2. **Sync I/O blocks event loop** - File writes block all concurrent requests
3. **Double-click vulnerability** - Users can submit duplicate feedback
4. **No backend input validation** - Comment field has no length limit

## Proposed Solution

Apply 4 targeted fixes (~20 minutes total effort) to harden the feedback system.

---

## Implementation Tasks

### Task 1: Add Rate Limiting to Feedback Endpoint

**File:** `backend/main.py`
**Effort:** 5 minutes
**Severity:** HIGH (Security)

**Problem:** The `/api/feedback` endpoint has no rate limiting. Attackers can spam it to fill disk space or perform DoS.

**Solution:** Apply existing rate limiting pattern from chat endpoint.

```python
@app.post("/api/feedback")
async def submit_feedback(payload: FeedbackRequest, request: Request):
    """Log user feedback (thumbs up/down)."""
    # Add rate limiting (reuse existing pattern)
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = await store.check_rate_limit(f"feedback:{client_ip}", limit=10, window=60)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait.")

    if payload.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Rating must be 'up' or 'down'")
    # ... rest of endpoint
```

**Acceptance Criteria:**
- [ ] Rate limit of 10 feedback submissions per minute per IP
- [ ] Returns 429 status when limit exceeded

---

### Task 2: Wrap File I/O in Thread Pool

**File:** `backend/main.py`
**Effort:** 5 minutes
**Severity:** HIGH (Performance)

**Problem:** `log_feedback()` uses synchronous file I/O which blocks the async event loop, degrading throughput for all concurrent requests.

**Solution:** Wrap the call in `asyncio.to_thread()`.

```python
@app.post("/api/feedback")
async def submit_feedback(payload: FeedbackRequest, request: Request):
    # ... validation ...

    # Run file I/O in thread pool to avoid blocking event loop
    await asyncio.to_thread(
        log_feedback,
        payload.session_id,
        payload.rating,
        payload.comment,
        payload.trigger
    )
    return {"success": True}
```

**Acceptance Criteria:**
- [ ] `log_feedback` runs in thread pool
- [ ] Event loop not blocked during file writes

---

### Task 3: Add Double-Click Guard to Frontend

**File:** `frontend/app.js`
**Effort:** 5 minutes
**Severity:** HIGH (Data Integrity)

**Problem:** Feedback buttons have no protection against rapid multiple clicks, causing duplicate submissions.

**Solution:** Add `isSubmitting` flag and disable buttons immediately.

```javascript
function addFeedbackUI(messageEl, trigger) {
  let isSubmitting = false;  // Add guard flag

  // ... create feedback element ...

  feedback.querySelectorAll(".feedback-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (isSubmitting) return;  // Guard against double-click
      isSubmitting = true;

      // Disable both buttons visually
      feedback.querySelectorAll(".feedback-btn").forEach(b => b.disabled = true);

      const rating = btn.dataset.rating;
      btn.classList.add("selected");
      // ... rest of handler
    });
  });

  // Same pattern for comment submit button
}
```

**Acceptance Criteria:**
- [ ] Buttons disabled after first click
- [ ] No duplicate submissions possible
- [ ] Visual feedback that button was clicked

---

### Task 4: Add Pydantic Field Validation

**File:** `backend/main.py`
**Effort:** 5 minutes
**Severity:** MEDIUM (Security)

**Problem:** `comment` field has no length limit in backend. Frontend limit (200 chars) can be bypassed.

**Solution:** Add Pydantic field constraints.

```python
from pydantic import BaseModel, Field
from typing import Literal

class FeedbackRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=500)
    trigger: Literal["first_response", "password_unlock", ""] = ""
```

**Acceptance Criteria:**
- [ ] `session_id` required, max 100 chars
- [ ] `rating` only accepts "up" or "down" (via Literal type)
- [ ] `comment` max 500 chars
- [ ] `trigger` only accepts valid values

---

## Review Findings Summary

| Reviewer | Verdict | Key Finding |
|----------|---------|-------------|
| Security Sentinel | MEDIUM | Missing rate limiting, input validation |
| Performance Oracle | HIGH | Sync I/O blocks event loop |
| Julik Frontend Races | HIGH | Double-click vulnerability |
| Data Integrity Guardian | HIGH | Non-atomic writes, silent failures |
| Code Simplicity | PASS | No over-engineering |
| Architecture Strategist | APPROVED | Follows existing patterns |

## Success Metrics

- [ ] All 4 fixes implemented
- [ ] No duplicate feedback entries in logs
- [ ] Event loop latency unchanged under load
- [ ] Rate limiting prevents abuse

## References

- Security audit: agent a03e6fc
- Performance review: agent a0643a3
- Frontend races review: agent ac2c034
- Data integrity review: agent a622b7b
- Brainstorm: `docs/brainstorms/2026-02-06-feedback-loop-brainstorm.md`
