---
title: "feat: Warm elegant UI redesign"
type: feat
date: 2026-03-21
---

# feat: Warm Elegant UI Redesign

## Overview

Shift the Resume Assistant from cool blue sky glassmorphism to a warm ivory/amber aesthetic that feels like a premium product page. Warm ivory background, amber accents, warm-tinted glassmorphism cards, no dark mode. Typography unchanged (Playfair + DM Sans).

## Proposed Solution

**CSS-only change.** Update `:root` variables, body background, glassmorphism tints, hero gradient, and remove blue sky/cloud animation. No layout, typography, or JavaScript changes needed.

## Implementation

### Phase 1: Root Variables

**File: `frontend/styles.css` lines 1-45**

Replace all `:root` color variables:

```css
:root {
  /* Warm palette */
  --bg:               hsl(35, 40%, 96%);          /* warm ivory */
  --card:             hsl(35, 30%, 99%);           /* warm white */
  --text:             hsl(25, 25%, 18%);           /* espresso */
  --muted:            hsl(25, 12%, 50%);           /* warm gray */
  --primary:          hsl(25, 20%, 22%);           /* dark warm */
  --secondary:        hsl(35, 25%, 93%);           /* light warm */
  --gold:             hsl(30, 72%, 52%);           /* amber */
  --gold-dark:        hsl(28, 74%, 42%);           /* dark amber */
  --accent-warm:      hsl(25, 85%, 58%);           /* copper */
  --accent-warm-soft: hsla(25, 85%, 58%, 0.24);

  /* Hero */
  --hero-text:        hsl(0, 0%, 99%);
  --hero-muted:       hsla(0, 0%, 100%, 0.9);
  --hero-gold:        hsl(0, 0%, 100%);

  /* Borders — warm brown tint */
  --border:           hsla(30, 30%, 30%, 0.12);
  --border-strong:    hsla(30, 30%, 30%, 0.22);
  --ring:             hsla(30, 72%, 52%, 0.34);
  --surface-hover:    hsla(25, 20%, 14%, 0.035);

  /* Shadows — warm tint */
  --shadow-sm:        0 1px 3px hsla(25, 20%, 14%, 0.06);
  --shadow-md:        0 8px 30px hsla(25, 20%, 14%, 0.08);
  --shadow-lg:        0 16px 48px hsla(25, 20%, 14%, 0.12);

  /* Footer */
  --footer-bg:          linear-gradient(145deg, hsla(35, 30%, 99%, 0.28), hsla(35, 30%, 99%, 0.10));
  --footer-text:        hsl(25, 25%, 18%);
  --footer-heading:     hsl(25, 28%, 14%);
  --footer-subtitle:    hsl(25, 20%, 28%);
  --footer-btn-border:  hsla(25, 25%, 18%, 0.22);
  --footer-btn-bg:      rgba(255, 255, 255, 0.28);
  --footer-btn-text:    hsl(25, 24%, 16%);
  --footer-separator:   hsla(25, 24%, 20%, 0.22);
  --footer-copyright:   hsl(25, 16%, 34%);

  /* Typography unchanged */
  --font-display:     "Playfair Display", Georgia, serif;
  --font-body:        "DM Sans", system-ui, -apple-system, sans-serif;
}
```

### Phase 2: Body Background

**File: `frontend/styles.css` lines 55-121**

Replace the blue sky gradient and cloud drift animation with a clean warm background:

```css
/* Replace body background (line 55-62) */
body {
  background: var(--bg);
  /* Optional: very subtle warm gradient for depth */
  /* background: linear-gradient(180deg, hsl(35, 35%, 95%) 0%, hsl(35, 40%, 96%) 100%); */
}
```

**Remove entirely:**
- `body::before` cloud layer (lines 77-100) — delete the entire block
- `@keyframes cloudDrift` (lines 101-107) — delete
- `body::after` warm glow overlay (lines 108-121) — delete

### Phase 3: Glassmorphism Warm Tint

Replace all `hsla(206/207, 90-92%, 96%, 0.xx)` blue tints with warm cream tints. Every glassmorphism element follows the same pattern — swap the blue hue for warm:

| Element | Line | Old Blue Tint | New Warm Tint |
|---------|------|--------------|---------------|
| `.site-header.is-scrolled` | ~154 | `hsla(210, 52%, 98%, 0.34)` | `hsla(35, 40%, 98%, 0.34)` |
| `.chat-card` | ~476 | `hsla(206, 90%, 96%, 0.46)` | `hsla(35, 40%, 96%, 0.46)` |
| `.msg.bot` | ~613 | `hsla(207, 92%, 96%, 0.30)` | `hsla(35, 40%, 96%, 0.30)` |
| `.msg.bot.is-thinking` | ~620 | `hsla(207, 92%, 96%, 0.28)` | `hsla(35, 40%, 96%, 0.28)` |
| `.timeline-entry` | ~988 | `hsla(207, 92%, 96%, 0.58)` | `hsla(35, 40%, 96%, 0.58)` |
| `.skills-block` | ~1172 | `hsla(207, 92%, 96%, 0.44)` | `hsla(35, 40%, 96%, 0.44)` |
| `.resume-card` | ~1244 | `hsla(207, 92%, 96%, 0.58)` | `hsla(35, 40%, 96%, 0.58)` |
| Mobile `.nav-links.is-open` | ~1660 | `hsla(210, 52%, 98%, 0.38)` | `hsla(35, 40%, 98%, 0.38)` |
| Header scroll border | ~158 | `hsla(210, 60%, 98%, 0.55)` | `hsla(35, 40%, 98%, 0.55)` |
| Thinking pulse border | ~627 | `hsla(200, 72%, 52%, 0.14)` | `hsla(30, 72%, 52%, 0.14)` |

**Search pattern:** Find all `hsla(20[0-9]` and `hsla(21[0-9]` in the CSS and replace hue with warm equivalents (30-35).

### Phase 4: Hero Section

**File: `frontend/styles.css`** — hero gradient

Shift the hero background from cool dark blue to warm dark espresso:

```css
.site-hero {
  background: linear-gradient(
    180deg,
    hsl(25, 30%, 16%) 0%,    /* deep espresso */
    hsl(28, 35%, 22%) 60%,   /* warm dark brown */
    hsl(30, 40%, 28%) 100%   /* medium warm brown */
  );
}
```

### Phase 5: Theme Meta Tag

**File: `frontend/index.html` line 6**

```html
<!-- Old -->
<meta name="theme-color" content="#1f8dd7" />
<!-- New — warm amber -->
<meta name="theme-color" content="#D4883C" />
```

### Phase 6: Status Steps

The new streaming status steps use `--gold-dark` and `--muted` which will automatically pick up the warm values from the root variable changes. No additional changes needed.

## Acceptance Criteria

- [ ] Background is warm ivory — no blue sky, no cloud animation
- [ ] All glassmorphism cards have warm cream tint (no blue)
- [ ] Accent color is amber throughout (focus rings, thinking dots, checkmarks)
- [ ] Hero section uses warm dark gradient
- [ ] Shadows have warm brown tint (not blue-gray)
- [ ] Borders have warm tint
- [ ] Footer variables are warm
- [ ] Theme meta tag updated to amber
- [ ] No dark mode toggle or code remains
- [ ] `prefers-reduced-motion` still works
- [ ] Mobile responsive layout unchanged
- [ ] Status steps inherit warm colors correctly

## Scope Estimate

| Component | Changes |
|-----------|---------|
| `frontend/styles.css` | ~40 lines modified, ~45 lines deleted (cloud animation) |
| `frontend/index.html` | 1 line (theme-color meta) |
| `frontend/app.js` | 0 changes |
| `backend/` | 0 changes |

## References

- Brainstorm: `docs/brainstorms/2026-03-21-warm-elegant-redesign-brainstorm.md`
- Root variables: `frontend/styles.css:1-45`
- Body background + clouds: `frontend/styles.css:55-121`
- Glassmorphism patterns: 13 elements mapped in research
- Hero gradient: `frontend/styles.css` (hero section)
- Previous redesign: PR #46 (glassmorphism redesign, Feb 2026)
