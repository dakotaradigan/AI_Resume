---
module: Resume Assistant
date: 2026-02-12
problem_type: security_issue
component: documentation
symptoms:
  - "Phone number [REDACTED] visible in production chatbot responses"
  - "PII remained in system_prompt.txt after removal from resume.json"
root_cause: config_error
resolution_type: config_change
severity: high
tags: [pii, privacy, system-prompt, data-removal]
---

# Troubleshooting: Phone Number PII Leak in Production Chatbot

## Problem
Dakota's personal phone number was being returned by the chatbot in production despite having been removed from `data/resume.json`. The number was still present in two locations within `data/system_prompt.txt`.

## Environment
- Module: Resume Assistant
- Affected Component: System prompt data file (`data/system_prompt.txt`)
- Date: 2026-02-12

## Symptoms
- Chatbot responded with phone number [REDACTED] when asked "what's his phone number?"
- Phone number had been removed from `data/resume.json` but still appeared in responses
- Two hardcoded instances in `data/system_prompt.txt` (lines 29 and 198)

## What Didn't Work

**Direct solution:** The problem was identified and fixed on the first attempt once the correct source file was located. The initial confusion was that the phone number had already been removed from `resume.json`, so it was unclear why it still appeared — the system prompt is a separate data source injected directly into the LLM context.

## Solution

Removed phone number from both locations in `data/system_prompt.txt`:

**Location 1 — Rate limit handling contact section (line 29):**
```
# Before (broken):
- Phone: [REDACTED]
- Email: dakotaradigan@gmail.com

# After (fixed):
- Email: dakotaradigan@gmail.com
```

**Location 2 — Contact information section (line 198):**
```
# Before (broken):
- **Phone**: [REDACTED]
- **Email**: dakotaradigan@gmail.com

# After (fixed):
- **Email**: dakotaradigan@gmail.com
```

**Commands run:**
```bash
# Push hotfix directly to main
git push origin main

# Clear production LRU cache so new prompt takes effect
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" https://chat.dakotaradigan.io/admin/cache/clear
```

## Why This Works

1. **Root cause:** The phone number existed in two separate data sources — `resume.json` (structured data for RAG) and `system_prompt.txt` (injected directly into every LLM call). Removing it from `resume.json` only eliminated it from RAG retrieval results, but the system prompt still contained the number and was included in every API call to Claude.
2. **The fix** removes the phone number from both instances in the system prompt, eliminating the last source of PII leakage.
3. **Cache clear** was necessary because `system_prompt.txt` is loaded via `@lru_cache` in the backend — without clearing, the old cached prompt (with the phone number) would continue to be used until server restart.

## Prevention

- When removing sensitive data, audit ALL data sources: `resume.json`, `system_prompt.txt`, and Qdrant vector DB chunks
- Use `grep -r` across the entire project for any PII before considering it fully removed
- The `lru_cache` on system prompt loading means changes require either a server restart or `/admin/cache/clear` call to take effect in production
- Consider adding a CI check that greps for phone number patterns in committed files

## Related Issues

No related issues documented yet.
