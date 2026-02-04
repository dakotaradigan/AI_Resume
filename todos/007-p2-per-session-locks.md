---
id: "007"
status: pending
priority: p2
type: refactor
title: Consider per-session locks instead of global lock
created: 2026-02-03
tags: [performance, concurrency]
---

# 007-P2: Per-Session Locks

## Problem
Single global lock serializes all session operations, causing contention under load.

**File:** `backend/main.py:47`

## Simple Fix
Use per-session locks or evaluate if current traffic warrants this complexity.
