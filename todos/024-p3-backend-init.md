---
id: "024"
status: pending
priority: p3
type: fix
title: Add __init__.py to backend
created: 2026-02-03
tags: [python, packaging]
---

# 024-P3: Add __init__.py

## Problem
Backend directory lacks `__init__.py`, not a proper Python package.

**File:** `backend/`

## Simple Fix
Add empty `__init__.py`. Low priority - works fine without it.
