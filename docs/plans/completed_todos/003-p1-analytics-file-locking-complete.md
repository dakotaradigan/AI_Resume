---
id: "003"
status: pending
priority: p1
type: fix
title: Add file locking to analytics writes
created: 2026-02-03
tags: [data-integrity, analytics, concurrency]
---

# 003-P1: Add File Locking to Analytics Writes

## Problem Statement

The analytics logging function writes to `queries.json` without file locking. Concurrent requests can corrupt the JSONL file by interleaving writes.

**File:** `backend/analytics/analytics.py:32-34`

```python
# Current code - NO LOCKING, race condition
with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry) + "\n")
```

**Risk:** Corrupted JSONL lines that can't be parsed, lost analytics data.

---

## Proposed Solution

**Simple fix:** Use `fcntl.flock()` for file locking on write.

```python
import fcntl

def log_query(session_id: str, query: str, response_preview: str = "") -> None:
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "query": query,
        "response_preview": response_preview[:100] if response_preview else ""
    }

    try:
        with open(ANALYTICS_FILE, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Release lock
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to log query: {e}")
```

**Why this is elegant:**
- Uses standard library (fcntl) - no new dependencies
- Lock is held only during write (minimal contention)
- Automatic unlock via finally block
- Improved error handling (logger instead of print)

---

## Implementation Steps

1. Edit `backend/analytics/analytics.py`
2. Add `import fcntl` at top
3. Update `log_query()` function with locking pattern
4. Replace `print()` with `logging.getLogger().warning()`

---

## Testing

### Manual Test 1: Basic Logging Still Works
```bash
# Start backend
cd backend && uvicorn main:app --reload --port 8000

# Send a chat message
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}'

# Check analytics file
tail -1 backend/analytics/queries.json

# Expected: Valid JSON line with timestamp, session_id, query
```

### Manual Test 2: Concurrent Writes Don't Corrupt
```bash
# Send 10 concurrent requests
for i in {1..10}; do
  curl -s -X POST http://localhost:8000/api/chat \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"Test $i\"}" &
done
wait

# Verify all lines are valid JSON
tail -10 backend/analytics/queries.json | while read line; do
  echo "$line" | python3 -c "import json,sys; json.loads(sys.stdin.read())" && echo "OK" || echo "CORRUPT"
done

# Expected: All lines should print "OK"
```

### Manual Test 3: Verify No File Permission Issues
```bash
# Remove analytics file and let it recreate
rm backend/analytics/queries.json

# Send a message
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "First message"}'

# Verify file created and has content
cat backend/analytics/queries.json

# Expected: Single valid JSON line
```

---

## Acceptance Criteria

- [ ] `fcntl` import added to analytics.py
- [ ] `log_query()` uses exclusive file locking
- [ ] Lock released in finally block (never leaks)
- [ ] Error handling uses logger instead of print
- [ ] Concurrent writes produce valid JSONL (no corruption)
- [ ] No performance degradation (locks are brief)

---

## Files Modified

- `backend/analytics/analytics.py` (add locking to log_query)

---

## Platform Note

`fcntl` is Unix-only. If Windows support is needed in the future, consider:
- `portalocker` package (cross-platform)
- Or document Unix-only requirement

For this project (Railway deployment = Linux), `fcntl` is appropriate.

---

## Commit Message

```
fix: add file locking to analytics writes to prevent corruption

Concurrent requests could interleave writes to queries.json, producing
malformed JSONL. Now uses fcntl exclusive locking during writes.

Also improved error handling to use logger instead of print.

Closes #003
```
