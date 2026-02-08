---
id: "017"
status: pending
priority: p3
type: refactor
title: Remove duplicate dark theme CSS rules
created: 2026-02-03
tags: [css, cleanup]
---

# 017-P3: Remove Duplicate Dark Theme CSS

## Problem
Some `:root[data-theme="dark"]` rules are redundant because CSS variables already handle theming.

**File:** `frontend/styles.css:151-173`

## Simple Fix
Remove the redundant dark theme overrides.
