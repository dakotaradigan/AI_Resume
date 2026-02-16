# Citation Grounding UX

**Date:** 2026-02-12
**Updated:** 2026-02-15
**Status:** Attempted and reverted (PR #51). Needs new approach.

## What We're Building

A collapsible "Sources" section below each bot response that links to the corresponding resume sections on the same page. Clicking a source scrolls to that section with a brief gold highlight and a "Referenced" pill.

**Goal:** Build recruiter trust by showing every claim is grounded in real resume data — not hallucinated.

## Why This Approach

- **Collapsible (opt-in):** Keeps the chat clean and conversational. Recruiters who care about accuracy can expand; others aren't distracted.
- **Chips with scroll + highlight:** Provides a tangible link between the answer and the source material on the page.
- **RAG-native:** The backend already retrieves specific resume chunks via Qdrant. The citation data is a natural byproduct — we just need to surface it.

## Spec

### 1. Label
`Sources (N)` — no emoji, parenthesized count badge. Example: `Sources (2)`.

### 2. Placement
Directly under each bot bubble, above feedback buttons.

### 3. Default State
Collapsed by default. Auto-expand on low-confidence or ambiguous answers.

### 4. Chip Format
`<Project/Role> → <Section>`

Examples:
- `Ben AI → Projects`
- `Senior PM @ Wells Fargo → Experience`
- `PCAP Certification → Certifications`

### 5. Scroll Behavior
On chip click:
- Smooth scroll to the target resume section
- 1.8s gold glow on the target section (matches existing thinking pulse duration)
- Subtle "Referenced" pill appears near the section title

### 6. Mobile Behavior
Full-width wrapped chips. Minimum tap target height of 36px.

### 7. Empty-Source Fallback
If no grounded chunks are found: hide the Sources control entirely. Never show an empty `Sources (0)`.

## Key Decisions

1. **No inline citations** — the bot's conversational tone is a strength. Citations live below the response, not inside it.
2. **Source granularity = resume section level** — chips reference sections like "Experience" or "Projects", not individual bullet points. Keeps it scannable.
3. **Trust over engagement** — primary goal is credibility ("this is real data"), not driving exploration.
4. **Subtle, not prominent** — collapsed by default so it doesn't compete with the response.

## Open Questions

- **Source mapping:** Should the backend return citation metadata with each response (section IDs matched to RAG chunks), or should the frontend infer it from the response text?
- **Which responses get sources?** All grounded responses? Skip for redirect/off-topic responses?
- **Auto-expand threshold:** What defines "low-confidence / ambiguous"? RAG similarity score below a threshold? Number of chunks retrieved?
- **Feedback interaction:** Sources sit between the response and feedback UI — verify they don't compete visually.

## Rejected Alternatives

- **Inline citations ([1], [2]):** Clutters the conversational tone. Feels academic, not warm.
- **Always-visible chips:** Adds visual weight to every response. Repetitive after 3-4 exchanges.
- **Auto-highlight only (no chat UI):** Novel but impractical — recruiter may not see the resume if they haven't scrolled. No clear connection between response and source.

---

## Implementation Attempt (2026-02-15) — Reverted

### What was built (PR #51)
- Backend: Added `sources: list[dict]` to `ChatResponse`, threaded RAG chunk metadata (title, type) through `retrieve_rag_context()` to API response
- Frontend: `addSourcesUI()` function with `<details>` collapse, source chips, smooth-scroll + blue highlight on click, deduplication, reduced-motion fallback
- CSS: `.source-chip` pills, `.section-highlighted` animation, 36px mobile tap targets
- Also fixed qdrant-client v1.16 compatibility (`search()` → `query_points()`)

### What worked
- UI rendering was correct — collapsible sources appeared below bot responses
- Deduplication, scroll behavior, and highlight animation all functioned
- Codex review caught a real bug: `animationend` never fires with `prefers-reduced-motion`, fixed with setTimeout fallback
- qdrant-client fix was valid and kept after revert

### What failed — the fundamental flaw
**RAG retrieval chunks ≠ what the bot actually references.** The sources showed generic chunk titles like "Personal Information" and "Skills and Expertise" even when the bot was talking about specific things like Ben AI or the Wells Fargo integration. The assumption that "what RAG retrieved" equals "what the bot cited" was wrong.

Additionally:
- Score threshold issues: 0.5 filtered out all results. 0.2 still filtered most. 0.0 returned results but with irrelevant titles
- RAG chunk titles are too generic (section-level like "Personal Information" instead of entity-level like "Ben AI")
- Reindex endpoint broken independently (`proxies` kwarg error in OpenAI client)

### Approaches to consider for v2
1. **Prompt-based citations:** Instruct Claude to return structured citation metadata alongside the reply (which entities/sections it actually used). Most accurate but adds prompt complexity and tokens.
2. **Post-processing entity matching:** After the bot responds, scan reply text for known entities (company names, project names, skills) and map to resume sections. Lightweight but fuzzy.
3. **Better RAG chunk granularity:** Re-chunk resume data at entity level (per role, per project, per certification) with descriptive titles. Makes the current RAG-passthrough approach viable.
4. **Hybrid:** Better chunks + lightweight post-processing to filter out chunks the bot didn't actually reference.
