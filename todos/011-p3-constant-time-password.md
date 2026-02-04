---
id: "011"
status: pending
priority: p3
type: fix
title: Use constant-time password comparison
created: 2026-02-03
tags: [security]
---

# 011-P3: Constant-Time Password Comparison

## Problem
Password comparison vulnerable to timing attacks.

**File:** `backend/main.py:816-818`

## Simple Fix
Use `secrets.compare_digest()` instead of `!=`.
