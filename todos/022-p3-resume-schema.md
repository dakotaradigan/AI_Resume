---
id: "022"
status: pending
priority: p3
type: feat
title: Add Pydantic schema for resume.json
created: 2026-02-03
tags: [validation]
---

# 022-P3: Resume Schema Validation

## Problem
No schema validation for resume.json, malformed data causes runtime errors.

**File:** `backend/main.py:299-306`

## Simple Fix
Add a Pydantic model for resume structure. Low priority - data rarely changes.
