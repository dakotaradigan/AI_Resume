---
id: "030"
status: pending
priority: p1
type: fix
title: Reduce response verbosity across all categories
created: 2026-02-08
tags: [evals, prompt-tuning]
---

# 030-P1: Reduce Response Verbosity

## Problem
Eval review showed 35+ failures due to overly verbose responses. Off-topic, adversarial, and simple questions get multi-paragraph answers instead of 1-2 sentences. This also drives latency (more tokens = slower).

## Fix Areas
- System prompt: enforce stricter conciseness rules
- Off-topic/adversarial: one paragraph max, redirect quickly
- Simple factual questions: brief answer, no over-explanation
- "Tell me everything" type queries: cap response length

## Eval IDs
12, 15, 17, 18, 21, 22, 29, 33, 34, 39, 45, 46, 51, 55, 56, 58, 59, 71, 77-85, 86-100
