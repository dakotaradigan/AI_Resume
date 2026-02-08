# LRU Cache Prevents Resume Data Updates Without Server Restart

---
title: LRU Cache Prevents Resume Data Updates Without Server Restart
category: configuration-issues
tags:
  - lru_cache
  - resume.json
  - stale-data
  - development-workflow
module: backend
symptoms:
  - "Changes to resume.json not reflected on frontend after browser hard refresh"
  - "Stale bullet points still showing after editing resume.json"
  - "API response returns old resume data despite file changes"
date_solved: 2026-02-08
severity: low
---

## Problem Statement

After editing `data/resume.json` (updating bullet text, reordering achievements, fixing grammar), changes did not appear on the frontend even after a hard browser refresh (Cmd+Shift+R). The API endpoint `/api/resume` continued returning stale data.

## Root Cause Analysis

Three functions in `backend/main.py` use `@lru_cache(maxsize=1)`:

```python
@lru_cache(maxsize=1)
def load_system_prompt() -> str: ...

@lru_cache(maxsize=1)
def load_resume_context() -> str: ...

@lru_cache(maxsize=1)
def load_resume_json_public() -> dict: ...
```

Once called, `load_resume_json_public()` caches the resume data in memory for the lifetime of the process. Editing the JSON file on disk has no effect until the cache is cleared.

## Solution

**Option A (development):** Restart the server to clear all caches.

```bash
# Kill existing server and restart
lsof -ti :8000 | xargs kill -9
cd backend && USE_RAG=false uvicorn main:app --port 8000
```

**Option B (production):** Use the admin cache clear endpoint (no restart needed).

```bash
curl -X POST http://localhost:8000/admin/cache/clear \
  -H "X-Admin-Token: $ADMIN_TOKEN"
```

This calls `load_resume_json_public.cache_clear()` along with the other cached functions.

**Option C (development with auto-reload):** Use `uvicorn --reload` which restarts on file changes, but note that `--reload` only watches `.py` files by default, not `.json` files. You still need a manual restart or cache clear for JSON changes.

## Prevention Strategies

1. **Always restart the dev server** after editing `resume.json` -- a browser hard refresh is not sufficient
2. **Use the admin endpoint** in production to clear caches without downtime
3. **Remember:** `--reload` flag on uvicorn does NOT auto-detect `.json` file changes

## Files Involved

- `backend/main.py:332-377` - `load_system_prompt()`, `load_resume_context()`, `load_resume_json_public()` (the three cached functions)
- `backend/main.py:573-592` - `/admin/cache/clear` endpoint that clears all three caches
- `data/resume.json` - source data file

## Key Learnings

1. **`lru_cache` persists for the process lifetime** -- file changes on disk are invisible to cached functions
2. **Browser cache and server cache are independent** -- hard refresh only clears the browser side
3. **The admin cache clear endpoint exists for exactly this reason** -- use it instead of restarting in production
