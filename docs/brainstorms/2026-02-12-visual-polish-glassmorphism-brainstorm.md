---
title: Visual Polish — Glassmorphism, Gradients & Scroll Animations
date: 2026-02-12
type: enhancement
---

# Visual Polish — Glassmorphism, Gradients & Scroll Animations

## What We're Building

Elevate the existing resume site's visual quality by layering three effects on top of the current warm editorial design:

1. **Glassmorphism cards** — Semi-transparent cards with `backdrop-filter: blur()`, subtle borders, and layered depth
2. **Rich gradient backgrounds** — Radial/linear gradients behind key sections (hero, footer, section dividers) for visual richness
3. **Enhanced scroll animations** — Upgrade existing `.reveal` IntersectionObserver system with more sophisticated choreography (staggered fades, scale-ins, parallax-feel offsets)

## Why This Approach

**Evolution, not revolution.** The current palette (Playfair Display + DM Sans, warm gold/sage, cream `hsl(40, 33%, 97%)` background) is already cohesive and professional. The problem isn't the design system — it's that the site lacks the visual depth, layering, and motion that makes modern sites feel premium.

Every.io achieves its sleek look through three CSS techniques that can all be adopted without changing the existing color system or HTML structure.

## Key Decisions

1. **Keep current palette and fonts** — No color system overhaul. Gold/sage/cream stays. Glass and gradients layer ON TOP of the existing variables.

2. **Zero new dependencies** — No GSAP, no Swiper, no animation libraries. The site already has an IntersectionObserver-based `.reveal` system in `app.js`. Enhance it with better keyframes and staggered timing, not a new library.

3. **CSS-first approach** — Glass (`backdrop-filter`), gradients (`radial-gradient`, `linear-gradient`), and most animations are pure CSS. The only JS is the existing reveal trigger logic.

4. **Same HTML structure** — No new sections, no layout changes. This is a CSS + animation enhancement pass, not a structural redesign.

## Specific Effects to Explore

### Glass Cards
- Timeline entries, skills blocks, education/cert cards → semi-transparent backgrounds with `backdrop-filter: blur(12px)`
- Chat card → subtle glass border treatment
- Navbar (already has this on scroll — extend to other surfaces)

### Gradient Backgrounds
- Hero section → soft radial gradient behind the name/tagline
- Section dividers → gradient mesh or soft color wash between Experience/Education/Skills
- Footer → richer gradient treatment (currently solid dark, could add depth)

### Scroll Animations
- Upgrade existing `.reveal` → staggered delays per card (not just per section)
- Timeline entries → slide in from left with slight rotation
- Skills chips → cascade in with 30ms stagger
- Section headers → subtle scale-up on entry
- Hero elements → already have staggered `heroFadeUp` — could add subtle parallax-feel offset

## What We're NOT Doing

- No dark mode redesign (light mode stays primary)
- No new fonts or color palette
- No carousel/marquee components
- No GSAP or animation library dependencies
- No structural HTML changes
- No new pages or sections

## Open Questions

1. **Glass intensity** — How transparent should cards be? Subtle (95% opacity, barely noticeable) vs. obvious (70% opacity, clearly glass)? Probably start subtle.
2. **Gradient palette** — Should gradients use the existing gold/sage colors, or introduce a new accent (e.g., a soft blue or purple for depth)?
3. **Performance** — `backdrop-filter` can be expensive on mobile. Need to test and potentially disable on low-power devices via `prefers-reduced-motion` or a viewport check.

## Success Criteria

- A recruiter visiting the site thinks "this looks premium and modern"
- The chatbot section feels like a polished product, not a homework assignment
- Scroll experience feels smooth and intentional
- No performance regression on mobile
- Zero new JS dependencies added

## Inspiration Reference

- Every.io — glassmorphism, gradient backgrounds, scroll-triggered animations
- Linear.app — clean glass UI with subtle depth
- Stripe.com — gradient backgrounds with editorial typography

## Next Steps

Run `/workflows:plan` to break this into implementable phases (likely: 1. Glass cards, 2. Gradients, 3. Scroll animation upgrades).
