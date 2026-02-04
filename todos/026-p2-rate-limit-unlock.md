---
id: "026"
status: pending
priority: p2
type: fix
title: Add rate limiting to /api/unlock endpoint
created: 2026-02-03
tags: [security]
---

# 026-P2: Rate Limit Unlock Endpoint

## Problem
The `/api/unlock` endpoint has no rate limiting, allowing unlimited password brute-force attempts.

**File:** `backend/main.py:801-830`

## Simple Fix
Apply the same `check_rate_limit()` call used in `/api/chat` to the unlock endpoint.

```python
# Add at start of unlock_chat():
rate_limit_key = _get_client_ip(request)
allowed = await store.check_rate_limit(rate_limit_key, max_requests=5, window=60.0)
if not allowed:
    return UnlockResponse(success=False, message="Too many attempts. Please wait.")
```
