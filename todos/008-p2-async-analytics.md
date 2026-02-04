---
id: "008"
status: pending
priority: p2
type: refactor
title: Make analytics logging async
created: 2026-02-03
tags: [performance, async]
---

# 008-P2: Async Analytics Logging

## Problem
Analytics file I/O is synchronous (blocking), even with the locking fix from 003.

**File:** `backend/analytics/analytics.py:32-37`

## Simple Fix
Use `aiofiles` or a background queue to avoid blocking the event loop.
