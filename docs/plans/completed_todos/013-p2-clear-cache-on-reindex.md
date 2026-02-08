---
id: "013"
status: completed
priority: p2
type: fix
title: Clear LRU cache on RAG reindex
created: 2026-02-03
tags: [rag, cache]
---

# 013-P2: Clear LRU Cache on Reindex

## Problem
LRU cache not cleared after reindex, so stale fallback context may be served.

**File:** `backend/main.py:546-618`

## Simple Fix
Call `load_resume_context.cache_clear()` after successful reindex.
