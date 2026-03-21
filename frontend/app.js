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

const sessionId =
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;

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
      chatSection?.scrollIntoView({ behavior: "smooth", block: "start" });
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
    const row = el("div", { class: "resume-card-title-row" }, [
      el("div", { class: "resume-card-title", text: ed.school || "" }),
      el("div", { class: "resume-card-meta", text: ed.graduation || "" }),
    ]);
    const subtitle = el("div", { class: "resume-card-subtitle", text: ed.degree || "" });
    educationGrid.append(el("article", { class: "resume-card reveal" }, [row, subtitle]));
  });
}

function renderCertifications(items) {
  if (!certificationsGrid) return;
  certificationsGrid.innerHTML = "";
  safeArray(items).forEach((c, idx) => {
    const name = c.name || "";
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
    const delayClass = idx <= 4 ? ` reveal-delay-${Math.min(idx + 1, 4)}` : "";
    certificationsGrid.append(
      el("article", { class: `resume-card reveal${delayClass}` }, [row, subtitle, status])
    );
  });
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

function getThinkingMarkup(label = "Thinking") {
  return `
    <span class="thinking-label">${label}</span>
    <span class="thinking-dots" aria-hidden="true">
      <span class="thinking-dot"></span>
      <span class="thinking-dot"></span>
      <span class="thinking-dot"></span>
    </span>
  `;
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
 * Start showing status steps in the thinking bubble while the fetch is in progress.
 * Returns a controller object so sendMessage can finalize/update steps when the response arrives.
 */
function startStatusSteps(container, message) {
  container.innerHTML = "";
  container.classList.add("has-steps");
  const announcer = document.getElementById("step-announcer");
  const stepEls = [];
  const topic = extractQueryTopic(message);

  function addStep(text) {
    if (!container.isConnected) return null;
    const step = document.createElement("div");
    step.className = "status-step";
    step.setAttribute("aria-hidden", "true");
    const icon = document.createElement("span");
    icon.className = "step-icon";
    icon.textContent = "\u2713";
    step.appendChild(icon);
    const content = document.createElement("div");
    content.className = "step-content";
    const label = document.createElement("span");
    label.className = "step-label";
    label.textContent = text;
    content.appendChild(label);
    step.appendChild(content);
    container.appendChild(step);
    requestAnimationFrame(() => step.classList.add("is-visible"));
    if (announcer) announcer.textContent = text;
    stepEls.push(step);
    return step;
  }

  // Step 1 — reference the user's topic if we can extract one
  const step1Text = topic
    ? `Searching for "${topic}"...`
    : "Searching resume data...";
  addStep(step1Text);

  // Step 2 appears after 800ms — generic until response arrives with real data
  const step2Timer = setTimeout(() => addStep("Matching relevant experience..."), 800);
  // Step 3 appears after 1800ms
  const step3Timer = setTimeout(() => addStep("Composing answer..."), 1800);

  return {
    /** Call when response arrives to update step 2 with real source data and finalize. */
    finalize(data) {
      clearTimeout(step2Timer);
      clearTimeout(step3Timer);

      // Ensure step 2 exists with real data
      if (stepEls.length < 2) {
        // Step 2 hasn't appeared yet — add it with real data
        const text = (data.used_rag && data.sources?.length)
          ? `Found ${data.sources.length} relevant section${data.sources.length > 1 ? "s" : ""}`
          : data.used_rag ? "Using full resume context..." : "Found relevant sections";
        const step2 = addStep(text);
        if (step2 && data.used_rag && data.sources?.length) {
          const contentDiv = step2.querySelector(".step-content");
          if (contentDiv) {
            const list = document.createElement("ul");
            list.className = "step-items";
            data.sources.forEach((title) => {
              const li = document.createElement("li");
              li.textContent = title;
              list.appendChild(li);
            });
            contentDiv.appendChild(list);
          }
        }
      } else if (data.used_rag && data.sources?.length) {
        // Step 2 already visible — update its text and add source titles
        const step2 = stepEls[1];
        const label = step2.querySelector(".step-label");
        if (label) label.textContent = `Found ${data.sources.length} relevant section${data.sources.length > 1 ? "s" : ""}`;
        const contentDiv = step2.querySelector(".step-content");
        if (contentDiv) {
          const list = document.createElement("ul");
          list.className = "step-items";
          data.sources.forEach((title) => {
            const li = document.createElement("li");
            li.textContent = title;
            list.appendChild(li);
          });
          contentDiv.appendChild(list);
        }
      }

      // Ensure step 3 exists
      if (stepEls.length < 3) addStep("Generating response...");
    },

    /** Cancel timers on error. */
    cancel() {
      clearTimeout(step2Timer);
      clearTimeout(step3Timer);
    },
  };
}

async function sendMessage(message, { isRetry = false } = {}) {
  suggestionsEl?.remove();
  if (!isRetry) addMessage(message, "user");
  const thinkingEl = addMessage("Thinking...", "bot");
  const thinkingBody = thinkingEl.querySelector(".msg-body");
  if (thinkingBody) {
    thinkingEl.classList.add("is-thinking");
    thinkingBody.innerHTML = getThinkingMarkup("Thinking");
  }
  setSending(true);

  // Start status steps animation in parallel with the fetch
  let stepCtrl = null;
  if (thinkingBody) {
    stepCtrl = startStatusSteps(thinkingBody, message);
  }

  try {
    const fetchStart = Date.now();
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });

    if (!res.ok) {
      stepCtrl?.cancel();
      // Ensure "Thinking..." shows for at least 1.5s on error paths
      const elapsed = Date.now() - fetchStart;
      const MIN_THINKING_MS = 1500;
      if (elapsed < MIN_THINKING_MS) {
        await new Promise((r) => setTimeout(r, MIN_THINKING_MS - elapsed));
      }
      // Handle chat limit (403)
      if (res.status === 403) {
        const errorData = await res.json().catch(() => ({}));
        const body = thinkingEl.querySelector(".msg-body");
        if (body) {
          thinkingEl.classList.remove("is-thinking");
          body.textContent = "";

          const prompt = el("p", { class: "unlock-prompt", text: errorData.detail || "You've hit the free chat limit." });
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
                body: JSON.stringify({ password, session_id: sessionId }),
              });

              const unlockData = await unlockRes.json();

              if (unlockData.success) {
                thinkingEl.remove();
                setTimeout(() => sendMessage(message, { isRetry: true }), 0);
                return;
              } else {
                errorEl.textContent = unlockData.message || "Incorrect password.";
                errorEl.style.display = "block";
                passwordInput.focus();
              }
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
        requestScrollToBottom();
        return;
      }

      // Show API error message for any non-OK response
      const errorData = await res.json().catch(() => ({}));
      const body = thinkingEl.querySelector(".msg-body");
      if (body) {
        thinkingEl.classList.remove("is-thinking");
        body.textContent = errorData.detail || "Sorry, something went wrong. Please try again.";
      }
      requestScrollToBottom();
      return;
    }

    const data = await res.json();
    const body = thinkingEl.querySelector(".msg-body");
    if (body) {
      // Ensure steps have time to animate before showing the answer
      const MIN_STEPS_MS = 2400;
      const elapsed = Date.now() - fetchStart;
      if (elapsed < MIN_STEPS_MS) {
        await new Promise((r) => setTimeout(r, MIN_STEPS_MS - elapsed));
      }
      stepCtrl?.finalize(data);
      // Brief pause after finalize so the updated step 2 is visible
      await new Promise((r) => setTimeout(r, 400));
      thinkingEl.classList.remove("is-thinking");
      // Append the answer below the steps
      const answerDiv = document.createElement("div");
      answerDiv.className = "step-answer";
      answerDiv.innerHTML = parseMarkdown(data.reply ?? "No response received.");
      body.appendChild(answerDiv);
    }

    // Show feedback UI on first successful response
    if (!firstResponseFeedbackShown) {
      firstResponseFeedbackShown = true;
      addFeedbackUI(thinkingEl, "first_response");
    }

    requestScrollToBottom();
  } catch (err) {
    stepCtrl?.cancel();
    const body = thinkingEl.querySelector(".msg-body");
    if (body) {
      thinkingEl.classList.remove("is-thinking");
      body.textContent = "Sorry, something went wrong. Please try again.";
    }
    requestScrollToBottom();
    console.error(err);
  } finally {
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

// Render resume details below chat (Experience / Skills / Education).
loadAndRenderResume();
