---
id: "009"
status: pending
priority: p2
type: refactor
title: Batch embedding generation during indexing
created: 2026-02-03
tags: [performance, rag]
---

# 009-P2: Batch Embedding Generation

## Problem
Embeddings generated one chunk at a time during reindexing (sequential API calls).

**File:** `backend/rag.py:358-374`

## Simple Fix
Use OpenAI's batch API to embed all chunks in one call.
