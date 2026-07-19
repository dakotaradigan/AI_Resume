// Applies the theme before first paint. This must stay an external file
// loaded in <head> before the stylesheet: the site's CSP (script-src 'self')
// blocks inline scripts, and running after paint would flash the wrong theme.
(function () {
  var stored = null;
  try {
    stored = localStorage.getItem("theme");
  } catch (e) {
    /* storage unavailable: fall through to system preference */
  }
  var dark = stored
    ? stored === "dark"
    : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
})();
