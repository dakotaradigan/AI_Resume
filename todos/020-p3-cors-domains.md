---
id: "020"
status: pending
priority: p3
type: fix
title: Verify CORS domains match production
created: 2026-02-03
tags: [config]
---

# 020-P3: CORS Domain Alignment

## Problem
Hardcoded CORS origins may not match actual production domain.

**File:** `backend/main.py:477-479`

## Simple Fix
Verify domains match, consider making configurable via env var.
