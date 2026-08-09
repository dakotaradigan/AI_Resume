// Vanilla adapter for the thinking-orbs engine (vendor/thinking-orbs.js,
// MIT — Jakub Antalik). The upstream package ships a React component; this
// site has no React, so this file reimplements that wrapper's behavior in
// plain JS: a per-orb rAF loop on a shared clock, paused when offscreen or
// on hidden tabs, a static frame under prefers-reduced-motion, and live
// light/dark ink following the site's data-theme attribute.
//
// API: createThinkingOrb(state, size) -> canvas element (or null when the
// engine is unavailable). Removal from the DOM stops its loop.

(function () {
  "use strict";

  const LABELS = {
    working: "Working…",
    searching: "Searching…",
    solving: "Solving…",
    listening: "Listening…",
    connecting: "Connecting…",
    weaving: "Weaving…",
    composing: "Composing…",
    breathing: "Thinking…",
    shaping: "Shaping…",
  };

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  function isDark() {
    return document.documentElement.dataset.theme === "dark";
  }

  // `size` is the rendered CSS size. Options:
  // - `tuning`: which hand-tuned density preset (64 or 20) drives the
  //   drawing. The 20 tuning is an inline-text spinner — at avatar sizes
  //   it reads as a few stray dots, so 32px+ defaults to the 64 tuning.
  // - `still`: render a single static frame (a mark, not an animation) —
  //   used by the chat header so only working states ever move.
  function createThinkingOrb(state, size, { tuning, still = false } = {}) {
    if (typeof ThinkingOrbs === "undefined") return null;
    const { MODE_DRAWS, resolvePreset } = ThinkingOrbs;
    const tuned = tuning === 64 || tuning === 20 ? tuning : size >= 32 ? 64 : 20;

    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", LABELS[state] || "Thinking…");
    canvas.style.width = size + "px";
    canvas.style.height = size + "px";
    canvas.style.display = "block";

    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    const { mode, speed, opts } = resolvePreset(state, tuned);
    const draw = MODE_DRAWS[mode];

    const frame = (tSec) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);
      draw(ctx, size, tSec, isDark(), opts);
    };

    // Still marks and reduced motion: one static, deterministic frame —
    // but keep it in sync with theme flips.
    if (still || reducedMotion.matches) {
      frame(0.6);
      const themeObserver = new MutationObserver(() => {
        if (canvas.isConnected) frame(0.6);
        else themeObserver.disconnect();
      });
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
      return canvas;
    }

    let raf = 0;
    let running = false;
    const loop = () => {
      // Self-cleanup: the collapse() path just removes the element.
      if (!canvas.isConnected && started) {
        stop();
        io?.disconnect();
        document.removeEventListener("visibilitychange", onVis);
        return;
      }
      frame((performance.now() / 1000) * speed);
      if (running) raf = requestAnimationFrame(loop);
    };
    const start = () => {
      if (running) return;
      running = true;
      raf = requestAnimationFrame(loop);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };

    // First frame immediately, even before visibility is known.
    frame((performance.now() / 1000) * speed);
    let started = false;

    // Pause offscreen and on hidden tabs — free when not visible.
    let visible = true;
    const io =
      typeof IntersectionObserver !== "undefined"
        ? new IntersectionObserver(([entry]) => {
            visible = entry.isIntersecting;
            started = true;
            if (visible && document.visibilityState !== "hidden") start();
            else stop();
          })
        : null;
    io?.observe(canvas);
    const onVis = () => {
      if (document.visibilityState === "hidden") stop();
      else if (visible) start();
    };
    document.addEventListener("visibilitychange", onVis);
    if (!io) {
      started = true;
      start();
    }

    return canvas;
  }

  window.createThinkingOrb = createThinkingOrb;
})();
