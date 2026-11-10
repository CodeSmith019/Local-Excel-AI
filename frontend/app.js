/**
 * Excel AI - Frontend Application
 * Plain JavaScript, no frameworks, no external dependencies.
 */

// --- Constants & State ---
const STORAGE_KEY = "excel_ai_chat_items";
const MAX_HISTORY = 30;
const HEALTH_POLL_INTERVAL_MS = 10000;

let isBusy = false;
let currentAbortController = null;

// --- DOM Element References ---
const chatLog = document.getElementById("chatLog");
const liveStatusContainer = document.getElementById("liveStatusContainer");
const promptInput = document.getElementById("promptInput");
const sendBtn = document.getElementById("sendBtn");
const chatForm = document.getElementById("chatForm");
const headerUndoBtn = document.getElementById("headerUndoBtn");
const modelStatus = document.getElementById("modelStatus");
const modelDot = document.getElementById("modelDot");
const excelStatus = document.getElementById("excelStatus");
const excelDot = document.getElementById("excelDot");

// --- Helper Utilities ---

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatTime(timestamp) {
  const d = timestamp ? new Date(timestamp) : new Date();
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    chatLog.scrollTop = chatLog.scrollHeight;
  });
}

function setBusy(busy) {
  isBusy = busy;
  promptInput.disabled = busy;
  sendBtn.disabled = busy;

  document.querySelectorAll(".chip").forEach((chip) => {
    chip.disabled = busy;
  });

  if (!busy) {
    liveStatusContainer.innerHTML = "";
    promptInput.focus();
  }
}

// --- Session Storage Management ---

function loadHistory() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    console.warn("Failed to load chat history from sessionStorage:", e);
    return [];
  }
}

function saveHistoryItem(item) {
  try {
    const history = loadHistory();
    history.push(item);
    const trimmed = history.slice(-MAX_HISTORY);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch (e) {
    console.warn("Failed to save chat item to sessionStorage:", e);
  }
}

function updateHistoryItem(id, updates) {
  try {
    const history = loadHistory();
    const idx = history.findIndex((h) => h.id === id);
    if (idx !== -1) {
      history[idx] = { ...history[idx], ...updates };
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    }
  } catch (e) {
    console.warn("Failed to update history item:", e);
  }
}

// --- Rendering Functions ---

function renderUserMessage(text, timestamp = Date.now()) {
  const div = document.createElement("div");
  div.className = "message-card message-user";
  div.innerHTML = `
    <div class="message-body">${escapeHtml(text)}</div>
    <div class="message-time" style="text-align: right; margin-top: 4px;">${formatTime(timestamp)}</div>
  `;
  chatLog.appendChild(div);
  scrollToBottom();
}

function renderAssistantMessage(text, timestamp = Date.now()) {
  const div = document.createElement("div");
  div.className = "message-card message-assistant";
  div.innerHTML = `
    <div class="message-header">
      <span class="assistant-name">Excel AI</span>
      <span class="message-time">${formatTime(timestamp)}</span>
    </div>
    <div class="message-body">${escapeHtml(text)}</div>
  `;
  chatLog.appendChild(div);
  scrollToBottom();
}

function updateLiveStatus(label) {
  liveStatusContainer.innerHTML = `
    <div class="working-indicator" role="status">
      <div class="spinner" aria-hidden="true"></div>
      <span class="working-text">${escapeHtml(label)}…</span>
    </div>
  `;
  scrollToBottom();
}

function clearLiveStatus() {
  liveStatusContainer.innerHTML = "";
}

function renderPlanCard(plan, timestamp = Date.now()) {
  const div = document.createElement("div");
  div.className = "plan-card";
  const paramsJson = plan.params ? JSON.stringify(plan.params, null, 2) : "{}";

  div.innerHTML = `
    <div class="plan-title-row">
      <span class="plan-badge">Plan</span>
      <span class="plan-title">${escapeHtml(plan.op_title || plan.op || "Operation")}</span>
    </div>
    <div class="plan-explanation">${escapeHtml(plan.explanation || "")}</div>
    <details class="plan-details">
      <summary>Details</summary>
      <pre><code>${escapeHtml(paramsJson)}</code></pre>
    </details>
  `;
  chatLog.appendChild(div);
  scrollToBottom();
}

function renderPreviewCard(preview, id = null, isHistoric = false, timestamp = Date.now()) {
  const itemId = id || "preview-" + Date.now() + "-" + Math.random().toString(36).substring(2, 7);
  const div = document.createElement("div");
  div.className = "preview-card";
  div.id = itemId;

  let warningsHtml = "";
  if (preview.warnings && preview.warnings.length > 0) {
    warningsHtml = `
      <div class="preview-warnings" role="alert">
        <strong>Warnings:</strong>
        ${preview.warnings.map((w) => `<div>• ${escapeHtml(w)}</div>`).join("")}
      </div>
    `;
  }

  // Row statistics for row operations
  let rowStatsHtml = "";
  const rowMatch = preview.summary && preview.summary.match(/\((\d+)\s*->\s*(\d+)\s*rows\)/i);
  if (rowMatch) {
    const rowsBefore = rowMatch[1];
    const rowsAfter = rowMatch[2];
    rowStatsHtml = `
      <div class="preview-row-stats">
        <span class="row-stats-badge">Rows:</span>
        <span class="row-stats-before">${escapeHtml(rowsBefore)}</span>
        <span class="row-stats-arrow">&rarr;</span>
        <span class="row-stats-after">${escapeHtml(rowsAfter)} rows</span>
      </div>
    `;
  }

  // Format changes swatches
  let formatsHtml = "";
  const formats = preview.formats || [];
  if (formats.length > 0) {
    const swatchesHtml = formats
      .map((fmt) => {
        const swatch = fmt.fill_hex
          ? `<span class="color-swatch" style="background-color: ${escapeHtml(fmt.fill_hex)};" title="${escapeHtml(fmt.fill_hex)}"></span><span class="color-hex">${escapeHtml(fmt.fill_hex)}</span>`
          : `<span class="color-swatch-clear">Clear fill</span>`;
        return `
          <div class="format-swatch-item">
            <span class="cell-addr">${escapeHtml(fmt.address)}</span>
            ${swatch}
          </div>
        `;
      })
      .join("");

    formatsHtml = `
      <div class="preview-formats-section">
        <div class="preview-section-title">Formatting (${formats.length} cell${formats.length === 1 ? "" : "s"})</div>
        <div class="format-swatches-grid">
          ${swatchesHtml}
        </div>
      </div>
    `;
  }

  // Build changes table
  let rowsHtml = "";
  const changes = preview.changes || [];
  const isFormulaOp = preview.op === "add_formula_column" || preview.op === "add_summary_formula" || (changes.length > 0 && changes.some((c) => Boolean(c.formula)));

  if (changes.length === 0) {
    rowsHtml = `<tr><td colspan="3" style="text-align: center; color: var(--text-muted); padding: 8px;">No cell changes</td></tr>`;
  } else if (isFormulaOp) {
    const maxDisplay = 10;
    const displayChanges = changes.slice(0, maxDisplay);
    for (const change of displayChanges) {
      let formulaHtml = "";
      if (change.formula) {
        formulaHtml = `<span class="formula-tag" title="Formula: ${escapeHtml(change.formula)}">${escapeHtml(change.formula)}</span>`;
      } else if (change.after !== null && change.after !== undefined && change.after !== "") {
        formulaHtml = escapeHtml(String(change.after));
      }

      let valDisplay = "";
      if (change.value !== null && change.value !== undefined && change.value !== "") {
        valDisplay = escapeHtml(String(change.value));
      } else if (!change.formula && change.after !== null && change.after !== undefined) {
        valDisplay = escapeHtml(String(change.after));
      } else {
        valDisplay = `<span style="color: var(--text-muted); font-style: italic;">(preview)</span>`;
      }

      rowsHtml += `
        <tr>
          <td class="cell-addr">${escapeHtml(change.address)}</td>
          <td class="cell-formula">${formulaHtml}</td>
          <td class="cell-after highlighted">${valDisplay}</td>
        </tr>
      `;
    }

    if (changes.length > maxDisplay) {
      const remaining = changes.length - maxDisplay;
      rowsHtml += `
        <tr>
          <td colspan="3" class="preview-more-rows">... ${remaining} more</td>
        </tr>
      `;
    }
  } else {
    for (const change of changes) {
      const beforeVal = change.before !== null && change.before !== undefined && change.before !== ""
        ? escapeHtml(String(change.before))
        : `<span style="color: var(--text-muted); font-style: italic;">(blank)</span>`;

      let afterVal = "";
      if (change.after !== null && change.after !== undefined && change.after !== "") {
        afterVal = escapeHtml(String(change.after));
      } else if (change.formula) {
        afterVal = escapeHtml(change.formula);
      } else {
        afterVal = `<span style="color: var(--text-muted); font-style: italic;">(blank)</span>`;
      }

      let formulaHtml = "";
      if (change.formula) {
        formulaHtml = `<span class="formula-tag" title="Formula: ${escapeHtml(change.formula)}">${escapeHtml(change.formula)}</span>`;
      }

      rowsHtml += `
        <tr>
          <td class="cell-addr">${escapeHtml(change.address)}</td>
          <td class="cell-before">${beforeVal}</td>
          <td class="cell-after highlighted">
            ${afterVal}
            ${formulaHtml}
          </td>
        </tr>
      `;
    }
  }

  let changesTableHtml = "";
  if (changes.length > 0 || formats.length === 0) {
    const tableHeaderHtml = isFormulaOp
      ? `
          <thead>
            <tr>
              <th style="width: 50px;">Cell</th>
              <th>Formula</th>
              <th>Value</th>
            </tr>
          </thead>
        `
      : `
          <thead>
            <tr>
              <th style="width: 50px;">Cell</th>
              <th>Before</th>
              <th>After</th>
            </tr>
          </thead>
        `;

    changesTableHtml = `
      <div class="preview-table-container">
        <table class="preview-table">
          ${tableHeaderHtml}
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      </div>
    `;
  }

  // Actions area
  let actionsHtml = "";
  if (isHistoric || preview.status === "applied") {
    actionsHtml = `<div class="preview-actions"><span class="action-status-badge badge-applied">Applied</span></div>`;
  } else if (isHistoric || preview.status === "cancelled") {
    actionsHtml = `<div class="preview-actions"><span class="action-status-badge badge-cancelled">Cancelled</span></div>`;
  } else {
    actionsHtml = `
      <div class="preview-actions" id="actions-${itemId}">
        <button type="button" class="btn btn-primary btn-apply" data-action="apply">Apply</button>
        <button type="button" class="btn btn-secondary btn-cancel" data-action="cancel">Cancel</button>
      </div>
    `;
  }

  div.innerHTML = `
    <div class="preview-header">
      <div class="preview-summary">${escapeHtml(preview.summary || "Proposed changes")}</div>
      <div class="message-time">${formatTime(timestamp)}</div>
    </div>
    ${warningsHtml}
    ${rowStatsHtml}
    ${changesTableHtml}
    ${formatsHtml}
    ${actionsHtml}
  `;

  chatLog.appendChild(div);
  scrollToBottom();

  // Attach button listeners if active (not historic)
  if (!isHistoric && !preview.status) {
    const applyBtn = div.querySelector('.btn-apply');
    const cancelBtn = div.querySelector('.btn-cancel');

    if (applyBtn && cancelBtn) {
      applyBtn.addEventListener("click", () => handleConfirm(itemId, preview.thread_id, true));
      cancelBtn.addEventListener("click", () => handleConfirm(itemId, preview.thread_id, false));
    }
  }

  return itemId;
}

function renderDoneMessage(done, timestamp = Date.now()) {
  const div = document.createElement("div");
  div.className = "message-done";

  if (done.applied) {
    div.innerHTML = `
      <div class="done-content">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 0 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"/>
        </svg>
        <span>${escapeHtml(done.summary || "Changes applied successfully.")}</span>
      </div>
      <button type="button" class="btn-link undo-inline-btn" title="Undo this change">Undo</button>
    `;
    const undoBtn = div.querySelector(".undo-inline-btn");
    if (undoBtn) {
      undoBtn.addEventListener("click", () => handleUndo());
    }
  } else {
    div.style.backgroundColor = "#f3f2f1";
    div.style.borderColor = "var(--border-default)";
    div.style.color = "var(--text-secondary)";
    div.innerHTML = `
      <div class="done-content">
        <span>${escapeHtml(done.summary || "Cancelled. No changes applied.")}</span>
      </div>
    `;
  }

  chatLog.appendChild(div);
  scrollToBottom();
}

function renderErrorMessage(message, timestamp = Date.now()) {
  const div = document.createElement("div");
  div.className = "message-error";
  div.innerHTML = `
    <div class="error-icon" aria-hidden="true">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1ZM7.25 4.5a.75.75 0 0 1 1.5 0v4a.75.75 0 0 1-1.5 0v-4ZM8 12a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"/>
      </svg>
    </div>
    <div class="error-body">${escapeHtml(message || "An unexpected error occurred.")}</div>
  `;
  chatLog.appendChild(div);
  scrollToBottom();
}

function renderUndoMessage(restored, summary, timestamp = Date.now()) {
  const div = document.createElement("div");
  div.className = "message-undo";
  if (restored) {
    div.innerHTML = `
      <span style="color: var(--excel-green); font-weight: bold;">↺</span>
      <span><strong>Undone:</strong> ${escapeHtml(summary || "Previous change restored.")}</span>
    `;
  } else {
    div.innerHTML = `
      <span>${escapeHtml(summary || "No changes to undo.")}</span>
    `;
  }
  chatLog.appendChild(div);
  scrollToBottom();
}

// --- Restore Past History on Page Load ---

function restoreHistory() {
  const history = loadHistory();
  if (history.length === 0) return;

  // Clear initial placeholder if history exists
  chatLog.innerHTML = "";

  for (const item of history) {
    switch (item.type) {
      case "user":
        renderUserMessage(item.data.text, item.timestamp);
        break;
      case "assistant":
        renderAssistantMessage(item.data.text, item.timestamp);
        break;
      case "plan":
        renderPlanCard(item.data, item.timestamp);
        break;
      case "preview":
        renderPreviewCard(item.data, item.id, true, item.timestamp);
        break;
      case "done":
        renderDoneMessage(item.data, item.timestamp);
        break;
      case "error":
        renderErrorMessage(item.data.message, item.timestamp);
        break;
      case "undo":
        renderUndoMessage(item.data.restored, item.data.summary, item.timestamp);
        break;
    }
  }
}

// --- SSE over POST Client ---

/**
 * postSSE: EventSource-like SSE streaming over HTTP POST.
 * Handles split chunks, multi-line data, custom event types, and connection errors.
 */
async function postSSE(url, body, onEvent, options = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "text/event-stream"
    },
    body: JSON.stringify(body),
    signal: options.signal
  });

  if (!response.ok) {
    let errorText = "";
    try {
      errorText = await response.text();
    } catch {
      errorText = response.statusText;
    }
    throw new Error(`Server returned ${response.status}: ${errorText || response.statusText}`);
  }

  if (!response.body) {
    throw new Error("ReadableStream not supported on response body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let currentEvent = "message";
  let dataLines = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      // The last element is the uncompleted tail of the split
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event:")) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        } else if (line === "") {
          // Empty line indicates end of an SSE message block
          if (dataLines.length > 0) {
            const rawData = dataLines.join("\n");
            let parsedData;
            try {
              parsedData = JSON.parse(rawData);
            } catch {
              parsedData = rawData;
            }
            onEvent({ event: currentEvent, data: parsedData });
            currentEvent = "message";
            dataLines = [];
          }
        }
      }
    }

    // Flush any remaining buffer if stream closed without trailing newline
    if (buffer.length > 0) {
      const lines = [buffer];
      for (const line of lines) {
        if (line.startsWith("event:")) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (dataLines.length > 0) {
        const rawData = dataLines.join("\n");
        let parsedData;
        try {
          parsedData = JSON.parse(rawData);
        } catch {
          parsedData = rawData;
        }
        onEvent({ event: currentEvent, data: parsedData });
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// --- Action Handlers ---

async function submitInstruction(instruction) {
  const text = (instruction || "").trim();
  if (!text || isBusy) return;

  promptInput.value = "";
  setBusy(true);

  // Render and persist user message
  const now = Date.now();
  renderUserMessage(text, now);
  saveHistoryItem({
    id: "user-" + now,
    type: "user",
    data: { text },
    timestamp: now
  });

  updateLiveStatus("Reading sheet");

  currentAbortController = new AbortController();

  try {
    await postSSE(
      "/api/chat",
      { message: text },
      (sseEvent) => {
        const { event, data } = sseEvent;
        handleSSEEvent(event, data);
      },
      { signal: currentAbortController.signal }
    );
  } catch (err) {
    if (err.name === "AbortError") {
      renderErrorMessage("Request aborted.");
    } else {
      console.error("Chat SSE error:", err);
      const errorMsg = err.message || "Failed to communicate with server.";
      renderErrorMessage(errorMsg);
      saveHistoryItem({
        id: "error-" + Date.now(),
        type: "error",
        data: { message: errorMsg },
        timestamp: Date.now()
      });
    }
  } finally {
    clearLiveStatus();
    setBusy(false);
    currentAbortController = null;
  }
}

function handleSSEEvent(event, data) {
  const now = Date.now();

  switch (event) {
    case "status":
      if (data && data.label) {
        updateLiveStatus(data.label);
      }
      break;

    case "plan":
      renderPlanCard(data, now);
      saveHistoryItem({
        id: "plan-" + now,
        type: "plan",
        data,
        timestamp: now
      });
      break;

    case "preview":
      clearLiveStatus();
      const cardId = renderPreviewCard(data, null, false, now);
      saveHistoryItem({
        id: cardId,
        type: "preview",
        data,
        timestamp: now
      });
      break;

    case "done":
      clearLiveStatus();
      renderDoneMessage(data, now);
      saveHistoryItem({
        id: "done-" + now,
        type: "done",
        data,
        timestamp: now
      });
      pollHealth();
      break;

    case "error":
      clearLiveStatus();
      const msg = data.message || "An error occurred.";
      renderErrorMessage(msg, now);
      saveHistoryItem({
        id: "error-" + now,
        type: "error",
        data: { message: msg },
        timestamp: now
      });
      break;

    default:
      console.log("Unhandled SSE event:", event, data);
      break;
  }
}

async function handleConfirm(cardId, threadId, approved) {
  const actionsContainer = document.getElementById(`actions-${cardId}`);
  if (actionsContainer) {
    actionsContainer.innerHTML = approved
      ? `<span class="action-status-badge badge-applied">Applying…</span>`
      : `<span class="action-status-badge badge-cancelled">Cancelling…</span>`;
  }

  setBusy(true);
  updateLiveStatus(approved ? "Applying changes" : "Cancelling changes");

  try {
    await postSSE(
      "/api/confirm",
      { thread_id: threadId, approved: approved },
      (sseEvent) => {
        const { event, data } = sseEvent;
        handleSSEEvent(event, data);
      }
    );

    // Update status badge on card
    if (actionsContainer) {
      actionsContainer.innerHTML = approved
        ? `<span class="action-status-badge badge-applied">Applied</span>`
        : `<span class="action-status-badge badge-cancelled">Cancelled</span>`;
    }

    // Update stored preview item status in history
    updateHistoryItem(cardId, { status: approved ? "applied" : "cancelled" });
  } catch (err) {
    console.error("Confirm error:", err);
    const errorMsg = err.message || "Confirmation failed.";
    renderErrorMessage(errorMsg);
    if (actionsContainer) {
      actionsContainer.innerHTML = `<span class="action-status-badge badge-cancelled">Failed</span>`;
    }
  } finally {
    clearLiveStatus();
    setBusy(false);
  }
}

async function handleUndo() {
  if (isBusy) return;

  headerUndoBtn.disabled = true;
  updateLiveStatus("Undoing change");

  try {
    const res = await fetch("/api/undo", {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });

    if (!res.ok) {
      throw new Error(`Undo failed: HTTP ${res.status}`);
    }

    const data = await res.json();
    const now = Date.now();
    renderUndoMessage(data.restored, data.summary, now);
    saveHistoryItem({
      id: "undo-" + now,
      type: "undo",
      data: { restored: data.restored, summary: data.summary },
      timestamp: now
    });
    pollHealth();
  } catch (err) {
    console.error("Undo error:", err);
    renderErrorMessage("Failed to undo: " + (err.message || "Network error"));
  } finally {
    clearLiveStatus();
    headerUndoBtn.disabled = false;
  }
}

// --- Health Status Polling ---

async function pollHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    updateHealthUI(data);
  } catch (err) {
    updateHealthUI({
      backend: "offline",
      llm: { reachable: false, error: err.message },
      excel: { connected: false, error: "Backend unreachable" }
    });
  }
}

function updateHealthUI(health) {
  // Update Model status dot
  const llm = health.llm || {};
  if (llm.reachable) {
    modelDot.className = "status-dot dot-online";
    const modelText = llm.model ? `Model: ${llm.model}` : "Model connected";
    modelStatus.title = modelText;
    modelStatus.setAttribute("aria-label", modelText);
  } else {
    modelDot.className = "status-dot dot-offline";
    const errorText = llm.error ? `Model unreachable: ${llm.error}` : "Model unreachable";
    modelStatus.title = errorText;
    modelStatus.setAttribute("aria-label", errorText);
  }

  // Update Excel status dot
  const excel = health.excel || {};
  if (excel.connected) {
    excelDot.className = "status-dot dot-online";
    const wb = excel.workbook || "Active";
    const sh = excel.sheet || "Sheet";
    const excelText = `Excel: ${wb} · ${sh}`;
    excelStatus.title = excelText;
    excelStatus.setAttribute("aria-label", excelText);
  } else {
    excelDot.className = "status-dot dot-offline";
    const errorText = excel.error ? `Excel disconnected: ${excel.error}` : "Excel disconnected";
    excelStatus.title = errorText;
    excelStatus.setAttribute("aria-label", errorText);
  }
}

// --- Office.js Task Pane Integration ---
if (typeof window !== "undefined" && window.Office && typeof window.Office.onReady === "function") {
  window.Office.onReady((info) => {
    if (info && info.host === window.Office.HostType.Excel) {
      console.log("Excel AI loaded inside Excel Task Pane");
    } else {
      console.log("Excel AI loaded in browser mode");
    }
  });
}

// --- Event Listeners Initialization ---

document.addEventListener("DOMContentLoaded", () => {
  // Restore history from sessionStorage
  restoreHistory();

  // Initial health poll, then every 10 seconds
  pollHealth();
  setInterval(pollHealth, HEALTH_POLL_INTERVAL_MS);

  // Send on Enter (Shift+Enter for newline)
  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitInstruction(promptInput.value);
    }
  });

  // Submit on Send button click
  sendBtn.addEventListener("click", (e) => {
    e.preventDefault();
    submitInstruction(promptInput.value);
  });

  // Header Undo button
  headerUndoBtn.addEventListener("click", () => {
    handleUndo();
  });

  // Example chips click
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const text = chip.getAttribute("data-instruction");
      if (text) {
        submitInstruction(text);
      }
    });
  });

  // Auto-resize input height up to max
  promptInput.addEventListener("input", () => {
    promptInput.style.height = "auto";
    promptInput.style.height = Math.min(promptInput.scrollHeight, 100) + "px";
  });
});

// Expose API for testing and programmatic automation
window.ExcelAI = {
  submitInstruction,
  handleSSEEvent,
  handleConfirm,
  handleUndo,
  renderUserMessage,
  renderPlanCard,
  renderPreviewCard,
  renderDoneMessage,
  renderErrorMessage,
  renderUndoMessage,
  updateLiveStatus,
  clearLiveStatus,
  loadHistory,
  saveHistoryItem,
  pollHealth
};

// Optional visual testing helper
function runDemoStep(step) {
  chatLog.innerHTML = "";
  const now = Date.now();
  if (step === "working") {
    renderUserMessage("Convert headers to camelCase", now);
    updateLiveStatus("Reading sheet");
  } else if (step === "plan_preview") {
    renderUserMessage("Convert headers to camelCase", now);
    renderPlanCard({
      op: "convert_case_style",
      op_title: "Convert case style",
      explanation: "Convert all column headers to camelCase",
      params: { target: { kind: "headers" }, style: "camel" }
    }, now);
    renderPreviewCard({
      thread_id: "demo-thread-1",
      summary: "Converted 10 headers to camelCase",
      warnings: [],
      changes: [
        { address: "A1", before: "Emp ID", after: "empId", formula: null },
        { address: "B1", before: "Full Name", after: "fullName", formula: null },
        { address: "C1", before: "Department", after: "department", formula: null },
        { address: "D1", before: "Email", after: "email", formula: null },
        { address: "E1", before: "Phone", after: "phone", formula: null },
        { address: "F1", before: "Salary", after: "salary", formula: null },
        { address: "G1", before: "Join Date", after: "joinDate", formula: null },
        { address: "H1", before: "City", after: "city", formula: null },
        { address: "I1", before: "Status", after: "status", formula: null },
        { address: "J1", before: "Rating", after: "rating", formula: null }
      ]
    }, "preview-demo-1", false, now);
  } else if (step === "done") {
    renderUserMessage("Convert headers to camelCase", now);
    renderPlanCard({
      op: "convert_case_style",
      op_title: "Convert case style",
      explanation: "Convert all column headers to camelCase",
      params: { target: { kind: "headers" }, style: "camel" }
    }, now);
    renderPreviewCard({
      thread_id: "demo-thread-1",
      summary: "Converted 10 headers to camelCase",
      status: "applied",
      changes: [
        { address: "A1", before: "Emp ID", after: "empId" },
        { address: "B1", before: "Full Name", after: "fullName" },
        { address: "C1", before: "Department", after: "department" }
      ]
    }, "preview-demo-1", true, now);
    renderDoneMessage({ applied: true, summary: "Converted 10 headers to camelCase" }, now);
  } else if (step === "undo") {
    renderUserMessage("Convert headers to camelCase", now);
    renderDoneMessage({ applied: true, summary: "Converted 10 headers to camelCase" }, now);
    renderUndoMessage(true, "Converted 10 headers to camelCase", now);
  } else if (step === "error") {
    renderUserMessage("Convert headers to camelCase", now);
    renderErrorMessage("Open a workbook in Excel first. Please launch Microsoft Excel with employees.xlsx.", now);
  } else if (step === "offline") {
    modelDot.className = "status-dot dot-offline";
    modelStatus.title = "Model unreachable: ConnectError: Connection refused";
    renderErrorMessage("LLM server unreachable at http://127.0.0.1:8080/v1. Check that llama-server is running.", now);
  }
}

const urlParams = new URLSearchParams(window.location.search);
const stepParam = urlParams.get("demo_step");
if (stepParam) {
  runDemoStep(stepParam);
}


