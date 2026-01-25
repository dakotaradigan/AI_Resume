---
title: Fix excessive bullet spacing in chatbot responses
type: fix
date: 2026-01-24
---

# Fix: Excessive Bullet Spacing in Chatbot Responses

## Problem Statement

Chatbot responses show large gaps between bullet points despite CSS changes. The screenshot shows visible spacing between each bullet item that makes responses harder to scan.

**Root Cause Analysis:**
After examining the code, the problem is **NOT CSS** - it's a combination of:
1. **Claude adding blank lines between bullets** in its responses (violating system prompt)
2. **Markdown parser splitting on double newlines** (`frontend/app.js:102`) - treating each bullet as a separate paragraph

**Evidence:**
- System prompt clearly states: "Do NOT add blank lines between bullets" (line 48)
- Markdown parser splits on `\n\n+` pattern (double newlines)
- If Claude outputs bullets with blank lines between them, each bullet becomes a separate `<p>` tag

**Why CSS changes didn't work:**
- CSS can only control spacing of properly-formed `<li>` elements within a single `<ul>`
- But if bullets are split into separate `<ul>` blocks by the parser, CSS can't help

## Proposed Solution

### Option A: Fix Claude's Output (Recommended)
**Make Claude strictly follow the "no blank lines" instruction**

Strengthen the system prompt formatting rules:

```
## Formatting (CRITICAL)
When using bullet lists, you MUST follow these rules exactly:
- Each bullet on a single line starting with "- "
- NO blank lines between bullets
- NO extra whitespace or line breaks within the list

Example of CORRECT formatting:
- First item
- Second item
- Third item

Example of WRONG formatting (DO NOT DO THIS):
- First item

- Second item

- Third item
```

**Files to modify:**
- `data/system_prompt.txt` (lines 45-48)

### Option B: Make Parser More Forgiving
**Adjust markdown parser to handle bullets with blank lines**

Modify the regex that creates `<ul>` blocks to capture bullets even when separated by single/double newlines:

```javascript
// Current (line 99):
html = html.replace(/(<li>.*?<\/li>\n?)+/gs, (match) => `<ul>${match}</ul>`);

// Updated:
html = html.replace(/(<li>.*?<\/li>(\n\n?)?)+/gs, (match) => `<ul>${match.replace(/\n\n/g, '\n')}</ul>`);
```

This captures bullets separated by blank lines and removes the extra newlines within the `<ul>` block.

**Files to modify:**
- `frontend/app.js` (line 99)

### Option C: Both (Belt + Suspenders)
Implement both fixes for maximum reliability.

## Recommended Approach

**Start with Option A** (fix Claude's output):
- Cleaner long-term solution
- Claude should follow formatting instructions
- No parser complexity added

**If Option A doesn't work after testing:**
- Fall back to Option B (parser fix)
- This handles cases where Claude occasionally violates the rule

## Implementation Steps

### Step 1: Strengthen System Prompt (Option A)
1. Edit `data/system_prompt.txt`
2. Replace lines 45-48 with stronger formatting rules (see above)
3. Add example of correct vs wrong formatting
4. Test locally with question: "What are Dakota's top skills?"

### Step 2: Test & Verify
```bash
# Start backend
cd backend && uvicorn main:app --reload --port 8000

# Open http://localhost:8000 and ask:
"What are Dakota's top skills?"
"Tell me about Dakota's product management experience"

# Check for:
- No gaps between bullets
- Tight, scannable formatting
```

### Step 3: If Still Not Working, Apply Option B
1. Edit `frontend/app.js` line 99
2. Update regex to capture and clean bullet blocks with blank lines
3. Test again

### Step 4: Commit & Deploy
```bash
git add data/system_prompt.txt
# OR if parser fix needed:
git add frontend/app.js

git commit -m "Fix excessive spacing between bullets in responses"
git push origin improve-response-formatting
```

## Acceptance Criteria

- [ ] Bullet lists have no visible gaps between items
- [ ] Multiple bullet lists in same response are properly separated
- [ ] Paragraph spacing after bullet lists is appropriate (not too close)
- [ ] Solution works consistently across different question types

## Testing Scenarios

**Test 1: Simple Skills List**
- Ask: "What are Dakota's top skills?"
- Expected: Tight bullet list with no gaps

**Test 2: Multiple Sections with Bullets**
- Ask: "Tell me about Dakota's product management experience"
- Expected: Multiple bullet lists, each tight internally, proper spacing between sections

**Test 3: Mixed Content**
- Ask: "What's Dakota's AI experience?"
- Expected: Paragraphs and bullets mixed, proper spacing between each type

## Root Cause Documentation

**Why This Happened:**
1. System prompt has the rule "Do NOT add blank lines between bullets"
2. But Claude doesn't always strictly follow formatting rules
3. When Claude violates this, the markdown parser's `\n\n+` split creates separate paragraph blocks
4. CSS can't fix this because bullets are in different `<ul>` containers

**Lesson Learned:**
- When formatting issues persist despite CSS changes, check the HTML structure
- If the parser creates wrong structure, CSS is powerless
- Either fix the source (LLM output) or fix the parser

## Files Modified

- `data/system_prompt.txt` - Strengthen bullet formatting rules
- OR `frontend/app.js` - Make parser handle bullets with blank lines (if Option B needed)

## References

- Markdown parser: `frontend/app.js:40-123`
- System prompt formatting section: `data/system_prompt.txt:34-48`
- CSS styling (not the issue): `frontend/styles.css:258-265`
