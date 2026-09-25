(() => {
  const portrait = document.getElementById("hero-portrait");
  const poses = portrait?.querySelector(".hero-portrait-poses");
  if (!portrait || !poses) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const CENTER = 1;
  const DEAD_ZONE_RATIO = 0.18;
  const HYSTERESIS_PX = 8;
  let row = CENTER;
  let column = CENTER;
  let pendingPoint = null;
  let animationFrame = null;

  function showPose(nextRow, nextColumn) {
    row = nextRow;
    column = nextColumn;
    poses.style.left = `${-column * 100}%`;
    poses.style.top = `${-row * 100}%`;
  }

  function resetPose() {
    if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    animationFrame = null;
    pendingPoint = null;
    showPose(CENTER, CENTER);
  }

  // A small buffer prevents flickering between poses near a boundary.
  function direction(offset, deadZone, previous) {
    if (previous === 0 && offset < -deadZone + HYSTERESIS_PX) return 0;
    if (previous === 2 && offset > deadZone - HYSTERESIS_PX) return 2;
    if (offset < -deadZone - HYSTERESIS_PX) return 0;
    if (offset > deadZone + HYSTERESIS_PX) return 2;
    return CENTER;
  }

  function updatePose() {
    animationFrame = null;
    if (!pendingPoint || reducedMotion.matches || document.hidden) return;
    const bounds = portrait.getBoundingClientRect();
    if (bounds.bottom <= 0 || bounds.top >= window.innerHeight) return;
    const deadZone = bounds.width * DEAD_ZONE_RATIO;
    const x = pendingPoint.x - (bounds.left + bounds.width / 2);
    const y = pendingPoint.y - (bounds.top + bounds.height / 2);
    showPose(direction(y, deadZone, row), direction(x, deadZone, column));
  }

  function trackPointer(event) {
    if (reducedMotion.matches) return;
    // Touch gestures elsewhere on the page must remain ordinary scrolling.
    if (event.pointerType === "touch" && !portrait.contains(event.target)) return;
    pendingPoint = { x: event.clientX, y: event.clientY };
    if (animationFrame === null) animationFrame = requestAnimationFrame(updatePose);
  }

  window.addEventListener("pointermove", trackPointer, { passive: true });
  portrait.addEventListener("pointerdown", (event) => {
    if (reducedMotion.matches || event.pointerType === "mouse") return;
    portrait.setPointerCapture(event.pointerId);
    trackPointer(event);
  });
  portrait.addEventListener("pointercancel", resetPose);
  portrait.addEventListener("lostpointercapture", resetPose);
  document.documentElement.addEventListener("pointerleave", resetPose);
  window.addEventListener("blur", resetPose);
  window.addEventListener("resize", resetPose);
  window.addEventListener("scroll", resetPose, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) resetPose();
  });
  reducedMotion.addEventListener("change", resetPose);

  portrait.addEventListener("keydown", (event) => {
    if (reducedMotion.matches) return;
    const movements = {
      ArrowUp: [-1, 0], ArrowDown: [1, 0],
      ArrowLeft: [0, -1], ArrowRight: [0, 1],
    };
    if (event.key === "Home") {
      event.preventDefault();
      resetPose();
    } else if (movements[event.key]) {
      event.preventDefault();
      if (animationFrame !== null) cancelAnimationFrame(animationFrame);
      animationFrame = null;
      pendingPoint = null;
      const [dy, dx] = movements[event.key];
      showPose(Math.max(0, Math.min(2, row + dy)), Math.max(0, Math.min(2, column + dx)));
    }
  });
})();
