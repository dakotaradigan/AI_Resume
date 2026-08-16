const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendButton = chatForm.querySelector("button");

const resumePaper = document.getElementById("resume-paper");
const resumeDrawer = document.getElementById("resume-drawer");
const resumeTab = document.getElementById("resume-tab");

const brandTitle = document.getElementById("brand-title");
const heroName = document.getElementById("hero-name");
const heroTagline = document.getElementById("hero-tagline");
const heroEmail = document.getElementById("hero-email");
const heroLocation = document.getElementById("hero-location");
const suggestionsEl = document.getElementById("suggestions");

const siteHeader = document.getElementById("site-header");
const navLinks = document.getElementById("nav-links");
const hamburger = document.getElementById("hamburger");

// Hero tagline: keep it crisp and consistent (UI copy), independent from the longer resume summary.
const HERO_TAGLINE =
  "I turn emerging AI capabilities into products, workflows, and systems people actually use.";

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

// ===== Paper resume ("the old way") =====
// The drawer renders the same /api/resume payload the agent answers from,
// but as a single typewritten sheet. Citations from chat answers open the
// drawer and drag a highlighter mark across the cited part of the page.

const drawerState = { open: false, lastFocus: null };

function paperLink(href, text) {
  const url = safeExternalUrl(href);
  if (!url) return el("strong", { text });
  return el("a", {
    class: "paper-link",
    href: url,
    target: "_blank",
    rel: "noopener noreferrer",
    text,
  });
}

function paperSection(id, title, children) {
  return el("section", { id, class: "paper-section" }, [
    el("h3", { class: "paper-heading paper-markable", text: title }),
    ...children,
  ]);
}

function renderResumePaper(data) {
  if (!resumePaper) return;
  resumePaper.innerHTML = "";

  const personal = data.personal || {};

  const contact = el("p", { class: "paper-contact" });
  const contactBits = [];
  if (personal.location) contactBits.push(el("span", { text: personal.location }));
  if (personal.email) {
    contactBits.push(
      el("a", { class: "paper-link", href: `mailto:${personal.email}`, text: personal.email })
    );
  }
  if (personal.linkedin) contactBits.push(paperLink(personal.linkedin, "LinkedIn"));
  if (personal.github) contactBits.push(paperLink(personal.github, "GitHub"));
  contactBits.forEach((bit, i) => {
    if (i) contact.append(" \u00B7 ");
    contact.append(bit);
  });

  resumePaper.append(
    el("header", { class: "paper-head" }, [
      el("h2", { class: "paper-name", text: personal.name || "" }),
      personal.title ? el("p", { class: "paper-title", text: personal.title }) : null,
      contactBits.length ? contact : null,
    ])
  );

  if (personal.summary) {
    resumePaper.append(el("p", { class: "paper-summary", text: personal.summary }));
  }

  const expEntries = safeArray(data.experience).map((exp) => {
    const head = el("div", { class: "paper-entry-head" }, [
      el("span", { class: "paper-entry-role", text: exp.role || "" }),
      exp.duration ? el("span", { class: "paper-entry-meta", text: exp.duration }) : null,
    ]);
    const subText = [exp.company, exp.location].filter(Boolean).join(" \u2014 ");
    const sub = subText ? el("div", { class: "paper-entry-sub", text: subText }) : null;
    const achievements = safeArray(exp.achievements);
    const bullets = achievements.length
      ? el("ul", { class: "paper-bullets" }, achievements.map((a) => el("li", { text: a })))
      : null;
    return el("div", { class: "paper-entry" }, [head, sub, bullets]);
  });
  resumePaper.append(paperSection("paper-experience", "Experience", expEntries));

  const eduEntries = safeArray(data.education).map((ed) => {
    const head = el("div", { class: "paper-entry-head" }, [
      el("span", { class: "paper-entry-role", text: ed.school || "" }),
      ed.graduation ? el("span", { class: "paper-entry-meta", text: ed.graduation }) : null,
    ]);
    const sub = ed.degree ? el("div", { class: "paper-entry-sub", text: ed.degree }) : null;
    return el("div", { class: "paper-entry" }, [head, sub]);
  });
  resumePaper.append(paperSection("paper-education", "Education", eduEntries));

  const certEntries = safeArray(data.certifications).map((c) => {
    const name = c.name || "";
    const li = el("li", {
      id: buildResumeAnchor("paper-certification", name),
      class: "paper-markable",
    });
    li.append(c.credential_url ? paperLink(c.credential_url, name) : el("strong", { text: name }));
    // Match the old cards: only PCAP shows its date.
    const showDate = /PCAP/i.test(name) || /Certified Associate Python Programmer/i.test(name);
    const extras = [c.issuer, showDate ? c.date : null].filter(Boolean).join(", ");
    if (extras) li.append(` \u2014 ${extras}`);
    const status = String(c.status || "").trim();
    if (status && status.toLowerCase() !== "completed") li.append(` (${status.toLowerCase()})`);
    return li;
  });
  resumePaper.append(
    paperSection("paper-certifications", "Certifications", [
      el("ul", { class: "paper-bullets paper-bullets--certs" }, certEntries),
    ])
  );

  const skillLines = Object.entries(data.skills || {}).map(([key, items]) => {
    const line = el("p", { class: "paper-skill-line" });
    line.append(el("strong", { text: `${key.replace(/_/g, " ").toUpperCase()}: ` }));
    line.append(safeArray(items).join(", "));
    return line;
  });
  resumePaper.append(paperSection("paper-skills", "Skills", skillLines));

  resumePaper.append(
    el("p", {
      class: "paper-signoff",
      text: "\u2014 typed the old-fashioned way. the agent upstairs is faster. \u2014",
    })
  );
}

function clearPaperMarks() {
  resumePaper?.querySelectorAll(".is-marked").forEach((n) => n.classList.remove("is-marked"));
}

function drawerFocusables() {
  const panel = resumeDrawer?.querySelector(".resume-drawer-panel");
  if (!panel) return [];
  return Array.from(
    panel.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")
  ).filter((n) => n.offsetParent !== null);
}

function openResumeDrawer() {
  if (!resumeDrawer || drawerState.open) return;
  drawerState.open = true;
  drawerState.lastFocus = document.activeElement;
  resumeDrawer.classList.add("is-open");
  resumeDrawer.setAttribute("aria-hidden", "false");
  resumeTab?.setAttribute("aria-expanded", "true");
  document.body.classList.add("resume-drawer-open");
  document.getElementById("resume-drawer-close")?.focus({ preventScroll: true });
}

function closeResumeDrawer() {
  if (!resumeDrawer || !drawerState.open) return;
  drawerState.open = false;
  resumeDrawer.classList.remove("is-open");
  resumeDrawer.setAttribute("aria-hidden", "true");
  resumeTab?.setAttribute("aria-expanded", "false");
  document.body.classList.remove("resume-drawer-open");
  clearPaperMarks();
  if (drawerState.lastFocus instanceof HTMLElement) {
    drawerState.lastFocus.focus({ preventScroll: true });
  }
  drawerState.lastFocus = null;
}

function initResumeDrawer() {
  if (!resumeDrawer) return;
  resumeTab?.addEventListener("click", () => {
    drawerState.open ? closeResumeDrawer() : openResumeDrawer();
  });
  document.getElementById("resume-drawer-close")?.addEventListener("click", closeResumeDrawer);
  resumeDrawer.querySelector("[data-drawer-close]")?.addEventListener("click", closeResumeDrawer);
  document.addEventListener("keydown", (e) => {
    if (!drawerState.open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      closeResumeDrawer();
      return;
    }
    // Minimal focus trap: keep Tab inside the dialog.
    if (e.key === "Tab") {
      const focusables = drawerFocusables();
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });
}

const CITATION_RULES = [
  {
    label: "Experience",
    targetId: "paper-experience",
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
    targetId: "paper-certification-pcap-certified-associate-python-programmer",
    patterns: [
      /\bpcap\b/i,
      /certified associate python programmer/i,
      /python institute/i,
    ],
  },
  {
    label: "AI Product Management",
    targetId: "paper-certification-ai-product-management",
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
    targetId: "paper-certification-finance-certification",
    patterns: [/finance certification/i],
  },
  {
    label: "Education",
    targetId: "paper-education",
    sourceTitles: ["Education"],
    patterns: [/\bmba\b/i, /washington state university/i],
  },
  {
    label: "Certifications",
    targetId: "paper-certifications",
    sourceTitles: ["Certifications"],
  },
  {
    label: "Skills",
    targetId: "paper-skills",
    sourceTitles: ["Skills and Expertise"],
  },
];

/**
 * Citation click: slide the paper out and run a highlighter across the cited
 * part of the sheet. Whole sections get their heading marked; specific lines
 * (individual certifications) get marked directly.
 */
function highlightCitationTarget(targetId) {
  const target = document.getElementById(targetId);
  if (!target) return;
  const mark = target.classList.contains("paper-section")
    ? target.querySelector(".paper-markable") || target
    : target;
  const wasOpen = drawerState.open;
  openResumeDrawer();
  // Let the slide-in transition land before scrolling the sheet.
  window.setTimeout(() => {
    clearPaperMarks();
    // Scroll to the mark, not the section: a whole section centered can push
    // its own marked heading off-screen.
    mark.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
    void mark.offsetWidth;
    mark.classList.add("is-marked");
  }, wasOpen ? 60 : 420);
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
      highlightCitationTarget(citation.targetId);
    });
    list.append(button);
  });

  return el("div", { class: "answer-citations" }, [
    el("span", { class: "answer-citations-label", text: "Sources" }),
    list,
  ]);
}

/**
 * Scroll to the chat card and focus the input. The hero CTAs, the interface
 * cards, and the project cards all funnel here; jdMode swaps the placeholder
 * to cue a JD paste (the fit analysis lives inside the chat thread).
 */
function focusChat({ jdMode = false } = {}) {
  document.getElementById("chat")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  if (jdMode && chatInput) {
    chatInput.placeholder = "Paste the full job description here...";
  }
  // Retry focus until the input is visible and focused
  let attempts = 0;
  const tryFocus = () => {
    if (chatInput) {
      chatInput.focus({ preventScroll: true });
      if (document.activeElement === chatInput || attempts > 10) return;
    }
    attempts++;
    setTimeout(tryFocus, 150);
  };
  setTimeout(tryFocus, 300);
}

/** Scroll to the chat, then send a prepared question (project card actions). */
function askAssistant(question) {
  document.getElementById("chat")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  window.setTimeout(() => sendMessage(question), 350);
}

// Hero CTA — scroll to chat and focus input
document.getElementById("hero-cta")?.addEventListener("click", (e) => {
  e.preventDefault();
  focusChat();
});

// Hero CTA — the fit analysis lives in the chat agent: jump there and cue
// the recruiter to paste the JD.
document.getElementById("hero-jd-cta")?.addEventListener("click", (e) => {
  e.preventDefault();
  focusChat({ jdMode: true });
});

// Hero CTA — slide out the paper resume ("the old way").
document.getElementById("hero-resume-cta")?.addEventListener("click", (e) => {
  e.preventDefault();
  openResumeDrawer();
});

// Nav "Resume" link opens the same drawer.
document.getElementById("nav-resume")?.addEventListener("click", (e) => {
  e.preventDefault();
  openResumeDrawer();
});

// "Explore my work your way" cards reuse the same three actions; the MCP
// card is a plain in-page anchor and needs no JS.
document.querySelectorAll("[data-explore]").forEach((cardEl) => {
  cardEl.addEventListener("click", () => {
    const mode = cardEl.dataset.explore;
    if (mode === "chat") focusChat();
    else if (mode === "jd") focusChat({ jdMode: true });
    else if (mode === "resume") openResumeDrawer();
  });
});

// MCP endpoint copy button.
const mcpCopyBtn = document.getElementById("mcp-copy");
if (mcpCopyBtn) {
  mcpCopyBtn.addEventListener("click", async () => {
    const url = document.getElementById("mcp-endpoint")?.textContent?.trim() || "";
    try {
      await copyToClipboard(url);
      mcpCopyBtn.textContent = "Copied";
      mcpCopyBtn.classList.add("is-copied");
      setTimeout(() => {
        mcpCopyBtn.textContent = "Copy";
        mcpCopyBtn.classList.remove("is-copied");
      }, 2000);
    } catch {
      mcpCopyBtn.textContent = "Press Ctrl+C";
    }
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

// ===== "Things I've built" project cards =====
// Display copy is tightened for the homepage (problem → built → why it
// matters), but every card is keyed to a project in the /api/resume payload
// and only renders when that project exists — cards can't outlive or drift
// from the source data. Claims stay within what resume.json states.
const PROJECT_CARDS = [
  {
    match: "Resume Assistant",
    title: "AI Resume",
    blurb:
      "Static resumes can't answer questions. This site is the alternative: a resume you can interview — conversational answers, JD fit analysis, and structured data for AI agents, all from one source of truth.",
    tags: ["RAG", "hybrid retrieval", "model routing", "evals", "MCP", "FastAPI"],
    link: "./how-it-works.html",
    actionLabel: "See how it's built",
  },
  {
    match: "Ben AI",
    title: "Ben AI",
    blurb:
      "Financial advisors were spending 30+ minutes researching benchmark eligibility. Ben AI answers those queries in seconds — a personal proof-of-concept I brought to Parametric and scaled into a production assistant.",
    tags: ["GPT-4o", "RAG", "Pinecone", "function calling", "FastAPI"],
    ask: "Tell me about Ben AI",
    actionLabel: "Ask my AI about it",
  },
  {
    match: "SQL Analytics Framework",
    title: "SQL Analytics Framework",
    blurb:
      "Roadmap debates ran on opinion. SQL reporting and heatmaps surfaced how features were actually used — lifting utilization 20% and putting data behind prioritization.",
    tags: ["SQL", "product analytics"],
    ask: "Tell me about Dakota's SQL analytics framework",
    actionLabel: "Ask my AI about it",
  },
  {
    match: "Python Self-Service Tool",
    title: "C-Suite Self-Service Tool",
    blurb:
      "Executives had no self-serve view of key business metrics. A working Python prototype made the digital-service concept concrete — and won the buy-in to keep going.",
    tags: ["Python", "automation", "data visualization"],
    ask: "Tell me about the Python self-service tool Dakota built for executives",
    actionLabel: "Ask my AI about it",
  },
];

function renderProjectCards(data) {
  const grid = document.getElementById("project-grid");
  const section = document.getElementById("projects");
  if (!grid || !section) return;

  const projects = safeArray(data.projects);
  const cards = PROJECT_CARDS.filter((card) =>
    projects.some((p) => String(p.name || "").startsWith(card.match))
  );
  if (!cards.length) return; // section stays hidden

  grid.innerHTML = "";
  cards.forEach((card) => {
    let action = null;
    if (card.link) {
      action = el("a", { class: "home-link", href: card.link, text: `${card.actionLabel} →` });
    } else if (card.ask) {
      action = el("button", { class: "home-link", type: "button", text: `${card.actionLabel} →` });
      action.addEventListener("click", () => askAssistant(card.ask));
    }
    grid.append(
      el("article", { class: "project-card" }, [
        el("h3", { class: "project-title", text: card.title }),
        el("p", { class: "project-blurb", text: card.blurb }),
        el(
          "div",
          { class: "project-tags" },
          card.tags.map((t) => el("span", { class: "project-tag", text: t }))
        ),
        action ? el("div", { class: "project-action" }, [action]) : null,
      ])
    );
  });
  section.hidden = false;
}

async function loadAndRenderResume() {
  try {
    const res = await fetch("/api/resume");
    if (!res.ok) throw new Error(`Resume fetch failed: ${res.status}`);
    const data = await res.json();

    const personal = data.personal || {};
    const name = (personal.name || "").trim();
    const email = (personal.email || "").trim();
    if (brandTitle && name) brandTitle.textContent = name.toUpperCase();
    if (heroName && name) heroName.textContent = name;
    if (heroTagline) heroTagline.textContent = HERO_TAGLINE;
    if (heroEmail && email) {
      const t = heroEmail.querySelector(".hero-contact-text");
      if (t) t.textContent = email;
    }
    if (heroLocation && personal.location) {
      const t = heroLocation.querySelector(".hero-contact-text");
      if (t) t.textContent = personal.location;
    }

    renderResumePaper(data);
    renderProjectCards(data);
  } catch (err) {
    console.warn("Resume data unavailable (did you start the backend?)", err);
    // No sheet to show: hide the drawer tab so it never opens onto blank paper.
    resumeTab?.setAttribute("hidden", "");
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
function createStatusSteps(container, orbState = "working") {
  container.innerHTML = "";
  container.classList.add("has-steps");
  // One live status row — active orb + a single line that updates in
  // place — rather than a stacked checklist. The orb is removed on
  // collapse; motion means "working right now".
  const live = document.createElement("div");
  live.className = "status-live";
  const orb = window.createThinkingOrb?.(orbState, 20) ?? null;
  if (orb) {
    orb.classList.add("thinking-orb");
    live.appendChild(orb);
  }
  const announcer = document.getElementById("step-announcer");
  const prefersReduced =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MIN_STEP_INTERVAL_MS = 350;

  const stepsWrap = document.createElement("div");
  stepsWrap.className = "status-steps";
  live.appendChild(stepsWrap);
  container.appendChild(live);
  // Every stage is kept for the post-answer disclosure dropdown.
  const history = [];

  const queue = [];
  const stepEls = [];
  let lastRenderAt = 0;
  let timer = null;
  let flushed = false;

  function renderStep({ text, items, announce }) {
    if (!stepsWrap.isConnected) return;
    // Single live line: each stage replaces the previous one. Item lists
    // are not shown live — they surface in the post-answer disclosure.
    stepEls.forEach((el) => el.remove());
    stepEls.length = 0;
    const step = document.createElement("div");
    step.className = "status-step";
    step.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.className = "step-label";
    label.textContent = text;
    step.appendChild(label);
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
      history.push({ text, items });
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
    /**
     * Replace the live line with a collapsed disclosure (called on done):
     * a one-line summary the reader can expand to review every stage and
     * the retrieval sources.
     */
    collapse(summaryText, sourceItems) {
      this.flush();
      orb?.remove();
      if (!stepsWrap.isConnected) return;
      stepEls.forEach((step) => step.remove());
      stepEls.length = 0;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      const details = document.createElement("details");
      details.className = "status-details";
      const summary = document.createElement("summary");
      summary.textContent = summaryText;
      details.appendChild(summary);
      const body = document.createElement("div");
      body.className = "status-details-body";
      history.forEach((entry) => {
        const line = document.createElement("div");
        line.className = "status-history-line";
        line.textContent = entry.text;
        body.appendChild(line);
      });
      if (sourceItems && sourceItems.length) {
        const list = document.createElement("ul");
        list.className = "step-items";
        sourceItems.slice(0, 4).forEach((item) => {
          const li = document.createElement("li");
          li.textContent = item;
          list.appendChild(li);
        });
        body.appendChild(list);
      }
      details.appendChild(body);
      stepsWrap.appendChild(details);
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
          // JD analyses draw from their own budget, so this works even
          // when the chat quota is exhausted — paste the JD right here.
          if (chatInput) {
            chatInput.placeholder = "Paste the full job description here...";
            chatInput.focus({ preventScroll: true });
          }
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
        action: () => openResumeDrawer(),
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
function renderUnlockForm(thinkingEl, detail, message, onUnlocked) {
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
        if (onUnlocked) {
          onUnlocked();
          return;
        }
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

  const steps = thinkingBody ? createStatusSteps(thinkingBody, "searching") : null;
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

// --- JD fit analysis (runs inside the chat thread) ---
const JD_MAX_CHARS = 15000;

let jdBusy = false;
let jdAnalysisMarkdown = ""; // raw markdown of the last completed analysis
let jdLastText = ""; // first line of the last analyzed JD feeds the email subject

function announceJD(text) {
  const announcer = document.getElementById("step-announcer");
  if (announcer) announcer.textContent = text;
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
      announceJD(announceText);
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
    jdLastText
      .split("\n")
      .map((l) => l.trim())
      .find(Boolean) || "your role";
  const subject = `Re: ${roleLine.slice(0, 60)} — fit analysis from your site`;
  return `mailto:${getContactEmail()}?subject=${encodeURIComponent(subject)}`;
}

function renderJDActions(host) {
  // Only the latest analysis carries live actions — older ones would act
  // on the wrong (current) session state.
  chatLog?.querySelectorAll(".jd-actions:not(.jd-actions--brief)").forEach((n) => n.remove());
  const analysisMarkdown = jdAnalysisMarkdown;

  const briefBtn = el("button", {
    class: "chip chip--primary jd-brief-btn",
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
    makeCopyButton("Copy summary", () => extractRecruiterSummary(analysisMarkdown), "Recruiter summary copied"),
    briefBtn,
    emailLink,
  ]);
  host.append(actions);
}

async function sendJDMatch(jdText, { mode = "analysis" } = {}) {
  if (jdBusy) return;
  jdBusy = true;
  if (mode === "analysis") jdLastText = jdText;

  // The analysis streams into a regular bot message so the whole flow
  // lives in the conversation.
  const msg = addMessage("", "bot");
  msg.classList.add("jd-analysis");
  const msgBody = msg.querySelector(".msg-body");
  if (mode === "analysis") {
    msgBody.append(el("h3", { class: "jd-results-heading", text: "Fit analysis" }));
  }
  const streamHost = el("div", {
    class: mode === "analysis" ? "jd-stream" : "jd-stream jd-stream--brief",
  });
  msgBody.append(streamHost);

  const steps = createStatusSteps(streamHost, "solving");
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
      requestScrollToBottom();
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
      // Free-limit wall: show the actual password form right here instead
      // of a dead-end message, and retry this analysis once unlocked.
      if (result.res && result.res.status === 403) {
        const host = el("div", { class: "jd-unlock" }, [el("div", { class: "msg-body" })]);
        streamHost.append(host);
        renderUnlockForm(host, detail, null, () => sendJDMatch(jdText, { mode }));
        announceJD("Password required for another analysis.");
        return;
      }
      streamHost.append(
        el("p", { class: "jd-error", text: detail || "Something went wrong. Please try again." })
      );
      announceJD("The analysis could not be completed.");
      return;
    }

    ensureAnswerDiv();
    answerDiv.innerHTML = parseMarkdown(finalData.reply ?? "");
    answerDiv.style.minHeight = "";
    steps.collapse(mode === "brief" ? "Screening brief ready" : "Analysis complete");
    decorateJDResults(answerDiv);

    if (mode === "analysis") {
      jdAnalysisMarkdown = String(finalData.reply || "");
      renderJDActions(msgBody);
      announceJD("Fit analysis ready.");
    } else {
      const briefMarkdown = String(finalData.reply || "");
      streamHost.append(
        el("div", { class: "jd-actions jd-actions--brief" }, [
          makeCopyButton("Copy brief", () => briefMarkdown, "Screening brief copied"),
        ])
      );
      announceJD("Screening brief ready.");
    }
    requestScrollToBottom();
  } catch (err) {
    console.error(err);
    steps.flush();
    streamHost.append(
      el("p", { class: "jd-error", text: "Something went wrong. Please try again." })
    );
  } finally {
    jdBusy = false;
  }
}

/** Chat interstitial when a pasted message looks like a job description. */
function renderJDInterstitial(text) {
  suggestionsEl?.remove();
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

// --- Resume PDF download (password-gated; unlocked with the chat password) ---

function clearPdfChatHelpers() {
  suggestionsEl?.remove();
  chatLog?.querySelector(".msg.intro")?.remove();
  removePreviousFollowups();
  autoScrollEnabled = true;
}

async function downloadResumePdf() {
  const btn = document.getElementById("pdf-download");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/resume.pdf", { credentials: "same-origin" });
    if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = el("a", { href: url, download: "Dakota-Radigan-Resume.pdf" });
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return;
    }
    let detail = "Unable to download the PDF right now.";
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {
      /* non-JSON error body */
    }

    // The starter helpers float over the bottom of the chat card. Once the
    // PDF flow needs the chat, clear them so its status and unlock form stay
    // visible—especially on narrow screens.
    clearPdfChatHelpers();

    // 403 = locked: reuse the chat unlock form inside a bot message, then
    // retry the download once the password is accepted.
    const host = addMessage(detail, "bot");
    if (res.status === 403) {
      renderUnlockForm(host, detail, null, () => downloadResumePdf());
    }
    requestScrollToBottom();
    (host.querySelector(".unlock-form") || host).scrollIntoView({
      behavior: scrollBehavior(),
      block: "center",
    });
  } catch (err) {
    console.error("PDF download failed", err);
    clearPdfChatHelpers();
    const host = addMessage("Unable to download the PDF right now. Please try again soon.", "bot");
    requestScrollToBottom();
    host.scrollIntoView({ behavior: scrollBehavior(), block: "center" });
  } finally {
    if (btn) btn.disabled = false;
  }
}

document.getElementById("pdf-download")?.addEventListener("click", downloadResumePdf);

// Paper resume drawer: tab, close button, backdrop, Escape, focus trap.
initResumeDrawer();

// Render the typewritten paper resume from /api/resume.
loadAndRenderResume();
