const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chips = document.querySelectorAll(".chip");
const sendButton = chatForm.querySelector("button");

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

function setSending(isSending) {
  chatInput.disabled = isSending;
  if (sendButton) {
    sendButton.disabled = isSending;
  }
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

chips.forEach((chip) => {
  chip.addEventListener("click", () => {
    chatInput.value = chip.dataset.prompt;
    chatInput.focus();
  });
});

// Seed a friendly greeting.
addMessage("Hi! Ask about Dakota's experience, projects, or skills.", "bot");

