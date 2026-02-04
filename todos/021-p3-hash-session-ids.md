---
id: "021"
status: pending
priority: p3
type: refactor
title: Hash session IDs in analytics logs
created: 2026-02-03
tags: [privacy, analytics]
---

# 021-P3: Hash Session IDs

## Problem
Raw session IDs in analytics enable session correlation.

**File:** `backend/analytics/analytics.py:24`

## Simple Fix
Hash with `hashlib.sha256(session_id.encode()).hexdigest()[:16]`.
