// Theme toggle for the how-it-works page. theme-init.js stamps data-theme
// before first paint; this wires the toggle, mirroring app.js applyTheme
// (kept tiny and standalone so this page never loads the chat bundle).
(function () {
  const THEME_COLORS = { light: "#FBFDFF", dark: "#16171C" };

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", THEME_COLORS[theme] || THEME_COLORS.light);
    document
      .getElementById("theme-toggle")
      ?.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
  }

  applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");

  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* storage unavailable: theme still applies for this page view */
    }
    applyTheme(next);
  });

  const mq = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
  mq?.addEventListener?.("change", (e) => {
    let stored = null;
    try {
      stored = localStorage.getItem("theme");
    } catch {
      /* ignore */
    }
    if (!stored) applyTheme(e.matches ? "dark" : "light");
  });
})();
