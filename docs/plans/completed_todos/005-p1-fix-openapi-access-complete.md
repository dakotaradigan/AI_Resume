---
id: "005"
status: pending
priority: p1
type: fix
title: Fix OpenAPI/Swagger access blocked by static mount
created: 2026-02-03
tags: [api, documentation, agent-native]
---

# 005-P1: Fix OpenAPI/Swagger Access

## Problem Statement

The `StaticFiles` mount at `/` catches all routes, blocking access to FastAPI's built-in `/docs` and `/openapi.json` endpoints.

**File:** `backend/main.py:818-824`

```python
# Current code - catches ALL routes including /docs
app.mount(
    "/",
    StaticFiles(directory=frontend_dir, html=True),
    name="frontend",
)
```

**Risk:** API discoverability blocked - agents and developers can't discover endpoints.

---

## Proposed Solution

**Option A (Recommended): Mount static files AFTER defining API routes**

FastAPI's router takes precedence over mounted apps when routes are defined first. The current code already defines routes before the mount, but we need to ensure the order is correct and add explicit routes for docs.

Actually, looking at the code structure, the issue is that `StaticFiles(html=True)` serves `index.html` for any path not matching a file. We need to exclude API paths.

**Simple fix:** The code already works correctly because:
1. FastAPI routes (`/api/*`, `/admin/*`, `/health*`) are defined before the mount
2. Those routes take precedence

Let me verify this is actually an issue...

```bash
# Test if /docs works
curl -s http://localhost:8000/docs | head -5
curl -s http://localhost:8000/openapi.json | head -5
```

If `/docs` returns the frontend HTML instead of Swagger, the fix is:

**Option B: Add explicit routes for docs before static mount**

```python
# backend/main.py - Before the static mount (around line 817)

# Ensure API documentation routes are accessible
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import JSONResponse

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title + " - Swagger UI"
    )

@app.get("/openapi.json", include_in_schema=False)
async def openapi():
    return JSONResponse(app.openapi())

# Then the static mount...
```

**Why this is elegant:**
- Explicit routes for docs take precedence over static mount
- No changes to how frontend is served
- Standard FastAPI patterns

---

## Implementation Steps

1. First, test if `/docs` is actually blocked:
   ```bash
   cd backend && uvicorn main:app --reload --port 8000
   curl http://localhost:8000/docs
   ```
2. If blocked (returns HTML instead of Swagger), add explicit doc routes
3. Test that both `/docs` and `/openapi.json` work
4. Verify frontend still works at `/`

---

## Testing

### Manual Test 1: Swagger UI Accessible
```bash
# Start backend
cd backend && uvicorn main:app --reload --port 8000

# Check /docs returns Swagger UI (not frontend HTML)
curl -s http://localhost:8000/docs | grep -i "swagger\|openapi"

# Expected: Should contain "swagger" or "openapi" references
# NOT the frontend HTML with "Dakota Radigan"
```

### Manual Test 2: OpenAPI JSON Accessible
```bash
curl -s http://localhost:8000/openapi.json | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('info', {}).get('title', 'NO TITLE'))"

# Expected: "Resume Assistant"
```

### Manual Test 3: Frontend Still Works
```bash
# Open http://localhost:8000 in browser
# Expected: Normal chatbot UI with hero section, chat interface

# Also verify deep links work:
curl -s http://localhost:8000/ | grep "Dakota Radigan"
# Expected: Should contain the name (frontend HTML)
```

### Manual Test 4: API Endpoints Still Work
```bash
curl http://localhost:8000/health
# Expected: {"status": "ok"}

curl http://localhost:8000/api/resume | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['personal']['name'])"
# Expected: "Dakota Radigan"
```

---

## Acceptance Criteria

- [ ] `/docs` returns Swagger UI (not frontend HTML)
- [ ] `/openapi.json` returns valid OpenAPI schema
- [ ] Frontend at `/` still works normally
- [ ] All existing API endpoints unaffected
- [ ] ReDoc at `/redoc` works (optional, FastAPI default)

---

## Files Modified

- `backend/main.py` (add explicit doc routes before static mount, ~line 817)

---

## Alternative Approach (Not Recommended)

Could also fix by mounting frontend at a different path:

```python
app.mount("/app", StaticFiles(directory=frontend_dir, html=True))
```

But this changes the frontend URL which may break bookmarks and requires redirects. Not worth the complexity.

---

## Agent-Native Benefit

Once `/docs` and `/openapi.json` are accessible:
- Agents can discover all available endpoints
- API clients can auto-generate from OpenAPI spec
- Improves developer experience for anyone integrating

---

## Commit Message

```
fix: add explicit routes for /docs and /openapi.json

StaticFiles mount was catching all routes including API documentation.
Added explicit routes that take precedence, restoring Swagger UI access.

Improves API discoverability for agents and developers.

Closes #005
```
