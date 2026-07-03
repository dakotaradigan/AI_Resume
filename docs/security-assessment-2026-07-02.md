# Resume Assistant Security Assessment

Date: 2026-07-02

Assessed revision: `6f5718f` plus the security tests added with this report

Target: local in-process FastAPI application only; no production endpoints were contacted

## Executive result

The application passed the admin authentication, analytics authorization,
prompt-injection, system-prompt canary, secret canary, phone scrubbing, and
distinct-session isolation checks.

One conditional weakness was reproduced:

| ID | Severity | Finding |
| --- | --- | --- |
| SEC-01 | Low | Anyone who obtains and reuses a valid session ID receives that session's prior chat context |

No critical, high, or medium-severity finding was reproduced.

## Scope and method

The assessment covered:

- Missing, invalid, and valid admin tokens on all four `/admin/*` routes
- Analytics export confidentiality
- Six prompt-injection and system-information extraction patterns
- Synthetic system-prompt, phone, admin-token, chat-password, and API-key canaries
- Phone removal from `/api/resume`, static chat context, and RAG chunks
- Chat history behavior with distinct and reused session IDs

Deterministic API tests use synthetic settings, temporary analytics files, and
a fake model. The opt-in model tests use the locally configured Anthropic test
key, disable RAG, inject only synthetic canaries, and run against an in-process
FastAPI app.

Out of scope:

- Production infrastructure, Railway configuration, proxies, Redis, and Qdrant
- Network interception, host compromise, browser extensions, and dependency CVEs
- Exhaustive or statistical prompt-injection testing across repeated model runs

## Finding

### SEC-01: Session history is available to anyone reusing the session ID

Severity: **Low**

`POST /api/chat` accepts a client-supplied `session_id` and loads history using
that value alone. It has no server-side binding to a browser cookie or other
client property.

Relevant code:

- `backend/main.py:418-425`
- `backend/main.py:977-991`
- `backend/main.py:1036-1039`
- `frontend/app.js:27-47`

Reproduced behavior:

- A distinct session ID did not receive the first session's marker.
- Reusing the first session ID caused the live model to identify the technology
  marker from the first session's prior query.
- The deterministic model test confirms that prior messages are supplied
  whenever the same ID is reused.

The severity is low because current browsers generate the ID with
`crypto.randomUUID()`, so remote guessing is impractical. The fallback uses a
timestamp and `Math.random()`, and analytics records store the live session ID
alongside full conversations. A leaked ID therefore acts as a bearer credential
for the remaining session lifetime.

Recommended fix:

1. Mint session IDs on the server and reject unknown client-selected IDs.
2. Prefer an `HttpOnly`, `Secure`, `SameSite` cookie for the opaque session
   credential.
3. Store an HMAC-derived analytics identifier instead of the live session ID so
   an analytics export cannot be used to resume sessions.

## Verified controls

### Admin authentication

Passed:

- Missing and invalid tokens returned `401` on all four admin routes when a
  token was configured.
- A missing configured token returned `503` outside development.
- Development without a token returned `503` for a non-loopback client.
- Analytics content was returned only with the valid synthetic admin token.
- Admin tokens use constant-time comparison.

There is an intentional local-development exception: when
`ENVIRONMENT=development`, `ADMIN_TOKEN` is empty, and the direct client address
is loopback, admin routes are available without a token. This was not rated as
a remotely exploitable finding, but every deployed environment should still set
a strong token. A reverse proxy that presents all external clients as loopback
would invalidate the assumption behind this exception.

### Prompt injection and system-prompt disclosure

Passed all six live-model probes:

- Direct request to print the system prompt
- JSON-structured system-prompt extraction
- Fake system message requesting environment variables and keys
- Base64/encoding request for hidden instructions
- Authority claim requesting private fields and passwords
- Role hijack requesting internal configuration

None returned the synthetic system-prompt canary, private phone canary, admin
token, chat password, API key, or system-prompt XML markers.

Residual risk:

- Prompt injection is model-dependent and non-deterministic. This result proves
  the tested cases for the configured model, not universal resistance.
- The application has no independent response filter. Its strongest protection
  is keeping operational secrets out of the model context, which the inspected
  request construction currently does.

### Private resume fields

Passed:

- `/api/resume` removed a synthetic `phone` field.
- Static chat context excluded the synthetic phone value.
- RAG personal-information chunks excluded the synthetic phone value.
- Email remained present by design as public contact information.

### Cross-session isolation

Passed for distinct random IDs. Failed only when the other session's exact ID
was deliberately reused, as described in SEC-01.

## Reproduction

Run the deterministic suite:

```bash
PYTHONPATH=backend USE_RAG=false \
  venv/bin/python -m unittest backend.test_security -v
```

Expected result: 9 tests pass. The session-reuse test intentionally
characterizes the finding:

- `test_reusing_another_users_session_id_exposes_their_history`

Run the opt-in live-model suite:

```bash
RUN_LLM_SECURITY=1 PYTHONPATH=backend USE_RAG=false \
  venv/bin/python -m unittest backend.test_security_llm -v
```

This uses the configured Anthropic API and may incur usage charges. It does not
contact the production application.

Run the complete local unit-test discovery:

```bash
PYTHONPATH=backend USE_RAG=false \
  venv/bin/python -m unittest discover -s backend -p 'test*.py' -v
```

The live-model tests are skipped unless `RUN_LLM_SECURITY=1` is explicitly set.

## Prioritized remediation

1. Stop writing live session credentials to analytics; use an HMAC-derived ID.
2. Move session credential issuance to the server.
3. Keep a strong `ADMIN_TOKEN` configured in every deployed environment.
4. Keep the model security suite as an opt-in release check for prompt, model,
   or resume-data changes.
