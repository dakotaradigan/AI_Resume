// Animated metaball "bubble" backgrounds for the hero and footer sections.
//
// Vanilla adaptation of a Paper (paper.design) export that used
// <Metaballs /> from @paper-design/shaders-react. Since this site has no
// React or build step, the same shader is driven directly through the
// vendored vanilla runtime in ./vendor/paper-shaders-metaballs.js
// (@paper-design/shaders, Apache-2.0).
//
// Progressive enhancement: if WebGL2 is unavailable or anything throws,
// the containers are removed and the CSS section gradients stand alone.

import {
  ShaderMount,
  metaballsFragmentShader,
  getShaderColorFromString,
  getShaderNoiseTexture,
  ShaderFitOptions,
} from "./vendor/paper-shaders-metaballs.js";

// Ordering matters: repeated entries weight how often a color is assigned
// to a ball. Light palette comes straight from the Paper export (site
// accent colors); dark palette maps the same roles onto the dark theme.
const THEME_PALETTES = {
  light: ["#ffffff", "#e7f2fb", "#e7f2fb", "#4a97d2", "#2f7cb3"],
  dark: ["#1d2733", "#24384a", "#24384a", "#2f7cb3", "#6fb3e6"],
};

const BALL_COUNT = 14;
const BALL_SIZE = 0.78;
// Frame shown to prefers-reduced-motion users: an arbitrary mid-animation
// timestamp so they get a composed arrangement instead of the t=0 state.
const STATIC_FRAME = 61750;

const HOSTS = [
  { selector: ".hero", className: "hero-bubbles" },
  { selector: ".site-footer", className: "footer-bubbles" },
];

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function colorUniforms(theme) {
  const palette = THEME_PALETTES[theme] || THEME_PALETTES.light;
  return {
    u_colors: palette.map(getShaderColorFromString),
    u_colorsCount: palette.length,
  };
}

function mountInto(section, className, noiseTexture, animate) {
  const host = document.createElement("div");
  host.className = className;
  host.setAttribute("aria-hidden", "true");
  section.prepend(host);

  const uniforms = {
    ...colorUniforms(currentTheme()),
    u_colorBack: getShaderColorFromString("#00000000"),
    u_count: BALL_COUNT,
    u_size: BALL_SIZE,
    u_noiseTexture: noiseTexture,
    u_fit: ShaderFitOptions.contain,
    u_scale: 1,
    u_rotation: 0,
    u_offsetX: 0,
    u_offsetY: 0,
    u_originX: 0.5,
    u_originY: 0.5,
    u_worldWidth: 0,
    u_worldHeight: 0,
  };

  try {
    return new ShaderMount(
      host,
      metaballsFragmentShader,
      uniforms,
      undefined,
      animate ? 1 : 0,
      animate ? 0 : STATIC_FRAME,
    );
  } catch {
    host.remove();
    return null;
  }
}

async function init() {
  if (typeof WebGL2RenderingContext === "undefined") return;

  const noiseTexture = getShaderNoiseTexture();
  if (!noiseTexture) return;
  try {
    // ShaderMount requires texture images to be fully loaded up front.
    await noiseTexture.decode();
  } catch {
    return;
  }

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const mounts = HOSTS.flatMap(({ selector, className }) => {
    const section = document.querySelector(selector);
    if (!section) return [];
    const mount = mountInto(section, className, noiseTexture, !reducedMotion.matches);
    return mount ? [mount] : [];
  });
  if (!mounts.length) return;

  // Follow the site theme toggle (app.js stamps data-theme on <html>).
  new MutationObserver(() => {
    const colors = colorUniforms(currentTheme());
    mounts.forEach((mount) => mount.setUniforms(colors));
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });

  reducedMotion.addEventListener("change", () => {
    mounts.forEach((mount) => {
      if (reducedMotion.matches) {
        mount.setFrame(STATIC_FRAME);
        mount.setSpeed(0);
      } else {
        mount.setSpeed(1);
      }
    });
  });
}

init();
