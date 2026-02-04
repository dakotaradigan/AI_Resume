---
id: "012"
status: pending
priority: p2
type: feat
title: Add rate limit headers to responses
created: 2026-02-03
tags: [api, agent-native]
---

# 012-P2: Rate Limit Headers

## Problem
No X-RateLimit-* headers, so clients can't know their limit status.

**File:** `backend/main.py`

## Simple Fix
Add middleware to include X-RateLimit-Limit, X-RateLimit-Remaining headers.
