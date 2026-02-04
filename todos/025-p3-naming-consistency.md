---
id: "025"
status: pending
priority: p3
type: refactor
title: Fix minor naming inconsistency in app.js
created: 2026-02-03
tags: [cleanup, js]
---

# 025-P3: Naming Consistency

## Problem
`suggestionsEl` uses `El` suffix but similar variables don't.

**File:** `frontend/app.js:25`

## Simple Fix
Rename to `suggestions` for consistency, or ignore (very minor).
