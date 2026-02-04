---
id: "010"
status: pending
priority: p2
type: fix
title: Add security headers middleware
created: 2026-02-03
tags: [security]
---

# 010-P2: Add Security Headers

## Problem
Missing CSP, X-Frame-Options, X-Content-Type-Options headers.

**File:** `backend/main.py`

## Simple Fix
Add a small middleware that sets security headers on all responses.
