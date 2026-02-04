---
id: "015"
status: pending
priority: p2
type: fix
title: Return copy of history list instead of reference
created: 2026-02-03
tags: [data-integrity]
---

# 015-P2: Return History Copy

## Problem
`get_history()` returns direct reference to internal list, allowing mutation outside lock.

**File:** `backend/main.py:49-54`

## Simple Fix
Return `list(self._messages[session_id])` instead of direct reference.
