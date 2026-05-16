# Redis Visitor Quota Plan

## Goal

Deploy Railway Redis and use it as the shared production state store for anonymous visitor quotas, password unlock state, rate limits, and daily cost controls. The main product goal is to prevent a visitor from bypassing the free chat limit by refreshing, starting a new chat, or changing the client-side `session_id`.

This is a planning artifact only. Implementation should happen in a later PR.

## Chosen Defaults

- **Redis provider:** Railway Redis, wired through `REDIS_URL`.
- **Visitor identity:** server-issued anonymous visitor cookie.
- **Cookie shape:** HttpOnly, same-site, secure in production, max-age aligned to visitor quota TTL.
- **Unlock scope:** same visitor/browser/device.
- **Quota persistence:** refresh and new chat retain quota and unlock state for the same visitor.
- **No login system:** clearing cookies or using private browsing can still reset identity; preventing that requires authentication or a stricter cookie-plus-IP policy.

## Implementation Outline

1. Add configuration for visitor identity and proxy behavior:
   - `VISITOR_COOKIE_NAME=resume_assistant_visitor_id`
   - `VISITOR_TTL_SECONDS=2592000`
   - `TRUST_PROXY_HEADERS=false`
2. Add backend helper logic to resolve visitor identity:
   - Read the visitor cookie from the request.
   - If missing or malformed, generate a UUID visitor ID.
   - Attach a `Set-Cookie` response with `HttpOnly`, `SameSite=Lax`, `Secure` in production, `Path=/`, and a matching max age.
3. Move free chat quota and password unlock state from frontend-provided `session_id` to server-owned visitor ID.
   - Keep `session_id` for conversation history and UI continuity only.
   - Do not trust `session_id` for quota or unlock authorization.
4. Update `/api/chat` flow:
   - Validate the message.
   - Resolve visitor ID.
   - Apply rate limiting using a safe client IP.
   - Reserve daily global quota atomically before the Anthropic call.
   - Apply the free chat limit against the visitor record.
5. Update `/api/unlock` flow:
   - Resolve visitor ID.
   - Rate-limit unlock attempts by safe IP and visitor ID.
   - On valid password, set `unlimited=true` on the visitor record.
6. Harden Redis-backed limits:
   - Add `check_and_increment_daily_limit(day_key, limit)`.
   - Redis path should use Lua or another atomic transaction.
   - In-memory path should use the existing async lock.
7. Fix related security issues from review:
   - Stop trusting `X-Forwarded-For` unless explicit trusted proxy mode is enabled.
   - Remove query-string admin token support from `/admin/analytics/export`; require `X-Admin-Token`.
   - Require `ADMIN_TOKEN` for admin endpoints outside an explicit local-development bypass.
   - Remove unused `python-multipart` or upgrade it before adding multipart/form endpoints.

## Acceptance Criteria

- A visitor who hits the free chat limit remains blocked after refresh.
- A visitor who hits the free chat limit remains blocked after starting a new chat/session in the same browser.
- A visitor who enters the password stays unlocked after refresh and new chat/session in the same browser.
- Frontend `session_id` can change without resetting quota or unlock state.
- Redis is active in production and stores visitor quota/unlock state.
- Daily cost cap is checked and incremented atomically.
- Spoofed `X-Forwarded-For` does not bypass rate limits when trusted proxy mode is disabled.
- Admin analytics export no longer accepts `?token=`.

## Test Plan

### Unit Tests

- Missing visitor cookie creates a visitor ID and response cookie.
- Existing valid visitor cookie is reused.
- Free chat limit blocks after the configured count per visitor.
- Password unlock sets visitor-level unlimited state.
- Same visitor with a different `session_id` keeps quota/unlock state.
- In-memory daily quota check is atomic under concurrent requests.

### Integration / Manual Tests

- With Redis enabled, ask until blocked, refresh, and confirm the visitor is still blocked.
- Start a new chat/session in the same browser and confirm the visitor is still blocked.
- Enter the password, refresh, and confirm the visitor remains unlocked.
- Start a new chat/session after unlock and confirm the visitor remains unlocked.
- Confirm `/health` returns ok after Redis is attached.
- Confirm backend startup logs indicate Redis-backed session store usage.

### Security Regression Tests

- Requests with different spoofed `X-Forwarded-For` values still share the same rate-limit bucket when `TRUST_PROXY_HEADERS=false`.
- `/admin/analytics/export?token=...` is rejected.
- `/admin/analytics/export` succeeds with a valid `X-Admin-Token`.
- Admin endpoints fail closed in non-local environments without `ADMIN_TOKEN`.

## Deployment Checklist

- Add Railway Redis service.
- Confirm `REDIS_URL` is present in the Railway app environment.
- Set `VISITOR_TTL_SECONDS` and `VISITOR_COOKIE_NAME` or rely on safe defaults.
- Keep `TRUST_PROXY_HEADERS=false` unless the proxy behavior is verified.
- Set and rotate `ADMIN_TOKEN` if query-string token access was used before.
- Deploy backend.
- Verify Redis-backed behavior with manual browser tests.

## GitHub Issue Template

Suggested issue title:

```text
Implement Redis-backed visitor quotas and unlock persistence
```

Suggested issue body:

```markdown
## Why

Today chat limits are tied to the frontend-provided `session_id`. Refresh usually preserves that value through localStorage, but new chat/session flows, localStorage clearing, private browsing, or manually changed `session_id` can reset the free chat count. We need server-owned visitor identity backed by Redis so the quota and password unlock state survive refresh/new chat for the same browser.

## Tasks

- Deploy Railway Redis and verify `REDIS_URL` in production.
- Add an HttpOnly server-issued visitor cookie.
- Key free chat quota and password unlock state by visitor ID, not frontend `session_id`.
- Keep `session_id` only for conversation history.
- Make the daily API cost cap atomic.
- Harden rate limiting by removing direct trust in `X-Forwarded-For`.
- Remove query-string admin token support.
- Require admin endpoints to fail closed outside explicit local development.

## Acceptance Criteria

- Refresh cannot reset the free chat quota.
- Starting a new chat/session in the same browser cannot reset the free chat quota.
- Password unlock persists for the same visitor across refresh/new chat.
- Redis is active in production for visitor quota/unlock state.
- Tests cover visitor quota, unlock persistence, daily cap atomicity, and security regressions.

Plan: `docs/plans/redis-visitor-quota.md`
```
