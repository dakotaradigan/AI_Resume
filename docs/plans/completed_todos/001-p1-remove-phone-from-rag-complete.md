---
id: "001"
status: complete
priority: p1
completed: 2026-02-03
type: fix
title: Remove phone number from RAG pipeline
created: 2026-02-03
tags: [security, privacy, rag]
---

# 001-P1: Remove Phone Number from RAG Pipeline

## Problem Statement

The phone number `425-283-9910` is included in the RAG vector embeddings and can be revealed through chat responses, bypassing the UI filtering that correctly removes it from `/api/resume`.

**File:** `backend/rag.py:145`

```python
# Current code includes phone in personal info chunk
text_parts = [
    f"Name: {personal.get('name', '')}",
    # ...
    f"Phone: {personal.get('phone', '')}",  # PII EXPOSURE
]
```

**Risk:** PII exposure, GDPR compliance concern, phone could appear in chat responses.

---

## Proposed Solution

**Simple fix:** Remove the phone line from the personal info chunk in `chunk_resume_data()`.

```python
# backend/rag.py - Remove line 145
text_parts = [
    f"Name: {personal.get('name', '')}",
    f"Title: {personal.get('title', '')}",
    f"Location: {personal.get('location', '')}",
    f"Summary: {personal.get('summary', '')}",
    f"Email: {personal.get('email', '')}",
    f"LinkedIn: {personal.get('linkedin', '')}",
    # REMOVED: f"Phone: {personal.get('phone', '')}",
]
```

**Why this is elegant:**
- Single line removal
- Matches the pattern in `load_resume_json_public()` which already filters phone
- No new code, just deletion

---

## Implementation Steps

1. Edit `backend/rag.py`
2. Remove line 145 (the phone line from personal info chunk)
3. Trigger RAG reindex to update vectors (phone will be gone from index)

---

## Testing

### Manual Test 1: Verify Phone Not in Chat Responses
```bash
# Start backend
cd backend && uvicorn main:app --reload --port 8000

# Open http://localhost:8000
# Ask: "What is Dakota's phone number?"
# Ask: "How can I contact Dakota?"
# Ask: "Give me Dakota's contact information"

# Expected: Phone should NOT appear in any response
# Email and LinkedIn should still appear
```

### Manual Test 2: Verify Reindex Clears Phone
```bash
# Trigger reindex (development mode, no token needed)
curl -X POST http://localhost:8000/admin/rag/reindex

# Verify new chunks don't contain phone
# Check response shows chunk count
```

### Manual Test 3: Verify /api/resume Still Works
```bash
curl http://localhost:8000/api/resume | jq '.personal'

# Expected: No "phone" field in response (already working)
```

---

## Acceptance Criteria

- [ ] Phone number removed from `chunk_resume_data()` in rag.py
- [ ] RAG reindex completed successfully
- [ ] Chat responses never include phone number (test 3+ contact-related queries)
- [ ] Email and LinkedIn still appear in contact responses
- [ ] No regressions in other chat functionality

---

## Files Modified

- `backend/rag.py` (line 145 - remove phone from personal chunk)

---

## Deployment Notes

After deploying to production:
1. Trigger reindex: `curl -X POST -H "X-Admin-Token: <token>" https://chat.dakotaradigan.io/admin/rag/reindex`
2. Verify phone not exposed in production chat

---

## Commit Message

```
fix: remove phone number from RAG pipeline to prevent PII exposure

Phone was included in personal info chunk embeddings, allowing it to
appear in chat responses. This bypassed the /api/resume filtering.

Closes #001
```
