---
id: "032"
status: pending
priority: p2
type: enhancement
title: Update resume data with missing info
created: 2026-02-08
tags: [evals, data]
---

# 032-P2: Resume Data Updates

## Problem
Eval review revealed missing/stale data in resume.json:

- Merrill Lynch experience (2018, client associate) not in data
- BenAI model updated to GPT 5.2 (resume still says GPT-4o)
- Hobbies/interests not included (Seahawks, Packers, etc.)
- Resume Assistant should mention Claude model used
- Missing info about Parametric in direct indexing context

## Fix
Update resume.json with the above. May also need to update project markdown files.

## Eval IDs
3, 10, 28, 36, 60, 69, 83
