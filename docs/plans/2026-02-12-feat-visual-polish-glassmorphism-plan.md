---
title: "feat: Visual Polish — Glassmorphism, Gradients & Scroll Animations"
type: feat
date: 2026-02-12
---

# Visual Polish — Glassmorphism, Gradients & Scroll Animations

## Overview

Layer three visual effects onto the existing site to make it feel premium and modern: gradient backgrounds for depth, glassmorphism cards, and richer scroll animations. Pure CSS + existing JS — zero new dependencies, same HTML structure, same color palette.

## Problem Statement

The current site is clean and professional but visually flat. White cards on cream background with simple fade-up reveals. It reads like a well-formatted document rather than a polished product. Modern portfolio sites (Every.io, Linear, Stripe) use layered depth, gradient washes, and choreographed motion to create a premium feel. The gap isn't the design system — it's the lack of visual richness.

---

## Key Architectural Decisions

### 1. Gradients first, then glass

Glassmorphism requires something visible *behind* the frosted surface. On a flat cream background, semi-transparent cards would look identical to opaque ones. So: add soft gradient orbs/blobs to section backgrounds first, then make cards semi-transparent. The gradients become the "show" that glass reveals.

### 2. Warm gradients, not cool

The existing palette is warm (gold `hsl(38, 80%, 55%)`, sage, cream). Gradient orbs should use warm tones — soft golds, muted ambers, desaturated sage greens. No blue/purple (that would clash with the editorial warmth). The site should feel like warm light filtering through frosted glass, not a tech startup dashboard.

### 3. CSS `::before`/`::after` pseudo-elements for gradient orbs

Gradient decorations go on pseudo-elements of section wrappers, not new HTML elements. This keeps the DOM unchanged and makes effects easy to toggle off via a single CSS rule.

### 4. Subtle glass, not obvious

Card opacity should be high (85-92%) — the gradient bleed-through should be a whisper, not a shout. `backdrop-filter: blur(12px)` with a thin `rgba` border. The effect should make someone think "this looks expensive" without being able to pinpoint why.

### 5. Enhance existing reveal choreography, don't replace it

The IntersectionObserver system (`app.js:396-424`) is well-built. Don't rewrite it. Add new CSS animation variants (`.reveal--scale`, `.reveal--slide-left`) and apply them to different element types. Timeline entries slide from left, skills chips cascade, section headers scale up. More variety in the choreography, same underlying trigger.

---

## Phase 1: Gradient Backgrounds

Add soft gradient orbs behind key sections using pseudo-elements on existing containers.

### `frontend/styles.css` — New gradient decoration system

```css
/* Gradient orb decorations — warm palette */
.hero::before {
  content: "";
  position: absolute;
  top: -20%;
  right: -15%;
  width: 500px;
  height: 500px;
  border-radius: 50%;
  background: radial-gradient(circle, hsla(38, 80%, 55%, 0.12) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

.resume-section {
  position: relative;  /* Already has padding, just needs positioning context */
}

.resume-section::before {
  content: "";
  position: absolute;
  width: 400px;
  height: 400px;
  border-radius: 50%;
  background: radial-gradient(circle, hsla(38, 60%, 60%, 0.08) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

/* Alternate orb positions per section */
#experience::before { top: 10%; left: -10%; }
#education::before { top: 20%; right: -10%; left: auto; }
#skills::before { bottom: 0; left: 50%; transform: translateX(-50%); top: auto; }
```

**Key details:**
- All orbs use the existing gold hue with very low opacity (0.08–0.12) — visible but not distracting
- `pointer-events: none` prevents orbs from intercepting clicks
- `z-index: 0` keeps orbs behind card content
- Hero already has `position: relative; overflow: hidden` — orb clipped to hero bounds

### Files to modify

| File | Change |
|------|--------|
| `frontend/styles.css` | Add gradient orb pseudo-elements to `.hero`, `.resume-section` |

No HTML or JS changes.

---

## Phase 2: Glassmorphism Cards

Make cards semi-transparent with backdrop blur so gradient orbs show through.

### `frontend/styles.css` — Glass treatment for cards

```css
/* Glass card base — shared across card types */
.timeline-entry {
  background: hsla(0, 0%, 100%, 0.88);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid hsla(220, 20%, 14%, 0.08);
  /* Keep existing border-left: 3px solid var(--gold) */
}

.skills-block {
  background: hsla(0, 0%, 100%, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid hsla(220, 20%, 14%, 0.08);
}

.resume-card {
  background: hsla(0, 0%, 100%, 0.88);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid hsla(220, 20%, 14%, 0.08);
}

/* Chat card — subtler glass (it's the primary interaction surface) */
.chat-card {
  background: hsla(0, 0%, 100%, 0.92);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}
```

**Key details:**
- Opacity range 0.85–0.92 (subtle — "expensive" feel without being gimmicky)
- Chat card gets highest opacity (0.92) since it's the primary interaction surface — readability is critical
- `-webkit-backdrop-filter` prefix required for Safari compatibility
- Thin `hsla` border replaces opaque `var(--border)` for softer edge
- Existing `box-shadow` values stay — they complement the glass effect

### Performance consideration

`backdrop-filter` triggers GPU compositing. On modern devices this is fine. For safety:

```css
@media (prefers-reduced-motion: reduce) {
  .timeline-entry,
  .skills-block,
  .resume-card,
  .chat-card {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    background: var(--card);  /* Fall back to opaque white */
  }
}
```

This also handles low-power devices that set `prefers-reduced-motion`.

### Files to modify

| File | Change |
|------|--------|
| `frontend/styles.css` | Update backgrounds on `.timeline-entry`, `.skills-block`, `.resume-card`, `.chat-card`. Add reduced-motion fallback. |

No HTML or JS changes.

---

## Phase 3: Enhanced Scroll Animations

Add animation variants and richer stagger choreography. Modify CSS only + minimal JS to apply new classes.

### `frontend/styles.css` — New animation variants

```css
/* Scale-in variant (for section headers) */
.reveal--scale {
  opacity: 0;
  transform: scale(0.95);
  transition: opacity 600ms ease, transform 600ms ease;
}

.reveal--scale.is-visible {
  opacity: 1;
  transform: scale(1);
}

/* Slide-from-left variant (for timeline entries) */
.reveal--slide-left {
  opacity: 0;
  transform: translateX(-24px);
  transition: opacity 500ms ease, transform 500ms ease;
}

.reveal--slide-left.is-visible {
  opacity: 1;
  transform: translateX(0);
}

/* Extend stagger range for larger lists */
.reveal-delay-5 { transition-delay: 500ms; }
.reveal-delay-6 { transition-delay: 600ms; }
```

### `frontend/app.js` — Apply variants when building elements

```javascript
// Experience timeline entries: slide from left instead of fade up
const entry = el("article", {
  class: `timeline-entry reveal reveal--slide-left${delayClass}`
}, [...]);

// Section headers: scale-in
// (applied in HTML or dynamically if headers are rendered via JS)
```

**Key details:**
- New variants (`reveal--scale`, `reveal--slide-left`) compose with the existing `.reveal` base class — they override the default `translateY` transform
- Same `is-visible` trigger class — no IntersectionObserver changes needed
- Delay classes extended to 6 levels for longer lists
- `prefers-reduced-motion` already handled by the existing media query (covers all `.reveal` elements)

### Files to modify

| File | Change |
|------|--------|
| `frontend/styles.css` | Add `.reveal--scale`, `.reveal--slide-left` variants. Add delay-5 and delay-6. |
| `frontend/app.js` | Update `class` strings in `el()` calls for timeline entries (~2 lines changed). |

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| **`prefers-reduced-motion: reduce`** | All glass effects fall back to opaque. All animations disabled. Already handled by existing media queries. |
| **Older browsers (no `backdrop-filter`)** | Cards render with the semi-transparent `hsla()` background but no blur — slightly transparent but still readable. Graceful degradation. |
| **Mobile performance** | `backdrop-filter` uses GPU compositing. If performance issues arise, disable blur on mobile via `@media (max-width: 960px)`. Test first — modern phones handle this fine. |
| **Dark mode** | Not in scope. If added later, glass opacity and gradient colors would need dark-mode variants. |
| **Print styles** | Not affected — gradient pseudo-elements and blur don't render in print. |

## Acceptance Criteria

- [ ] Soft gradient orbs visible behind hero, experience, education, and skills sections
- [ ] Cards (timeline, skills, education, certifications) have frosted glass appearance
- [ ] Chat card has subtle glass effect without compromising readability
- [ ] Timeline entries animate in with slide-from-left (not just fade-up)
- [ ] Section headers animate with subtle scale-in
- [ ] Skills chips cascade with staggered timing
- [ ] All effects respect `prefers-reduced-motion: reduce`
- [ ] No visual regression on mobile (test at 375px viewport)
- [ ] No new JS dependencies added
- [ ] No HTML structure changes
- [ ] Page still loads under 2 seconds

## Implementation Sequence

Three commits to reduce risk and make review easy:

1. **Commit 1 (gradients):** Add gradient orb pseudo-elements to sections. Visual-only, no behavior change.
2. **Commit 2 (glass):** Update card backgrounds to semi-transparent + backdrop-filter. Add reduced-motion fallback.
3. **Commit 3 (animations):** Add new reveal variants and apply them to element classes.

Each commit is independently shippable — if glass looks bad, revert commit 2 without losing gradients.

## Files to Modify

| File | Change |
|------|--------|
| `frontend/styles.css` | Gradient orbs, glass card backgrounds, new animation variants |
| `frontend/app.js` | Apply `reveal--slide-left` class to timeline entries (~2 lines) |

No changes to: `frontend/index.html`, `backend/main.py`, `backend/config.py`, `data/resume.json`.

## Dependencies & Risks

- **Risk:** Glass cards may look too subtle at 88% opacity — might need tuning down to 75-80% after visual review. Mitigated by keeping changes in CSS variables for easy adjustment.
- **Risk:** `backdrop-filter` performance on older mobile devices. Mitigated by reduced-motion fallback + testing on real devices before shipping.
- **Risk:** Gradient orbs may look random/arbitrary if not positioned thoughtfully. Mitigated by starting with very low opacity (0.08) and adjusting upward.
- **Dependency:** None — pure CSS enhancement, no backend changes, no new packages.

## References

- Brainstorm: `docs/brainstorms/2026-02-12-visual-polish-glassmorphism-brainstorm.md`
- Existing reveal system: `frontend/app.js:396-424`
- Existing CSS animations: `frontend/styles.css:1078-1106` (reveal), `frontend/styles.css:322-389` (hero)
- Element class application: `frontend/app.js:330-392`
- CLAUDE.md simplicity principle: "If a fix requires more than ~50 lines of new code, reconsider the approach"
