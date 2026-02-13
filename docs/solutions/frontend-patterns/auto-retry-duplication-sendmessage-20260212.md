# Auto-Retry After Unlock Duplicated Fetch Logic and User Message

---
title: Auto-Retry After Unlock Duplicated Fetch Logic and User Message
category: frontend-patterns
tags:
  - sendMessage
  - auto-retry
  - unlock-flow
  - code-duplication
  - race-condition
module: frontend
symptoms:
  - "User's message appears twice in chat after password unlock"
  - "30 lines of duplicated fetch/parse/error logic nested 7+ levels deep"
  - "setSending(false) fires too early on 403 path, re-enabling input during unlock form"
  - "Focus lost after bot response — user must click back into input"
date_solved: 2026-02-12
severity: medium
---

## Problem Statement

After implementing auto-retry (re-submitting the user's blocked question after a successful password unlock), three bugs emerged:

1. **Duplicated logic:** The retry path copied 30 lines of fetch/parse/error handling from `sendMessage()` instead of reusing it.
2. **Double message:** Calling `sendMessage(message)` for the retry added the user's message bubble a second time (since `sendMessage` starts with `addMessage(message, "user")`).
3. **Focus loss:** After every bot response, the cursor didn't return to the input field.

## Root Cause Analysis

The auto-retry was implemented as a nested `try/catch/finally` inside the unlock form's submit handler, duplicating the entire `/api/chat` fetch, response parsing, error handling, `is-thinking` class management, feedback UI attachment, and scroll behavior. This created 8 levels of nesting and scattered `is-thinking` class removal across 5+ locations.

The double message occurred because `sendMessage()` unconditionally calls `addMessage(message, "user")` at the top — fine for the initial call, but the retry should skip this since the message is already displayed.

## Solution

### Fix 1: Reuse `sendMessage()` instead of duplicating (P1)

Replace 30 lines of nested fetch logic with 3 lines:

```javascript
// Before (30 lines of duplicated fetch/parse/error/finally)
if (unlockData.success) {
  thinkingEl.classList.add("is-thinking");
  body.innerHTML = getThinkingMarkup("Unlocked. Resubmitting");
  setSending(true);
  try {
    const retryRes = await fetch("/api/chat", { ... });
    // ... 20+ lines of response handling ...
  } finally {
    setSending(false);
  }
}

// After (3 lines)
if (unlockData.success) {
  thinkingEl.remove();
  sendMessage(message, { isRetry: true });
  return;
}
```

### Fix 2: Skip `addMessage` on retry

```javascript
// Before
async function sendMessage(message) {
  addMessage(message, "user");

// After
async function sendMessage(message, { isRetry = false } = {}) {
  if (!isRetry) addMessage(message, "user");
```

### Fix 3: Focus input after response

```javascript
} finally {
  setSending(false);
  chatInput.focus();  // Added — cursor returns to input
}
```

## Prevention

- **Don't duplicate async fetch logic.** If a function already handles fetch + parse + error + UI state, reuse it with a flag rather than copying the logic into a nested context.
- **When calling a function in a "retry" context, check what side effects the function performs at the top** (like adding UI elements) and provide a way to skip them.
- **Run multi-agent code review** (`/workflows:review`) — this duplication was flagged as P1 by 3 out of 6 review agents independently.

## Related

- PR #39: `feat/frontend-ux-polish`
- The `setSending(false)` race condition on the 403 path was also fixed as a side effect — `sendMessage()` manages its own `setSending` lifecycle correctly.
