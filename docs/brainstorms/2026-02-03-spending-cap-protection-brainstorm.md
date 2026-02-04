# Spending Cap Protection

**Date:** 2026-02-03
**Status:** Ready for implementation

## What We're Building

Two-layer protection against unexpected API costs:

1. **Daily conversation cap** - Limit total conversations per day (e.g., 50)
2. **Graceful 429 handling** - Friendly message when Anthropic rate limit hit

## Why This Approach

- User has Anthropic spending cap but wants graceful degradation
- Password holders could share access, causing unexpected volume
- Portfolio site must maintain professional appearance even when limited
- "SIMPLE WINS" - ~25 lines total, no external dependencies

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary protection | Daily cap | Proactive, predictable costs |
| Secondary protection | 429 detection | Backup if cap misconfigured |
| Message tone | Friendly, on-brand | "Taking a break" not "error" |
| Reset timing | Daily (midnight or rolling) | Simple, predictable |

## Friendly Message (Draft)

> "Lots of interest today! The AI assistant is taking a quick break.
> Feel free to reach out directly at dakotaradigan@gmail.com or connect on LinkedIn.
> We'll be back soon!"

## Implementation Notes

- Store daily counter in memory (fine for single Railway instance)
- Track by date string, reset when date changes
- Catch `RateLimitError` specifically from Anthropic SDK
- Both protections show the same friendly message

## Open Questions

- [ ] What daily limit? (Suggest: 50-100 conversations)
- [ ] Reset at midnight UTC or Pacific?

## Next Steps

Run `/workflows:plan` to generate implementation plan.
