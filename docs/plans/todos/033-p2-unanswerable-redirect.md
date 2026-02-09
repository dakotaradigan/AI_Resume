---
id: "033"
status: pending
priority: p2
type: fix
title: Improve unanswerable question handling
created: 2026-02-08
tags: [evals, prompt-tuning]
---

# 033-P2: Faster Unanswerable Redirects

## Problem
When the bot can't answer, it should be quick and friendly:
"I don't have that information — I'd recommend reaching out to Dakota directly."
Instead it gives long-winded responses.

## Fix
Update system prompt to handle unanswerable questions with a brief redirect to Dakota's contact info (email only, phone removed).

## Eval IDs
62, 63, 67, 68, 70, 71, 73
