---
id: "006"
status: pending
priority: p2
type: refactor
title: Move session cleanup to background task
created: 2026-02-03
tags: [performance, async]
---

# 006-P2: Move Session Cleanup to Background Task

## Problem
Session cleanup runs on every chat request, iterating O(n) through all sessions.

**File:** `backend/main.py:644-647`

## Simple Fix
Move to a background task that runs every 5 minutes instead of on every request.
