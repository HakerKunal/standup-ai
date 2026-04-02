const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? "http://localhost:8000"
  : "";

const EXAMPLES = {
  daily: `worked on PDEV-21730 date filter
qa deployment failing for PDEV-21725
added future date validation
reviewed dan comments
starting new ticket tomorrow`,

  blocker: `finished auth refactor PR #342
blocked on backend API change - waiting for alex
wrote unit tests for login flow
design review with sarah went well
need infra team to unblock DB migration before EOD`,

  weekly: `monday - PDEV-21730 date filter implementation
tuesday - PR review with team, fixed edge cases
wednesday - QA testing, found 3 bugs fixed 2
thursday - PDEV-21725 deployment issues
friday - addressed all review comments, merged to main
next week: starting PDEV-21800 notification system`,

  sprint: `PDEV-100 user auth complete
PDEV-101 dashboard 80% done, blocked on API
PDEV-102 email notifications done and deployed
PDEV-103 in progress, needs design sign-off
PDEV-104 not started, moved to next sprint
3 bugs fixed, 1 critical still open
demo ready for friday`,
};

// ── State ───────────────────────────────────────────────
let selectedFormat = "professional";
let isGenerating = false;

// ── Elements ────────────────────────────────────────────
const notesEl      = document.getElementById("notes");
const extraCtxEl   = document.getElementById("extra-context");
const generateBtn  = document.getElementById("generate-btn");
const btnText      = document.getElementById("btn-text");
const outputArea   = document.getElementById("output-area");
const outputText   = document.getElementById("output-text");
const emptyState   = document.getElementById("empty-state");
const copyBtn      = document.getElementById("copy-btn");
const copyLabel    = document.getElementById("copy-label");
const statusBar    = document.getElementById("status-bar");
const statusMsg    = document.getElementById("status-msg");
const formatGrid   = document.getElementById("format-grid");

// ── Format selection ─────────────────────────────────────
formatGrid.addEventListener("click", (e) => {
  const btn = e.target.closest(".format-btn");
  if (!btn) return;
  document.querySelectorAll(".format-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  selectedFormat = btn.dataset.format;
});

// ── Example chips ────────────────────────────────────────
document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    const key = chip.dataset.example;
    if (EXAMPLES[key]) {
      notesEl.value = EXAMPLES[key];
      notesEl.focus();
    }
  });
});

// ── Generate ─────────────────────────────────────────────
generateBtn.addEventListener("click", generate);
notesEl.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") generate();
});

async function generate() {
  const notes = notesEl.value.trim();
  if (!notes) {
    notesEl.focus();
    notesEl.style.borderColor = "var(--error)";
    setTimeout(() => notesEl.style.borderColor = "", 1500);
    return;
  }
  if (isGenerating) return;

  isGenerating = true;
  setGenerating(true);
  showOutput("");

  try {
    const res = await fetch(`${API_BASE}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        notes,
        format: selectedFormat,
        extra_context: extraCtxEl.value.trim(),
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      showError(err.detail || "Server error");
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;

        let msg;
        try { msg = JSON.parse(raw); } catch { continue; }

        if (msg.type === "text") {
          appendOutput(msg.content);
        } else if (msg.type === "done") {
          finalizeOutput();
        } else if (msg.type === "error") {
          showError(msg.message);
        }
      }
    }
  } catch (err) {
    if (err.name === "TypeError" && err.message.includes("fetch")) {
      showError("Cannot reach backend. Make sure the FastAPI server is running on port 8000.");
    } else {
      showError(`Unexpected error: ${err.message}`);
    }
  } finally {
    isGenerating = false;
    setGenerating(false);
  }
}

// ── UI helpers ───────────────────────────────────────────
function setGenerating(on) {
  generateBtn.disabled = on;
  btnText.textContent = on ? "Generating..." : "Generate Standup";
  statusBar.classList.toggle("hidden", !on);
  if (on) statusMsg.textContent = "Grok is writing your standup...";
}

function showOutput(initial) {
  emptyState.classList.add("hidden");
  outputText.classList.remove("hidden", "error");
  outputText.classList.add("streaming");
  outputText.textContent = initial;
  copyBtn.classList.add("hidden");
}

function appendOutput(text) {
  outputText.textContent += text;
  outputArea.scrollTop = outputArea.scrollHeight;
}

function finalizeOutput() {
  outputText.classList.remove("streaming");
  statusBar.classList.add("hidden");
  if (outputText.textContent.trim()) {
    copyBtn.classList.remove("hidden");
  }
}

function showError(message) {
  emptyState.classList.add("hidden");
  outputText.classList.remove("hidden", "streaming");
  outputText.classList.add("error");
  outputText.textContent = `Error: ${message}`;
  statusBar.classList.add("hidden");
  copyBtn.classList.add("hidden");
}

// ── Copy ─────────────────────────────────────────────────
copyBtn.addEventListener("click", async () => {
  const text = outputText.textContent;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copyLabel.textContent = "✅ Copied!";
    setTimeout(() => { copyLabel.textContent = "📋 Copy"; }, 2000);
  } catch {
    copyLabel.textContent = "❌ Failed";
    setTimeout(() => { copyLabel.textContent = "📋 Copy"; }, 2000);
  }
});
