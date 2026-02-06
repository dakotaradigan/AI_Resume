# Feedback Loop for AI Chatbot

**Date:** 2026-02-06
**Status:** Ready for implementation

## What We're Building

Thumbs up/down feedback buttons on each bot response, with an optional comment field when thumbs down is clicked. Feedback stored in local JSON file (matches existing queries.json pattern).

## Why This Approach

- User's goal is **signaling professionalism** to recruiters
- Thumbs up/down is the industry standard (ChatGPT, Claude, Perplexity all use it)
- Optional comment on thumbs down shows thoughtfulness without over-engineering
- Local JSON storage matches existing analytics pattern, easy to review

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Feedback type | Thumbs up/down | Industry standard, zero friction |
| Additional input | Comment on thumbs down only | Shows polish without complexity |
| Storage | Local JSON file | Matches queries.json pattern |
| Placement | Below each bot response | Standard pattern, non-intrusive |

## UI Behavior

**Feedback appears at two key moments only:**
1. After the first bot response (first impression from new visitors)
2. After successful password unlock (engaged users who unlocked full access)

**Interaction:**
1. Thumbs up/down icons appear below the message
2. Clicking thumbs up: icon highlights, saves to feedback.json, done
3. Clicking thumbs down: icon highlights, small text input appears asking "What went wrong?", submit saves to feedback.json
4. One-time feedback per trigger (disable after selection)

## Implementation Notes

- Add feedback icons to bot message template in app.js
- CSS for hover states and selected states
- New `/api/feedback` endpoint, append to `analytics/feedback.json`
- ~40-50 lines of code total

## Next Steps

Run `/workflows:plan` to generate implementation plan.
