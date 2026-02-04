---
id: "018"
status: pending
priority: p3
type: feat
title: Cache query embeddings
created: 2026-02-03
tags: [performance, rag]
---

# 018-P3: Query Embedding Cache

## Problem
Similar queries regenerate embeddings each time (API cost + latency).

**File:** `backend/rag.py:394`

## Simple Fix
Add `@lru_cache` on query embedding, or skip if traffic is low.
