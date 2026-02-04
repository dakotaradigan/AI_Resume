---
id: "019"
status: pending
priority: p3
type: feat
title: Add analytics log rotation
created: 2026-02-03
tags: [analytics, ops]
---

# 019-P3: Analytics Log Rotation

## Problem
Analytics file grows unbounded.

**File:** `backend/analytics/analytics.py`

## Simple Fix
Rotate logs daily or by size, or just periodically delete old entries manually.
