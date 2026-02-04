---
id: "004"
status: pending
priority: p1
type: fix
title: Make chat limit check atomic
created: 2026-02-03
tags: [security, concurrency, session]
---

# 004-P1: Make Chat Limit Check Atomic

## Problem Statement

The chat limit check and increment are separate operations with the lock released between them. This allows bypass via concurrent requests.

**Files:** `backend/main.py:668-677` (check) and `770-774` (increment)

```python
# CHECK (lock acquired, then released)
async with store._lock:
    meta = store._metadata.get(session_id, {})
    if not meta.get("unlimited", False) and meta.get("user_message_count", 0) >= settings.free_chat_limit:
        raise HTTPException(...)
# Lock released here!

# ... API call happens ...

# INCREMENT (lock acquired again)
async with store._lock:
    store._metadata[session_id]["user_message_count"] += 1
```

**Race condition:**
1. Request A: reads count=1, passes check (limit=2), releases lock
2. Request B: reads count=1 (unchanged!), also passes check
3. Both increment → user gets 3 exchanges instead of 2

**Risk:** Security bypass - users can exceed chat limit.

---

## Proposed Solution

**Add atomic method to SessionStore** that checks and increments in one operation.

```python
# backend/main.py - Add to SessionStore class

async def check_and_increment_limit(
    self,
    session_id: str,
    limit: int
) -> tuple[bool, str]:
    """
    Atomically check chat limit and increment count if allowed.

    Returns:
        (allowed, reason) - allowed=True if under limit, reason explains denial
    """
    async with self._lock:
        meta = self._metadata.get(session_id, {})

        # Unlimited users always allowed
        if meta.get("unlimited", False):
            meta["user_message_count"] = meta.get("user_message_count", 0) + 1
            return True, ""

        current_count = meta.get("user_message_count", 0)

        # At or over limit
        if current_count >= limit:
            return False, "You've reached the free chat limit. To continue, enter the password found on Dakota's resume."

        # Under limit - increment and allow
        meta["user_message_count"] = current_count + 1
        self._metadata[session_id] = meta
        return True, ""
```

**Update the chat endpoint** to use this method:

```python
# backend/main.py - Replace lines 668-677

allowed, reason = await store.check_and_increment_limit(
    session_id,
    settings.free_chat_limit
)
if not allowed:
    raise HTTPException(status_code=403, detail=reason)

# REMOVE lines 770-774 (the separate increment) - now handled atomically
```

**Why this is elegant:**
- Single lock acquisition for check+increment
- Encapsulates logic in SessionStore (fixes the encapsulation violation)
- Removes duplicate lock acquisition
- Clear, self-documenting method name

---

## Implementation Steps

1. Add `check_and_increment_limit()` method to SessionStore class
2. Replace lines 668-677 with call to new method
3. Remove lines 770-774 (the separate increment)
4. Test thoroughly with concurrent requests

---

## Testing

### Manual Test 1: Limit Still Works
```bash
# Start backend with fresh state
cd backend && uvicorn main:app --reload --port 8000

# Use a new session (new browser or incognito)
# Send 2 messages - both should work
# Send 3rd message - should get 403 with password prompt
```

### Manual Test 2: Unlimited Users Unaffected
```bash
# Get session ID from first request
SESSION_ID="<from response>"

# Unlock the session
curl -X POST http://localhost:8000/api/unlock \
  -H "Content-Type: application/json" \
  -d "{\"password\": \"<password>\", \"session_id\": \"$SESSION_ID\"}"

# Send many messages - all should work (no limit)
```

### Manual Test 3: Concurrent Requests Can't Bypass
```bash
# Create a new session
RESPONSE=$(curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "First"}')
SESSION_ID=$(echo $RESPONSE | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['session_id'])")

# Send second message (uses 2/2)
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"Second\", \"session_id\": \"$SESSION_ID\"}"

# Try to send 2 concurrent requests (both should fail or only 1 succeed)
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"Third\", \"session_id\": \"$SESSION_ID\"}" &
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"Fourth\", \"session_id\": \"$SESSION_ID\"}" &
wait

# Expected: At least one (likely both) should return 403
```

---

## Acceptance Criteria

- [ ] New `check_and_increment_limit()` method added to SessionStore
- [ ] Method is atomic (single lock acquisition)
- [ ] Chat endpoint uses new method
- [ ] Removed separate increment code (lines 770-774)
- [ ] Chat limit enforced correctly (2 messages for free users)
- [ ] Concurrent requests can't bypass limit
- [ ] Unlimited users unaffected
- [ ] No direct `store._lock` or `store._metadata` access from endpoint

---

## Files Modified

- `backend/main.py`:
  - Add `check_and_increment_limit()` to SessionStore class (~lines 85-110)
  - Update chat endpoint to use new method (~lines 668-677)
  - Remove separate increment (~lines 770-774)

---

## Bonus: Also Fix set_unlimited

While we're fixing encapsulation, add a proper method for setting unlimited:

```python
async def set_unlimited(self, session_id: str, value: bool) -> None:
    """Set unlimited access for a session."""
    async with self._lock:
        if session_id in self._metadata:
            self._metadata[session_id]["unlimited"] = value
```

Update `/api/unlock` endpoint (lines 808-810) to use this method.

---

## Commit Message

```
fix: make chat limit check atomic to prevent bypass via concurrent requests

The check and increment were separate operations, allowing race condition
bypass. Now uses atomic check_and_increment_limit() method in SessionStore.

Also fixes encapsulation by removing direct _lock/_metadata access from
the chat endpoint.

Closes #004
```
