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
const heroCredential = document.getElementById("hero-credential");
const heroTagline = document.getElementById("hero-tagline");
const heroEmail = document.getElementById("hero-email");
const heroLocation = document.getElementById("hero-location");
const suggestionsEl = document.getElementById("suggestions");

const siteHeader = document.getElementById("site-header");
const navLinks = document.getElementById("nav-links");
const hamburger = document.getElementById("hamburger");

// Hero tagline: keep it crisp and consistent (UI copy), independent from the longer resume summary.
const HERO_TAGLINE =
  "Turning product vision into reality with Python-driven AI solutions";

const SESSION_STORAGE_KEY = "resume-assistant-session-id";

function createSessionId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getSessionId() {
  try {
    const existing = localStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) return existing;
    const created = createSessionId();
    localStorage.setItem(SESSION_STORAGE_KEY, created);
    return created;
  } catch {
    return createSessionId();
  }
}

const sessionId = getSessionId();

/**
 * Simple markdown parser for bot responses.
 * Handles: **bold**, *italic*, headings, and bullet lists.
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

  const applyInlineMarkdown = (input) => {
    let out = escapeHtml(input);
    // Convert **bold** to <strong>
    out = out.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // Convert *italic* (but not ** which is bold)
    out = out.replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, "<em>$1</em>");
    return out;
  };

  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraphLines.length) return;
    const body = paragraphLines.map(applyInlineMarkdown).join("<br>");
    blocks.push(`<p>${body}</p>`);
    paragraphLines = [];
  };

  const flushList = () => {
    if (!listItems.length) return;
    blocks.push(`<ul>${listItems.map((item) => `<li>${item}</li>`).join("")}</ul>`);
    listItems = [];
  };

  for (const rawLine of lines) {
    const line = rawLine ?? "";
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      blocks.push(`<h${level}>${applyInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    const listMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      listItems.push(applyInlineMarkdown(listMatch[1].trim()));
      continue;
    }

    const continuationMatch = line.match(/^\s{2,}(\S.*)$/);
    if (continuationMatch && listItems.length > 0) {
      const lastIndex = listItems.length - 1;
      listItems[lastIndex] = `${listItems[lastIndex]} ${applyInlineMarkdown(continuationMatch[1].trim())}`;
      continue;
    }

    if (listItems.length > 0) {
      // Non-list text after list starts a new paragraph block.
      flushList();
    }
    paragraphLines.push(trimmed);
  }

  flushParagraph();
  flushList();

  if (!blocks.length) {
    const fallback = applyInlineMarkdown(String(text || "").trim());
    return fallback ? `<p>${fallback}</p>` : "";
  }

  return blocks.join("");
}

// --- Feedback UI ---
let firstResponseFeedbackShown = false;

function addFeedbackUI(messageEl, trigger) {
  const feedback = document.createElement("div");
  feedback.className = "msg-feedback";
  feedback.innerHTML = `
    <button class="feedback-btn" data-rating="up" title="Good response">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
      </svg>
    </button>
    <button class="feedback-btn" data-rating="down" title="Could be better">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
      </svg>
    </button>
  `;

  const commentBox = document.createElement("div");
  commentBox.className = "feedback-comment";
  commentBox.style.display = "none";
  commentBox.innerHTML = `
    <input type="text" placeholder="What could be better?" maxlength="200" />
    <button type="button">Send</button>
  `;

  feedback.querySelectorAll(".feedback-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      feedback.querySelectorAll(".feedback-btn").forEach(b => b.disabled = true);

      const rating = btn.dataset.rating;
      btn.classList.add("selected");

      if (rating === "down") {
        commentBox.style.display = "flex";
        commentBox.querySelector("input").focus();
      } else {
        await submitFeedback(rating, "", trigger);
        feedback.innerHTML = "<span class='feedback-thanks'>Thanks for the feedback. Feel free to keep the conversation going.</span>";
        chatInput.focus();
      }
    });
  });

  const sendBtn = commentBox.querySelector("button");
  sendBtn.addEventListener("click", async () => {
    if (sendBtn.disabled) return;
    sendBtn.disabled = true;
    sendBtn.textContent = "Sending...";
    const comment = commentBox.querySelector("input").value.trim();
    await submitFeedback("down", comment, trigger);
    commentBox.style.display = "none";
    feedback.innerHTML = "<span class='feedback-thanks'>Thanks for the feedback. Feel free to keep the conversation going.</span>";
    chatInput.focus();
  });

  messageEl.appendChild(feedback);
  messageEl.appendChild(commentBox);
}

async function submitFeedback(rating, comment, trigger) {
  try {
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ session_id: sessionId, rating, comment, trigger }),
    });
  } catch (err) {
    console.error("Feedback submission failed:", err);
  }
}

function addMessage(text, role) {
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

  div.append(body);
  chatLog.appendChild(div);
  requestScrollToBottom();
  return div;
}

// --- Chat autoscroll (robust, low-tech-debt) ---
// We only stick to bottom when the user is already near the bottom.
let autoScrollEnabled = true;
let pendingScroll = false;

function isChatNearBottom(thresholdPx = 80) {
  if (!chatLog) return true;
  const distance =
    chatLog.scrollHeight - (chatLog.scrollTop + chatLog.clientHeight);
  return distance < thresholdPx;
}

function requestScrollToBottom() {
  if (!chatLog || !autoScrollEnabled) return;
  if (pendingScroll) return;
  pendingScroll = true;
  requestAnimationFrame(() => {
    pendingScroll = false;
    if (!chatLog || !autoScrollEnabled) return;
    chatLog.scrollTop = chatLog.scrollHeight;
  });
}

function initChatAutoScroll() {
  if (!chatLog) return;

  autoScrollEnabled = true;

  chatLog.addEventListener(
    "scroll",
    () => {
      autoScrollEnabled = isChatNearBottom();
    },
    { passive: true }
  );

  // Covers both appends and "Thinking…" -> full reply replacements.
  const mo = new MutationObserver(() => requestScrollToBottom());
  mo.observe(chatLog, { childList: true, subtree: true, characterData: true });
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

function slugifyAnchor(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function buildResumeAnchor(prefix, value) {
  const slug = slugifyAnchor(value);
  return slug ? `${prefix}-${slug}` : "";
}

function safeExternalUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(String(value), window.location.origin);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

function normalizeSkillName(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9+.#/\s-]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function buildSkillLookup(skills) {
  const lookup = new Map();
  Object.values(skills || {}).forEach((group) => {
    safeArray(group).forEach((skill) => {
      const key = normalizeSkillName(skill);
      if (key && !lookup.has(key)) lookup.set(key, skill);
    });
  });
  return lookup;
}

function buildRoleAskPrompt(exp) {
  const role = String(exp?.role || "this role").trim();
  const company = String(exp?.company || "").trim();
  const roleLabel = company ? `${role} at ${company}` : role;
  return `What impact did Dakota have as ${roleLabel}? Focus on core responsibilities, measurable outcomes, and why this experience is relevant for hiring decisions.`;
}

function renderExperience(items, skillLookup = new Map()) {
  if (!experienceGrid) return;
  experienceGrid.innerHTML = "";
  experienceGrid.className = "experience-timeline";

  safeArray(items).forEach((exp, idx) => {
    const role = el("div", { class: "timeline-role", text: exp.role || "" });
    const companyText = exp.company || "";
    const company = el("div", { class: "timeline-company", text: companyText });

    // Build meta column (date + location, right-aligned)
    const metaChildren = [];
    if (exp.duration) metaChildren.push(el("div", { text: exp.duration }));
    if (exp.location) metaChildren.push(el("div", { text: exp.location }));
    const meta = metaChildren.length ? el("div", { class: "timeline-meta" }, metaChildren) : null;

    const header = el("div", { class: "timeline-header" }, [role, meta]);

    const achievements = safeArray(exp.achievements);
    const bullets = achievements.map((a, i) =>
      el("li", { class: i >= 3 ? "is-extra" : "", text: a })
    );
    const list = bullets.length
      ? el("ul", { class: "timeline-bullets is-collapsed" }, bullets)
      : null;

    const extrasCount = Math.max(0, achievements.length - 3);
    const toggle =
      extrasCount > 0
        ? el("button", {
            class: "timeline-toggle",
            type: "button",
            text: `Show more (${extrasCount})`,
          })
        : null;

    if (toggle && list) {
      toggle.addEventListener("click", () => {
        const expanded = list.classList.toggle("is-collapsed") === false;
        toggle.textContent = expanded ? "Show less" : `Show more (${extrasCount})`;
      });
    }

    // Technology tags
    const technologies = safeArray(exp.technologies);
    const alignedTech = [];
    const seen = new Set();
    technologies.forEach((tech) => {
      const key = normalizeSkillName(tech);
      const label = skillLookup.get(key) || tech;
      const seenKey = normalizeSkillName(label);
      if (!seenKey || seen.has(seenKey)) return;
      seen.add(seenKey);
      alignedTech.push(label);
    });
    const tags = technologies.length
      ? el("div", { class: "timeline-tags" },
          alignedTech.map((label) =>
            el("a", {
              class: "timeline-tag timeline-tag--link",
              href: "#skills",
              text: label,
              "aria-label": `Jump to skills section for ${label}`,
            })
          )
        )
      : null;

    const askBtn = el("button", {
      class: "timeline-ask-btn",
      type: "button",
      "aria-label": `Ask AI about ${exp.role || "this experience"}`,
    }, [
      el("span", { class: "timeline-ask-icon", "aria-hidden": "true", text: "✦" }),
      el("span", { text: "Ask AI" }),
    ]);
    askBtn.addEventListener("click", async () => {
      const chatSection = document.getElementById("chat");
      chatSection?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
      if (chatInput?.disabled) return;
      const prompt = buildRoleAskPrompt(exp);
      await sendMessage(prompt);
    });
    const actions = el("div", { class: "timeline-actions" }, [askBtn]);

    const delayClass = idx <= 4 ? ` reveal-delay-${Math.min(idx + 1, 4)}` : "";
    const entry = el("article", { class: `timeline-entry reveal${delayClass}` }, [
      header,
      company,
      list,
      toggle,
      tags,
      actions,
    ]);
    experienceGrid.append(entry);
  });
}

function renderSkills(skills) {
  if (!skillsGrid) return;
  skillsGrid.innerHTML = "";

  const entries = Object.entries(skills || {});
  entries.forEach(([key, items], idx) => {
    const label = key.replace(/_/g, " ").toUpperCase();
    const chips = safeArray(items).map((s) => el("button", { class: "chip chip--static", type: "button", text: s }));
    const delayClass = idx <= 4 ? ` reveal-delay-${Math.min(idx + 1, 4)}` : "";
    const block = el("section", { class: `skills-block reveal${delayClass}` }, [
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
    const cardId = buildResumeAnchor("education", ed.school || ed.degree);
    const row = el("div", { class: "resume-card-title-row" }, [
      el("div", { class: "resume-card-title", text: ed.school || "" }),
      el("div", { class: "resume-card-meta", text: ed.graduation || "" }),
    ]);
    const subtitle = el("div", { class: "resume-card-subtitle", text: ed.degree || "" });
    educationGrid.append(
      el("article", {
        id: cardId,
        class: "resume-card reveal",
        "data-citation-label": ed.school || ed.degree || "Education",
      }, [row, subtitle])
    );
  });
}

function renderCertifications(items) {
  if (!certificationsGrid) return;
  certificationsGrid.innerHTML = "";
  safeArray(items).forEach((c, idx) => {
    const name = c.name || "";
    const cardId = buildResumeAnchor("certification", name);
    const credentialUrl = safeExternalUrl(c.credential_url);
    const showDate =
      /PCAP/i.test(name) || /Certified Associate Python Programmer/i.test(name);
    const rowChildren = [el("div", { class: "resume-card-title", text: name })];
    if (showDate && c.date) {
      rowChildren.push(el("div", { class: "resume-card-meta", text: c.date }));
    }
    const row = el("div", { class: "resume-card-title-row" }, rowChildren);
    const subtitle = el("div", { class: "resume-card-subtitle", text: c.issuer || "" });
    const status =
      c.status && String(c.status).trim() && String(c.status).toLowerCase() !== "completed"
        ? el("div", { class: "resume-card-status", text: c.status })
        : null;
    const certificateLabel = credentialUrl
      ? el("span", { class: "resume-card-link-label", text: "View certificate" })
      : null;
    const delayClass = idx <= 4 ? ` reveal-delay-${Math.min(idx + 1, 4)}` : "";
    const tagName = credentialUrl ? "a" : "article";
    const attrs = {
      id: cardId,
      class: `resume-card${credentialUrl ? " resume-card--link" : ""} reveal${delayClass}`,
      "data-citation-label": name || "Certification",
    };
    if (credentialUrl) {
      attrs.href = credentialUrl;
      attrs.target = "_blank";
      attrs.rel = "noopener noreferrer";
      attrs["aria-label"] = `View certificate for ${name}`;
    }
    certificationsGrid.append(
      el(tagName, attrs, [row, subtitle, status, certificateLabel])
    );
  });
}

const CITATION_RULES = [
  {
    label: "Experience",
    targetId: "experience-evidence",
    scrollId: "experience",
    sectionId: "experience",
    patterns: [
      /senior product manager/i,
      /\bvp\b/i,
      /parametric/i,
      /morgan stanley/i,
      /\b8\+?\s*years\b/i,
      /operations/i,
      /major financial institution/i,
      /investment integration/i,
    ],
  },
  {
    label: "PCAP certification",
    targetId: "certification-pcap-certified-associate-python-programmer",
    sectionId: "education",
    patterns: [
      /\bpcap\b/i,
      /certified associate python programmer/i,
      /python institute/i,
    ],
  },
  {
    label: "AI Product Management",
    targetId: "certification-ai-product-management",
    sectionId: "education",
    patterns: [
      /ai product management/i,
      /product faculty/i,
      /ben ai/i,
      /rag-based assistant/i,
      /\brag\b/i,
      /3,500\+?\s+annual/i,
    ],
  },
  {
    label: "Finance certification",
    targetId: "certification-finance-certification",
    sectionId: "education",
    patterns: [/finance certification/i],
  },
  {
    label: "Education",
    targetId: "education-evidence",
    sectionId: "education",
    sourceTitles: ["Education"],
    patterns: [/\bmba\b/i, /washington state university/i],
  },
  {
    label: "Certifications",
    targetId: "certifications-evidence",
    sectionId: "education",
    sourceTitles: ["Certifications"],
  },
  {
    label: "Skills",
    targetId: "skills",
    sectionId: "skills",
    sourceTitles: ["Skills and Expertise"],
  },
];

function expandResumeSection(sectionId) {
  const section = document.getElementById(sectionId);
  if (!section?.classList?.contains("resume-section")) return;
  section.classList.add("is-expanded");
  const header = section.querySelector(".section-header--link[role='button']");
  header?.setAttribute("aria-expanded", "true");
  const toggle = section.querySelector(".section-toggle");
  if (toggle) toggle.textContent = "Hide details";
}

function highlightCitationTarget(targetId, sectionId, scrollId = targetId) {
  if (sectionId) expandResumeSection(sectionId);
  const target = document.getElementById(targetId);
  if (!target) return;
  const scrollTarget = document.getElementById(scrollId) || target;
  target.classList.add("is-visible");
  window.setTimeout(() => {
    scrollTarget.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
    target.classList.remove("is-cited");
    void target.offsetWidth;
    target.classList.add("is-cited");
    window.setTimeout(() => target.classList.remove("is-cited"), 2400);
  }, 120);
}

function buildAnswerCitations(data) {
  const reply = String(data?.reply || "");
  // Sources arrive as bare titles (/api/chat) or {title, score} objects (SSE).
  const sources = new Set(
    safeArray(data?.sources).map((s) => String((s && s.title) ?? s ?? ""))
  );
  const citations = [];
  const seenTargets = new Set();

  CITATION_RULES.forEach((rule) => {
    const sourceMatch = safeArray(rule.sourceTitles).some((title) => sources.has(title));
    const textMatch = safeArray(rule.patterns).some((pattern) => pattern.test(reply));
    if (!sourceMatch && !textMatch) return;
    if (seenTargets.has(rule.targetId)) return;
    seenTargets.add(rule.targetId);
    citations.push(rule);
  });

  return citations.slice(0, 4);
}

function renderAnswerCitations(data) {
  const citations = buildAnswerCitations(data);
  if (!citations.length) return null;

  const list = el("div", { class: "answer-citation-list" });
  citations.forEach((citation) => {
    const button = el("button", {
      class: "answer-citation",
      type: "button",
      text: citation.label,
    });
    button.addEventListener("click", () => {
      highlightCitationTarget(citation.targetId, citation.sectionId, citation.scrollId);
    });
    list.append(button);
  });

  return el("div", { class: "answer-citations" }, [
    el("span", { class: "answer-citations-label", text: "Sources" }),
    list,
  ]);
}

function initRevealOnScroll() {
  const nodes = Array.from(document.querySelectorAll(".reveal"));
  if (nodes.length === 0) return;

  const prefersReduced =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReduced) {
    nodes.forEach((n) => n.classList.add("is-visible"));
    return;
  }

  if (!("IntersectionObserver" in window)) {
    nodes.forEach((n) => n.classList.add("is-visible"));
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        io.unobserve(entry.target);
      });
    },
    { threshold: 0.08, rootMargin: "0px 0px -10% 0px" }
  );

  nodes.forEach((n) => io.observe(n));
}

// Hero CTA — scroll to chat and focus input
const heroCta = document.getElementById("hero-cta");
if (heroCta) {
  heroCta.addEventListener("click", (e) => {
    e.preventDefault();
    const chatEl = document.getElementById("chat");
    if (chatEl) chatEl.scrollIntoView({ behavior: scrollBehavior() });
    // Retry focus until the input is visible and focused
    let attempts = 0;
    const tryFocus = () => {
      if (chatInput) {
        chatInput.focus();
        if (document.activeElement === chatInput || attempts > 10) return;
      }
      attempts++;
      setTimeout(tryFocus, 150);
    };
    setTimeout(tryFocus, 300);
  });
}

// Secondary hero CTA — reveal the resume and move directly to Experience.
const heroResumeCta = document.getElementById("hero-resume-cta");
if (heroResumeCta) {
  heroResumeCta.addEventListener("click", (e) => {
    e.preventDefault();
    expandResumeSection("experience");
    const experienceEl = document.getElementById("experience");
    window.setTimeout(() => {
      experienceEl?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
    }, 100);
  });
}

// Collapsible resume sections — attached after DOM is fully ready
window.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".resume-section .section-header--link[role='button']").forEach((header) => {
    header.style.cursor = "pointer";
    header.addEventListener("click", (e) => {
      e.preventDefault();
      const section = header.closest(".resume-section");
      const expanded = section.classList.toggle("is-expanded");
      header.setAttribute("aria-expanded", String(expanded));
      const toggle = header.querySelector(".section-toggle");
      if (toggle) toggle.textContent = expanded ? "Hide details" : "Show details";
    });
    header.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); header.click(); }
    });
  });
});

// --- Theme (dark mode) ---
// theme-init.js already stamped data-theme before first paint; this wires the
// toggle, persists the choice, and keeps <meta name="theme-color"> in sync.
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

function initTheme() {
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

  // Follow live system changes only while no explicit choice is stored.
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
}

function initNavbar() {
  // Frosted glass on scroll
  if (siteHeader) {
    let wasScrolled = false;
    window.addEventListener("scroll", () => {
      const isScrolled = window.scrollY > 20;
      if (isScrolled !== wasScrolled) {
        wasScrolled = isScrolled;
        siteHeader.classList.toggle("is-scrolled", isScrolled);
      }
    }, { passive: true });
  }

  // Hamburger toggle
  if (hamburger && navLinks) {
    hamburger.addEventListener("click", () => {
      const isOpen = navLinks.classList.toggle("is-open");
      hamburger.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });

    // Close on nav link click (mobile)
    navLinks.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        navLinks.classList.remove("is-open");
        hamburger.setAttribute("aria-expanded", "false");
      });
    });

    // Close on outside click
    document.addEventListener("click", (e) => {
      if (!(e.target instanceof Node)) return;
      if (navLinks.contains(e.target) || hamburger.contains(e.target)) return;
      navLinks.classList.remove("is-open");
      hamburger.setAttribute("aria-expanded", "false");
    });

    // Close on Escape key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && navLinks.classList.contains("is-open")) {
        navLinks.classList.remove("is-open");
        hamburger.setAttribute("aria-expanded", "false");
        hamburger.focus();
      }
    });
  }
}

async function loadAndRenderResume() {
  try {
    const res = await fetch("/api/resume");
    if (!res.ok) throw new Error(`Resume fetch failed: ${res.status}`);
    const data = await res.json();

    const personal = data.personal || {};
    const name = (personal.name || "").trim();
    const creds = (personal.credentials || "").trim();
    const displayName = [name, creds].filter(Boolean).join(", ");
    const email = (personal.email || "").trim();
    if (brandTitle && displayName) brandTitle.textContent = displayName.toUpperCase();
    if (heroName && name) heroName.textContent = name;
    if (heroCredential && creds) heroCredential.textContent = creds;
    if (heroTagline) heroTagline.textContent = HERO_TAGLINE;
    if (heroEmail && email) {
      const t = heroEmail.querySelector(".hero-contact-text");
      if (t) t.textContent = email;
    }
    if (heroLocation && personal.location) {
      const t = heroLocation.querySelector(".hero-contact-text");
      if (t) t.textContent = personal.location;
    }

    const skillLookup = buildSkillLookup(data.skills);
    renderExperience(data.experience, skillLookup);
    renderSkills(data.skills);
    renderEducation(data.education);
    renderCertifications(data.certifications);
    initRevealOnScroll();
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

function scrollBehavior() {
  const reduced =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reduced ? "auto" : "smooth";
}

/**
 * Trailing unpaired bold/italic markers render as literal asterisks for a
 * frame while streaming; trim them from the parse input only.
 */
function stripUnpairedEmphasis(text) {
  let out = text;
  const sinceNl = out.slice(out.lastIndexOf("\n") + 1);
  if ((sinceNl.match(/\*\*/g) || []).length % 2 === 1) {
    out = out.slice(0, out.lastIndexOf("**"));
  } else if ((sinceNl.replace(/\*\*/g, "").match(/\*/g) || []).length % 2 === 1) {
    out = out.slice(0, out.lastIndexOf("*"));
  }
  return out;
}

/**
 * Extract a short topic label from the user's query for dynamic step text.
 */
function extractQueryTopic(message) {
  const lower = message.toLowerCase().replace(/[?!.]+$/g, "").trim();
  // Strip common question prefixes to get the core topic
  const prefixes = [
    "tell me about", "what is", "what are", "what's", "what can",
    "does dakota know", "does dakota have", "show me", "describe",
    "how does", "how did", "can you tell me about", "explain",
  ];
  for (const p of prefixes) {
    if (lower.startsWith(p)) return lower.slice(p.length).trim() || null;
  }
  // If short enough, use the whole query
  return lower.length <= 40 ? lower : null;
}

/**
 * POST to an SSE endpoint and dispatch parsed events to handlers.
 * Returns {ok:false, res} for non-2xx responses (callers reuse the existing
 * 403/unlock and error branches); {ok:true} after the stream ends.
 */
async function streamChat(url, body, handlers) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Explicit for clarity (it's the default): quota/unlock ride the HttpOnly
    // visitor cookie; session_id in the body is history-only.
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) return { ok: false, res };

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (frame) => {
    let eventName = null;
    let data = null;
    for (const line of frame.split("\n")) {
      if (line.startsWith("event: ")) eventName = line.slice(7);
      else if (line.startsWith("data: ")) {
        try {
          data = JSON.parse(line.slice(6));
        } catch {
          data = null;
        }
      }
    }
    if (!eventName || data === null) return;
    if (eventName === "session") handlers.onSession?.(data);
    else if (eventName === "status") handlers.onStatus?.(data);
    else if (eventName === "delta") handlers.onDelta?.(data);
    else if (eventName === "done") handlers.onDone?.(data);
    else if (eventName === "error") handlers.onError?.(data);
  };

  // Network reads split arbitrarily: buffer and only process complete
  // "\n\n"-terminated frames, keeping the remainder for the next read.
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      dispatch(buffer.slice(0, sep));
      buffer = buffer.slice(sep + 2);
    }
  }
  return { ok: true, res };
}

/**
 * Event-driven status steps. Real pipeline events can arrive faster than the
 * entrance transition plays, so DOM insertion is paced through a short display
 * queue (real data, gated presentation). The queue flushes the moment the
 * first answer token arrives; the answer is never delayed.
 */
function createStatusSteps(container) {
  container.innerHTML = "";
  container.classList.add("has-steps");
  const announcer = document.getElementById("step-announcer");
  const prefersReduced =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MIN_STEP_INTERVAL_MS = 350;

  const stepsWrap = document.createElement("div");
  stepsWrap.className = "status-steps";
  container.appendChild(stepsWrap);

  const queue = [];
  const stepEls = [];
  let lastRenderAt = 0;
  let timer = null;
  let flushed = false;

  function renderStep({ text, items, announce }) {
    if (!stepsWrap.isConnected) return;
    const step = document.createElement("div");
    step.className = "status-step";
    step.setAttribute("aria-hidden", "true");
    const icon = document.createElement("span");
    icon.className = "step-icon";
    icon.textContent = "✓";
    step.appendChild(icon);
    const content = document.createElement("div");
    content.className = "step-content";
    const label = document.createElement("span");
    label.className = "step-label";
    label.textContent = text;
    content.appendChild(label);
    if (items && items.length) {
      const list = document.createElement("ul");
      list.className = "step-items";
      items.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        list.appendChild(li);
      });
      content.appendChild(list);
    }
    step.appendChild(content);
    stepsWrap.appendChild(step);
    requestAnimationFrame(() => step.classList.add("is-visible"));
    // Screen readers: announce stage completions only, never per-token.
    if (announce && announcer) announcer.textContent = announce;
    stepEls.push(step);
    lastRenderAt = Date.now();
  }

  function pump() {
    if (timer || !queue.length) return;
    const wait =
      prefersReduced || flushed
        ? 0
        : Math.max(0, MIN_STEP_INTERVAL_MS - (Date.now() - lastRenderAt));
    timer = setTimeout(() => {
      timer = null;
      const next = queue.shift();
      if (next) renderStep(next);
      pump();
    }, wait);
  }

  return {
    addStep(text, { items = null, announce = null } = {}) {
      queue.push({ text, items, announce: announce ?? text });
      pump();
    },
    /** First delta arrived: render all remaining queued steps in one frame. */
    flush() {
      flushed = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      while (queue.length) renderStep(queue.shift());
    },
    /** Replace the step stack with a single summary line (called on done). */
    collapse(summaryText, sourceItems) {
      this.flush();
      if (!stepsWrap.isConnected) return;
      stepEls.forEach((step) => step.remove());
      stepEls.length = 0;
      renderStep({
        text: summaryText,
        items: sourceItems && sourceItems.length ? sourceItems.slice(0, 4) : null,
        announce: null,
      });
    },
  };
}

/** Follow-up chips live only on the latest bot message. */
function removePreviousFollowups() {
  document.querySelectorAll(".msg-followups").forEach((node) => {
    if (node.contains(document.activeElement)) chatInput?.focus();
    node.remove();
  });
}

function getContactEmail() {
  const heroText = heroEmail?.querySelector(".hero-contact-text")?.textContent?.trim();
  return heroText || "dakotaradigan@gmail.com";
}

/**
 * Build the follow-up chip row for a completed answer. When the reply consumed
 * the last free exchange, question chips would only lead to the unlock wall,
 * so conversion chips are shown instead.
 */
function renderFollowups(data) {
  const quotaExhausted = data.quota_remaining === 0;
  let chips;
  if (quotaExhausted) {
    chips = [
      {
        label: "Run a fit analysis for your role",
        action: () => {
          document
            .getElementById("jd-match")
            ?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
          document.getElementById("jd-input")?.focus({ preventScroll: true });
        },
      },
      {
        label: "Email Dakota",
        action: () => {
          const subject = encodeURIComponent("Reaching out from your resume site");
          window.location.href = `mailto:${getContactEmail()}?subject=${subject}`;
        },
      },
      {
        label: "See full resume",
        action: () =>
          document
            .getElementById("resume")
            ?.scrollIntoView({ behavior: scrollBehavior(), block: "start" }),
      },
    ];
  } else {
    const questions = safeArray(data.followups)
      .map((q) => String(q || "").trim())
      .filter(Boolean)
      .slice(0, 3);
    if (!questions.length) return null;
    chips = questions.map((q) => ({
      label: q.length > 60 ? `${q.slice(0, 59)}…` : q,
      action: () => sendMessage(q),
    }));
  }

  const chipsRow = el(
    "div",
    { class: "chips" },
    chips.map((chip) => {
      const btn = el("button", { class: "chip", type: "button", text: chip.label });
      btn.addEventListener("click", chip.action);
      return btn;
    })
  );
  return el("div", { class: "msg-followups" }, [
    el("span", {
      class: "answer-citations-label",
      text: quotaExhausted ? "Continue" : "Keep exploring",
    }),
    chipsRow,
  ]);
}

/** Free-limit wall: password unlock plus retry of the blocked message. */
function renderUnlockForm(thinkingEl, detail, message) {
  const body = thinkingEl.querySelector(".msg-body");
  if (!body) return;
  thinkingEl.classList.remove("is-thinking");
  body.textContent = "";

  const prompt = el("p", { class: "unlock-prompt", text: detail || "You've hit the free chat limit." });
  const passwordInput = el("input", {
    type: "text",
    class: "unlock-input",
    placeholder: "Enter password",
    autocomplete: "off",
    "aria-label": "Chat unlock password",
  });
  const submitBtn = el("button", { type: "submit", class: "unlock-submit", text: "Unlock" });
  const unlockForm = el("form", { class: "unlock-form" }, [passwordInput, submitBtn]);
  const errorEl = el("p", { class: "unlock-error" });

  body.append(prompt, unlockForm, errorEl);
  passwordInput.focus();

  unlockForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const password = passwordInput.value.trim();

    if (!password) {
      errorEl.textContent = "Please enter a password.";
      errorEl.style.display = "block";
      return;
    }

    try {
      submitBtn.disabled = true;
      const unlockRes = await fetch("/api/unlock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ password, session_id: sessionId }),
      });

      const unlockData = await unlockRes.json();

      if (unlockData.success) {
        thinkingEl.remove();
        autoScrollEnabled = true;
        requestScrollToBottom();
        setTimeout(() => sendMessage(message, { isRetry: true }), 0);
        return;
      }
      errorEl.textContent = unlockData.message || "Incorrect password.";
      errorEl.style.display = "block";
      passwordInput.focus();
    } catch (unlockErr) {
      errorEl.textContent = "Failed to unlock. Please try again.";
      errorEl.style.display = "block";
      console.error(unlockErr);
      passwordInput.focus();
    } finally {
      submitBtn.disabled = false;
    }
  });
}

async function sendMessage(message, { isRetry = false } = {}) {
  suggestionsEl?.remove();
  removePreviousFollowups();
  if (!isRetry) addMessage(message, "user");
  const thinkingEl = addMessage("Thinking...", "bot");
  const thinkingBody = thinkingEl.querySelector(".msg-body");
  thinkingEl.classList.add("is-thinking");
  setSending(true);

  const steps = thinkingBody ? createStatusSteps(thinkingBody) : null;
  const topic = extractQueryTopic(message);
  steps?.addStep(topic ? `Searching for "${topic}"...` : "Searching Dakota's experience...");

  // Streaming render state: throttled re-parse of the accumulated markdown.
  const FOLLOWUPS_MARKER = "FOLLOWUPS:";
  const startedAt = Date.now();
  let accumulated = "";
  let answerDiv = null;
  let renderPending = false;
  let maxAnswerHeight = 0;
  let finalData = null;
  let streamError = null;

  // Screen readers: never re-announce the growing answer, only completions.
  chatLog?.setAttribute("aria-live", "off");
  const announcer = document.getElementById("step-announcer");

  function streamRenderText(text) {
    // Hold back a marker-length tail so a FOLLOWUPS line split across SSE
    // frames never flashes on screen; done.reply is the stripped final text.
    let out = text.slice(0, Math.max(0, text.length - FOLLOWUPS_MARKER.length));
    const markerIdx = out.lastIndexOf(`\n${FOLLOWUPS_MARKER}`);
    if (markerIdx !== -1) {
      out = out.slice(0, markerIdx);
    } else {
      const nl = out.lastIndexOf("\n");
      const lastLine = out.slice(nl + 1).trimStart();
      if (lastLine && FOLLOWUPS_MARKER.startsWith(lastLine)) {
        out = nl === -1 ? "" : out.slice(0, nl);
      }
    }
    return stripUnpairedEmphasis(out);
  }

  function scheduleRender() {
    if (renderPending || !answerDiv) return;
    renderPending = true;
    requestAnimationFrame(() => {
      renderPending = false;
      if (!answerDiv) return;
      answerDiv.innerHTML = parseMarkdown(streamRenderText(accumulated));
      // Height ratchet: rendered content only grows during streaming, so the
      // bubble never bounces and autoscroll stays stable.
      const height = answerDiv.offsetHeight;
      if (height > maxAnswerHeight) {
        maxAnswerHeight = height;
        answerDiv.style.minHeight = `${height}px`;
      }
      requestScrollToBottom();
    });
  }

  function sourceItemsFrom(sources) {
    return safeArray(sources).map((s) => {
      const title = String((s && s.title) ?? s ?? "");
      // Hybrid results may be lexical-only, so raw vector scores are not confidence values.
      return title;
    });
  }

  function ensureAnswerDiv() {
    if (answerDiv || !thinkingBody) return;
    steps?.flush();
    thinkingEl.classList.remove("is-thinking");
    answerDiv = document.createElement("div");
    answerDiv.className = "step-answer";
    thinkingBody.appendChild(answerDiv);
  }

  try {
    const result = await streamChat(
      "/api/chat/stream",
      { message, session_id: sessionId },
      {
        onStatus(data) {
          if (data.stage === "cached") {
            steps?.addStep("Answered from cache");
          } else if (data.stage === "rag_search" && data.state === "done") {
            if (data.used_rag && data.sources?.length) {
              const items = sourceItemsFrom(data.sources);
              steps?.addStep(
                `Found ${items.length} relevant section${items.length > 1 ? "s" : ""}`,
                { items }
              );
            } else {
              steps?.addStep("Using full resume context");
            }
          } else if (data.stage === "routing") {
            steps?.addStep(`Routed to ${data.model}`);
          } else if (data.stage === "generation" && data.state === "start") {
            steps?.addStep("Generating answer...");
          }
        },
        onDelta(data) {
          ensureAnswerDiv();
          accumulated += data.text || "";
          scheduleRender();
        },
        onDone(data) {
          finalData = data;
        },
        onError(data) {
          streamError = data;
        },
      }
    );

    if (!result.ok) {
      const errorData = await result.res.json().catch(() => ({}));
      if (result.res.status === 403) {
        renderUnlockForm(thinkingEl, errorData.detail, message);
      } else {
        const body = thinkingEl.querySelector(".msg-body");
        if (body) {
          thinkingEl.classList.remove("is-thinking");
          body.textContent =
            errorData.detail || "Sorry, something went wrong. Please try again.";
        }
      }
      requestScrollToBottom();
      return;
    }

    if (streamError || !finalData) {
      const body = thinkingEl.querySelector(".msg-body");
      if (body) {
        thinkingEl.classList.remove("is-thinking");
        body.textContent =
          streamError?.detail || "Sorry, something went wrong. Please try again.";
      }
      if (announcer) announcer.textContent = "Something went wrong.";
      requestScrollToBottom();
      return;
    }

    // Finalize: authoritative render of the stripped reply, then the step
    // summary, citations, follow-up chips, and feedback UI.
    thinkingEl.classList.remove("is-thinking");
    ensureAnswerDiv();
    if (answerDiv) {
      answerDiv.innerHTML = parseMarkdown(finalData.reply ?? "No response received.");
      answerDiv.style.minHeight = "";
    }

    const sourceItems = sourceItemsFrom(finalData.sources);
    const summaryParts = [
      finalData.used_rag
        ? `${sourceItems.length} source${sourceItems.length === 1 ? "" : "s"}`
        : "Full resume context",
    ];
    if (finalData.model) summaryParts.push(finalData.model);
    summaryParts.push(`${((Date.now() - startedAt) / 1000).toFixed(1)}s`);
    steps?.collapse(summaryParts.join(" · "), finalData.used_rag ? sourceItems : null);

    if (thinkingBody) {
      const citations = renderAnswerCitations(finalData);
      if (citations) thinkingBody.appendChild(citations);
      const followups = renderFollowups(finalData);
      if (followups) thinkingBody.appendChild(followups);
    }

    if (announcer) {
      const firstSentence = String(finalData.reply || "").split(/(?<=[.!?])\s/)[0] || "";
      announcer.textContent = `Answer ready. ${firstSentence.slice(0, 150)}`;
    }

    if (!firstResponseFeedbackShown) {
      firstResponseFeedbackShown = true;
      addFeedbackUI(thinkingEl, "first_response");
    }

    requestScrollToBottom();
  } catch (err) {
    const body = thinkingEl.querySelector(".msg-body");
    if (body) {
      thinkingEl.classList.remove("is-thinking");
      body.textContent = "Sorry, something went wrong. Please try again.";
    }
    requestScrollToBottom();
    console.error(err);
  } finally {
    chatLog?.setAttribute("aria-live", "polite");
    thinkingEl?.classList?.remove("is-thinking");
    setSending(false);
    chatInput.focus();
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;
  chatInput.value = "";
  // Detect pasted job descriptions BEFORE any fetch: chat caps at 2,000 chars,
  // and the fit analysis is the better tool for a JD anyway.
  if (looksLikeJD(message)) {
    renderJDInterstitial(message);
    return;
  }
  sendMessage(message);
});

// Seed a friendly greeting.
const introMsg = addMessage("Hi! Ask about Dakota's experience, projects, or skills.", "bot");
introMsg.classList.add("intro");

// Robust chat stick-to-bottom behavior.
initChatAutoScroll();

// Navbar: frosted glass on scroll + hamburger.
initNavbar();

// Theme toggle + persistence (initial theme applied by theme-init.js).
initTheme();

// Explore link: focus chat input after scroll completes.
document.querySelector(".hero-explore")?.addEventListener("click", () => {
  setTimeout(() => chatInput?.focus(), 400);
});

// Suggestion chips - click to send, remove on use.
suggestionsEl?.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => sendMessage(chip.textContent.trim()));
});

// Feedback dialog
const feedbackDialog = document.getElementById("feedback-dialog");
const feedbackOpenBtn = document.getElementById("feedback-btn");
const feedbackCancelBtn = document.getElementById("feedback-cancel");
const feedbackForm = document.getElementById("feedback-form");
const feedbackText = document.getElementById("feedback-text");

if (feedbackDialog && feedbackOpenBtn) {
  feedbackOpenBtn.addEventListener("click", () => {
    feedbackDialog.showModal();
    feedbackText.value = "";
    feedbackText.focus();
  });

  feedbackCancelBtn?.addEventListener("click", () => feedbackDialog.close());

  feedbackDialog.addEventListener("click", (e) => {
    if (e.target === feedbackDialog) feedbackDialog.close();
  });

  feedbackForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    const body = (feedbackText?.value || "").trim();
    if (!body) return;
    const mailto = `mailto:dakotaradigan@gmail.com?subject=${encodeURIComponent("Resume Site Feedback")}&body=${encodeURIComponent(body)}`;
    window.open(mailto, "_blank");
    feedbackDialog.close();
  });
}

// --- JD fit analysis ("Hiring for a role?") ---
const jdInput = document.getElementById("jd-input");
const jdCounter = document.getElementById("jd-counter");
const jdAnalyzeBtn = document.getElementById("jd-analyze");
const jdResults = document.getElementById("jd-results");
const jdAnnouncer = document.getElementById("jd-announcer");
const JD_MIN_CHARS = 200;
const JD_MAX_CHARS = 15000;

let jdBusy = false;
let jdAnalysisMarkdown = ""; // raw markdown of the last completed analysis

function updateJDControls() {
  if (!jdInput || !jdCounter || !jdAnalyzeBtn) return;
  const len = jdInput.value.length;
  jdCounter.textContent = `${len.toLocaleString("en-US")} / 15,000`;
  jdCounter.classList.toggle("is-near-limit", len >= JD_MAX_CHARS * 0.9);
  const tooShort = len < JD_MIN_CHARS;
  jdAnalyzeBtn.disabled = jdBusy || tooShort;
  jdAnalyzeBtn.title = tooShort
    ? `Paste at least ${JD_MIN_CHARS} characters of the job description`
    : "";
  // Explain the disabled button once the user has pasted *something* short —
  // an unexplained dead button reads as frozen.
  const hint = document.getElementById("jd-hint");
  if (hint) hint.hidden = !(len > 0 && tooShort);
}

function looksLikeJD(text) {
  if (text.length <= 800) return false;
  const signals =
    /responsibilit|qualificat|requirement|we are looking for|years of experience|preferred|about the role|equal opportunity|benefits/gi;
  const hits = text.match(signals) || [];
  return new Set(hits.map((h) => h.toLowerCase())).size >= 2;
}

function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.appendChild(helper);
    helper.select();
    const ok = document.execCommand("copy");
    helper.remove();
    if (ok) resolve();
    else reject(new Error("copy failed"));
  });
}

function makeCopyButton(label, getText, announceText) {
  const btn = el("button", { class: "chip jd-copy-btn", type: "button", text: label });
  btn.addEventListener("click", async () => {
    try {
      // Copy from the raw markdown kept in JS scope — never from innerHTML.
      await copyToClipboard(getText());
      const original = label;
      btn.textContent = "✓ Copied";
      btn.classList.add("is-copied");
      if (jdAnnouncer) jdAnnouncer.textContent = announceText;
      setTimeout(() => {
        btn.textContent = original;
        btn.classList.remove("is-copied");
      }, 2000);
    } catch {
      btn.textContent = "Press Ctrl+C";
    }
  });
  return btn;
}

function extractRecruiterSummary(markdown) {
  const match = markdown.match(/##\s*Recruiter Summary\s*\n([\s\S]*?)(?=\n##\s|$)/i);
  return (match ? match[1] : markdown).trim();
}

/** Tag headings for glyph styling; wrap the Recruiter Summary in a card. */
function decorateJDResults(container) {
  const kinds = [
    [/strong matches/i, "strong"],
    [/partial matches/i, "partial"],
    [/honest gaps/i, "gaps"],
    [/recruiter summary/i, "summary"],
  ];
  container.querySelectorAll("h2").forEach((h2) => {
    const kind = kinds.find(([re]) => re.test(h2.textContent));
    if (kind) h2.dataset.jd = kind[1];
  });

  const summaryHeading = container.querySelector('h2[data-jd="summary"]');
  if (summaryHeading) {
    const toWrap = [];
    let node = summaryHeading.nextSibling;
    while (node && !(node.nodeType === 1 && node.tagName === "H2")) {
      toWrap.push(node);
      node = node.nextSibling;
    }
    if (toWrap.length) {
      const card = document.createElement("div");
      card.className = "jd-summary-card";
      summaryHeading.after(card);
      toWrap.forEach((n) => card.appendChild(n));
    }
  }
}

function buildJDMailto() {
  const roleLine =
    (jdInput?.value || "")
      .split("\n")
      .map((l) => l.trim())
      .find(Boolean) || "your role";
  const subject = `Re: ${roleLine.slice(0, 60)} — fit analysis from your site`;
  return `mailto:${getContactEmail()}?subject=${encodeURIComponent(subject)}`;
}

function renderJDActions() {
  if (!jdResults) return;
  jdResults.querySelector(".jd-actions:not(.jd-actions--brief)")?.remove();

  const briefBtn = el("button", {
    class: "jd-analyze jd-brief-btn",
    type: "button",
    text: "Generate screening brief",
  });
  briefBtn.addEventListener("click", async () => {
    if (jdBusy) return;
    briefBtn.disabled = true;
    briefBtn.textContent = "Writing brief…";
    await sendJDMatch("Generate a screening brief", { mode: "brief" });
    briefBtn.disabled = false;
    briefBtn.textContent = "Regenerate brief";
  });

  const emailLink = el("a", {
    class: "chip jd-email-btn",
    href: buildJDMailto(),
    text: "Email Dakota about this role",
  });

  const actions = el("div", { class: "jd-actions" }, [
    makeCopyButton("Copy summary", () => extractRecruiterSummary(jdAnalysisMarkdown), "Recruiter summary copied"),
    briefBtn,
    emailLink,
  ]);
  jdResults.append(actions);
}

async function sendJDMatch(jdText, { mode = "analysis" } = {}) {
  if (jdBusy || !jdResults) return;
  jdBusy = true;
  updateJDControls();
  if (jdAnalyzeBtn && mode === "analysis") jdAnalyzeBtn.textContent = "Analyzing…";

  let streamHost;
  if (mode === "analysis") {
    jdResults.hidden = false;
    jdResults.innerHTML = "";
    jdResults.append(el("h3", { class: "jd-results-heading", text: "Fit analysis" }));
    streamHost = el("div", { class: "jd-stream" });
    jdResults.append(streamHost);
    jdResults.focus({ preventScroll: true });
  } else {
    streamHost = el("div", { class: "jd-stream jd-stream--brief" });
    jdResults.append(streamHost);
  }

  const steps = createStatusSteps(streamHost);
  steps.addStep("Loading Dakota's full resume...");

  let accumulated = "";
  let answerDiv = null;
  let renderPending = false;
  let maxAnswerHeight = 0;
  let finalData = null;
  let streamError = null;

  function ensureAnswerDiv() {
    if (answerDiv) return;
    steps.flush();
    answerDiv = el("div", { class: "step-answer" });
    streamHost.appendChild(answerDiv);
  }

  function scheduleRender() {
    if (renderPending || !answerDiv) return;
    renderPending = true;
    requestAnimationFrame(() => {
      renderPending = false;
      if (!answerDiv) return;
      answerDiv.innerHTML = parseMarkdown(stripUnpairedEmphasis(accumulated));
      const height = answerDiv.offsetHeight;
      if (height > maxAnswerHeight) {
        maxAnswerHeight = height;
        answerDiv.style.minHeight = `${height}px`;
      }
    });
  }

  try {
    const result = await streamChat(
      "/api/jd-match",
      { jd_text: jdText, mode, session_id: sessionId },
      {
        onStatus(data) {
          if (data.stage === "context_load" && data.state === "done") {
            steps.addStep("Reviewing the job description...");
          } else if (data.stage === "generation" && data.state === "start") {
            steps.addStep(mode === "brief" ? "Writing screening brief..." : "Writing fit analysis...");
          }
        },
        onDelta(data) {
          ensureAnswerDiv();
          accumulated += data.text || "";
          scheduleRender();
        },
        onDone(data) {
          finalData = data;
        },
        onError(data) {
          streamError = data;
        },
      }
    );

    if (!result.ok || streamError || !finalData) {
      let detail = streamError?.detail;
      if (!result.ok) {
        const errorData = await result.res.json().catch(() => ({}));
        detail = errorData.detail;
      }
      steps.flush();
      streamHost.append(
        el("p", { class: "jd-error", text: detail || "Something went wrong. Please try again." })
      );
      if (jdAnnouncer) jdAnnouncer.textContent = "The analysis could not be completed.";
      return;
    }

    ensureAnswerDiv();
    answerDiv.innerHTML = parseMarkdown(finalData.reply ?? "");
    answerDiv.style.minHeight = "";
    steps.collapse(mode === "brief" ? "Screening brief ready" : "Analysis complete");
    decorateJDResults(answerDiv);

    if (mode === "analysis") {
      jdAnalysisMarkdown = String(finalData.reply || "");
      renderJDActions();
      if (jdAnnouncer) jdAnnouncer.textContent = "Fit analysis ready.";
    } else {
      const briefMarkdown = String(finalData.reply || "");
      streamHost.append(
        el("div", { class: "jd-actions jd-actions--brief" }, [
          makeCopyButton("Copy brief", () => briefMarkdown, "Screening brief copied"),
        ])
      );
      if (jdAnnouncer) jdAnnouncer.textContent = "Screening brief ready.";
    }
  } catch (err) {
    console.error(err);
    steps.flush();
    streamHost.append(
      el("p", { class: "jd-error", text: "Something went wrong. Please try again." })
    );
  } finally {
    jdBusy = false;
    if (jdAnalyzeBtn) jdAnalyzeBtn.textContent = "Analyze fit";
    updateJDControls();
  }
}

/** Chat interstitial when a pasted message looks like a job description. */
function renderJDInterstitial(text) {
  removePreviousFollowups();
  const msg = addMessage(
    "This looks like a job description. I can run a structured fit analysis against Dakota's full resume instead of a chat reply.",
    "bot"
  );
  const body = msg.querySelector(".msg-body");
  const clipped = text.slice(0, JD_MAX_CHARS);

  const analyzeChip = el("button", { class: "chip chip--primary", type: "button", text: "Analyze fit" });
  analyzeChip.addEventListener("click", () => {
    msg.remove();
    if (jdInput) {
      jdInput.value = clipped;
      updateJDControls();
    }
    document.getElementById("jd-match")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
    sendJDMatch(clipped);
  });

  const justChat = el("button", { class: "chip", type: "button", text: "Just chat" });
  if (text.length > 2000) {
    justChat.disabled = true;
    justChat.title = "Chat is limited to 2,000 characters";
  } else {
    justChat.addEventListener("click", () => {
      msg.remove();
      sendMessage(text);
    });
  }

  body?.append(el("div", { class: "chips jd-interstitial-chips" }, [analyzeChip, justChat]));
  if (text.length > 2000) {
    body?.append(
      el("p", {
        class: "jd-interstitial-note",
        text: "Chat is limited to 2,000 characters — use Analyze fit for full text.",
      })
    );
  }
  // The interstitial consumes no quota and sends nothing until a choice is made.
  requestScrollToBottom();
}

if (jdInput && jdAnalyzeBtn) {
  jdInput.addEventListener("input", updateJDControls);
  updateJDControls();
  jdAnalyzeBtn.addEventListener("click", () => {
    const text = jdInput.value.trim();
    if (text.length < JD_MIN_CHARS) return;
    sendJDMatch(text);
  });
}

// Render resume details below chat (Experience / Skills / Education).
loadAndRenderResume();
