---
id: "014"
status: pending
priority: p2
type: refactor
title: Add structured error codes to responses
created: 2026-02-03
tags: [api, agent-native]
---

# 014-P2: Structured Error Responses

## Problem
Error messages are human-readable strings, not machine-parseable codes.

**File:** `backend/main.py:659-689`

## Simple Fix
Add `error_code` field to HTTPException details (e.g., "RATE_LIMIT_EXCEEDED").
