---
id: "016"
status: pending
priority: p2
type: refactor
title: Consider splitting main.py into modules
created: 2026-02-03
tags: [architecture]
---

# 016-P2: Split main.py

## Problem
main.py is 830+ lines handling multiple concerns.

**File:** `backend/main.py`

## Simple Fix
Consider extracting: `session.py`, `routes/chat.py`, `routes/admin.py` when it becomes painful.
