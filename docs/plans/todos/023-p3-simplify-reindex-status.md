---
id: "023"
status: pending
priority: p3
type: refactor
title: Simplify reindex status tracking
created: 2026-02-03
tags: [cleanup, yagni]
---

# 023-P3: Simplify Reindex Status

## Problem
Reindex status dict is over-engineered; lock already provides "is running" state.

**File:** `backend/main.py:461-467`

## Simple Fix
Remove detailed status tracking, just use `lock.locked()` check.
