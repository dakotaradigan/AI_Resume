const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendButton = chatForm.querySelector("button");

const experienceGrid = document.getElementById("experience-grid");
const skillsGrid = document.getElementById("skills-grid");
const educationGrid = document.getElementById("education-grid");
const certificationsGrid = document.getElementById("certifications-grid");

const brandTitle = document.getElementById("brand-title");
const heroName = document.getElementById("hero-name");
const heroTitle = document.getElementById("hero-title");
const heroTagline = document.getElementById("hero-tagline");
const heroEmail = document.getElementById("hero-email");
const heroLocation = document.getElementById("hero-location");
const heroLinkedIn = document.getElementById("hero-linkedin");
const themeToggle = document.getElementById("theme-toggle");
const contactToggle = document.getElementById("contact-toggle");
const contactMenu = document.getElementById("contact-menu");
const contactLinkedIn = document.getElementById("contact-linkedin");
const contactEmail = document.getElementById("contact-email");
const scrollHint = document.getElementById("scroll-hint");

const sessionId =
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * Simple markdown parser for bot responses.
 * Handles: **bold**, *italic*, ## headings, - lists
 */
function parseMarkdown(text) {
  // Escape HTML to prevent XSS
  const escapeHtml = (str) =>
    str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");

  let html = escapeHtml(text);

  // Convert **bold** to <strong>
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Convert *italic* (but not ** which is bold)
  html = html.replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, "<em>$1</em>");

  // Convert headings (must be done before list processing)
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  // Convert - list items to <li>
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");

  // Wrap consecutive <li> in <ul>
  html = html.replace(/(<li>.*?<\/li>\n?)+/gs, (match) => `<ul>${match}</ul>`);

  // Split into paragraphs by double newlines
  const paragraphs = html.split(/\n\n+/);

  html = paragraphs
    .map((para) => {
      para = para.trim();
      // Don't wrap headings or lists in <p>
      if (
        para.startsWith("<h") ||
        para.startsWith("<ul>") ||
        para.startsWith("<ol>")
      ) {
        return para;
      }
      // Convert single line breaks to <br> within paragraphs
      para = para.replace(/\n/g, "<br>");
      return para ? `<p>${para}</p>` : "";
    })
    .filter((p) => p)
    .join("");

  return html;
}

function addMessage(text, role, timestamp = new Date()) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;

  const body = document.createElement("div");
  body.className = "msg-body";

  // Bot messages: parse markdown for formatting
  // User messages: plain text for security
  if (role === "bot") {
    body.innerHTML = parseMarkdown(text);
  } else {
    body.textContent = text;
  }

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = formatTime(timestamp);

  div.append(body, meta);
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (v === null || v === undefined) return;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("data-")) node.setAttribute(k, v);
    else node.setAttribute(k, v);
  });
  (Array.isArray(children) ? children : [children]).forEach((child) => {
    if (child === null || child === undefined) return;
    node.append(child);
  });
  return node;
}

function safeArray(v) {
  return Array.isArray(v) ? v : [];
}

function renderExperience(items) {
  if (!experienceGrid) return;
  experienceGrid.innerHTML = "";

  safeArray(items).forEach((exp) => {
    const titleRow = el("div", { class: "resume-card-title-row" }, [
      el("div", { class: "resume-card-kicker", text: exp.duration || "" }),
      el("div", { class: "resume-card-meta", text: exp.location || "" }),
    ]);

    const role = el("div", { class: "resume-card-title", text: exp.role || "" });
    const company = el("div", { class: "resume-card-subtitle", text: exp.company || "" });

    const bullets = safeArray(exp.achievements)
      .slice(0, 6)
      .map((a) => el("li", { text: a }));
    const list = bullets.length ? el("ul", { class: "resume-bullets" }, bullets) : null;

    const card = el("article", { class: "resume-card" }, [titleRow, role, company, list]);
    experienceGrid.append(card);
  });
}

function renderSkills(skills) {
  if (!skillsGrid) return;
  skillsGrid.innerHTML = "";

  const entries = Object.entries(skills || {});
  entries.forEach(([key, items]) => {
    const label = key.replace(/_/g, " ").toUpperCase();
    const chips = safeArray(items).map((s) => el("button", { class: "chip chip--static", type: "button", text: s }));
    const block = el("section", { class: "skills-block" }, [
      el("div", { class: "skills-kicker", text: label }),
      el("div", { class: "skills-chips" }, chips),
    ]);
    skillsGrid.append(block);
  });
}

function renderEducation(items) {
  if (!educationGrid) return;
  educationGrid.innerHTML = "";
  safeArray(items).forEach((ed) => {
    const row = el("div", { class: "resume-card-title-row" }, [
      el("div", { class: "resume-card-title", text: ed.school || "" }),
      el("div", { class: "resume-card-meta", text: ed.graduation || "" }),
    ]);
    const subtitle = el("div", { class: "resume-card-subtitle", text: ed.degree || "" });
    educationGrid.append(el("article", { class: "resume-card" }, [row, subtitle]));
  });
}

function renderCertifications(items) {
  if (!certificationsGrid) return;
  certificationsGrid.innerHTML = "";
  safeArray(items).forEach((c) => {
    const row = el("div", { class: "resume-card-title-row" }, [
      el("div", { class: "resume-card-title", text: c.name || "" }),
      el("div", { class: "resume-card-meta", text: c.date || "" }),
    ]);
    const subtitle = el("div", { class: "resume-card-subtitle", text: c.issuer || "" });
    certificationsGrid.append(el("article", { class: "resume-card" }, [row, subtitle]));
  });
}

async function loadAndRenderResume() {
  // The backend serves the frontend; this endpoint is same-origin.
  // If someone opens index.html directly without the backend, fail gracefully.
  try {
    const res = await fetch("/api/resume");
    if (!res.ok) throw new Error(`Resume fetch failed: ${res.status}`);
    const data = await res.json();

    const personal = data.personal || {};
    const name = (personal.name || "").trim();
    const creds = (personal.credentials || "").trim();
    const displayName = [name, creds].filter(Boolean).join(", ");
    const title = (personal.title || "").trim();
    const email = (personal.email || "").trim();
    const linkedin = (personal.linkedin || "").trim();

    if (brandTitle && displayName) brandTitle.textContent = displayName.toUpperCase();
    if (heroName && displayName) heroName.textContent = displayName;
    if (heroTitle && title) heroTitle.textContent = title;
    if (heroTagline && personal.summary) {
      // Keep this short + “hero-like”
      heroTagline.textContent =
        personal.summary.length > 110
          ? `${personal.summary.slice(0, 110).trim()}…`
          : personal.summary;
    }
    if (heroEmail && email) heroEmail.href = `mailto:${email}`;
    if (heroEmail && email) heroEmail.textContent = email;
    if (heroLocation && personal.location) heroLocation.textContent = personal.location;
    if (heroLinkedIn && linkedin) heroLinkedIn.href = linkedin;

    // Header contact dropdown
    if (contactLinkedIn && linkedin) contactLinkedIn.href = linkedin;
    if (contactEmail && email) contactEmail.href = `mailto:${email}`;

    renderExperience(data.experience);
    renderSkills(data.skills);
    renderEducation(data.education);
    renderCertifications(data.certifications);
  } catch (err) {
    console.warn("Resume sections unavailable (did you start the backend?)", err);
    const resumeRoot = document.getElementById("resume");
    if (resumeRoot) resumeRoot.style.display = "none";
  }
}

function setSending(isSending) {
  chatInput.disabled = isSending;
  if (sendButton) {
    sendButton.disabled = isSending;
  }
}

function getSystemTheme() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function getStoredTheme() {
  try {
    const v = localStorage.getItem("theme");
    return v === "dark" || v === "light" ? v : null;
  } catch {
    return null;
  }
}

function setStoredTheme(theme) {
  try {
    localStorage.setItem("theme", theme);
  } catch {
    // ignore
  }
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  if (themeToggle) {
    themeToggle.setAttribute(
      "aria-label",
      theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
    );
    themeToggle.setAttribute(
      "title",
      theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
    );
  }
}

function initTheme() {
  const stored = getStoredTheme();
  applyTheme(stored || getSystemTheme());

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || getSystemTheme();
      const next = current === "dark" ? "light" : "dark";
      setStoredTheme(next);
      applyTheme(next);
    });
  }
}

function setContactMenuOpen(isOpen) {
  if (!contactToggle || !contactMenu) return;
  contactToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
  contactMenu.hidden = !isOpen;
}

function initContactMenu() {
  if (!contactToggle || !contactMenu) return;
  setContactMenuOpen(false);

  contactToggle.addEventListener("click", (e) => {
    e.preventDefault();
    const isOpen = contactToggle.getAttribute("aria-expanded") === "true";
    setContactMenuOpen(!isOpen);
  });

  document.addEventListener("click", (e) => {
    const target = e.target;
    if (!(target instanceof Node)) return;
    if (contactMenu.contains(target) || contactToggle.contains(target)) return;
    setContactMenuOpen(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setContactMenuOpen(false);
  });
}

function initScrollHint() {
  if (!scrollHint) return;

  const hide = () => scrollHint.classList.add("is-hidden");

  // If there isn't meaningful scroll room, don't show it.
  const hasScrollRoom = () =>
    document.documentElement.scrollHeight - window.innerHeight > 80;

  const refresh = () => {
    if (!hasScrollRoom()) hide();
  };

  refresh();

  window.addEventListener(
    "scroll",
    () => {
      if (window.scrollY > 20) hide();
    },
    { passive: true }
  );

  window.addEventListener("resize", refresh, { passive: true });
}

async function sendMessage(message) {
  addMessage(message, "user");
  const thinkingEl = addMessage("Thinking...", "bot");
  setSending(true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });

    if (!res.ok) {
      throw new Error(`Request failed: ${res.status}`);
    }

    const data = await res.json();
    const body = thinkingEl.querySelector(".msg-body");
    const meta = thinkingEl.querySelector(".msg-meta");
    if (body) {
      // Parse markdown for bot responses
      body.innerHTML = parseMarkdown(data.reply ?? "No response received.");
    }
    if (meta) {
      meta.textContent = formatTime(new Date());
    }
  } catch (err) {
    const body = thinkingEl.querySelector(".msg-body");
    if (body) {
      body.textContent = "Sorry, something went wrong. Please try again.";
    }
    console.error(err);
  } finally {
    setSending(false);
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;
  chatInput.value = "";
  sendMessage(message);
});

// Seed a friendly greeting.
addMessage("Hi! Ask about Dakota's experience, projects, or skills.", "bot");

// Enable theme toggle (sun icon in header).
initTheme();

// Enable contact dropdown menu.
initContactMenu();

// Subtle hint that more content exists below (auto-hides on scroll).
initScrollHint();

// Render resume details below chat (Experience / Skills / Education).
loadAndRenderResume();

