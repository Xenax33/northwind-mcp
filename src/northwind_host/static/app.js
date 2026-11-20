// Northwind MCP host page: tool list, question box, answer, recent changes,
// a live log of every protocol message (Server-Sent Events) and the approval dialog.
"use strict";

const $ = (id) => document.getElementById(id);
const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const time = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });

// ---------- Tools ----------
async function loadTools() {
  const tools = await (await fetch("/api/tools")).json();
  $("tool-count").textContent = `(${tools.length})`;
  $("tool-list").innerHTML = tools
    .map((t) => {
      const props = t.input_schema.properties || {};
      const required = new Set(t.input_schema.required || []);
      const args = Object.keys(props)
        .map((name) => `<li><code>${escapeHtml(name)}</code>${required.has(name) ? " (required)" : ""}</li>`)
        .join("");
      const badge = t.read_only
        ? '<span class="badge">read-only</span>'
        : '<span class="badge writes">changes data</span>';
      return `<li><details><summary>${escapeHtml(t.name)} ${badge}</summary>
        <p>${escapeHtml(t.description || "")}</p>
        ${args ? `<ul class="args">${args}</ul>` : "<p>No arguments.</p>"}</details></li>`;
    })
    .join("");
}

// ---------- Minimal, safe Markdown for answers (tables, lists, bold, code) ----------
function inline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}
function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const isRow = (l) => /^\s*\|.*\|\s*$/.test(l || "");
    if (isRow(line) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || "")) {
      const cells = (l) => l.trim().slice(1, -1).split("|").map((c) => inline(c.trim()));
      let html = `<table><thead><tr>${cells(line).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
      i += 2;
      while (i < lines.length && isRow(lines[i])) {
        html += `<tr>${cells(lines[i]).map((c) => `<td>${c}</td>`).join("")}</tr>`;
        i++;
      }
      out.push(html + "</tbody></table>");
      i--;
    } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join("")}</ul>`);
      i--;
    } else if (line.trim()) {
      out.push(`<p>${inline(line.replace(/^#+\s*/, ""))}</p>`);
    }
  }
  return out.join("");
}

// ---------- Asking ----------
async function ask(question) {
  $("ask-button").disabled = true;
  $("ask-button").textContent = "Working…";
  $("ask-error").hidden = true;
  $("answer").className = "answer empty";
  $("answer").textContent = "Thinking. Follow the steps in the live log →";
  $("answer-meta").textContent = "";
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    $("answer").className = "answer";
    $("answer").innerHTML = renderMarkdown(body.answer || "(no answer)");
    const tools = body.tool_calls.map((c) => c.name + (c.is_error ? " (error)" : "")).join(", ") || "none";
    $("answer-meta").textContent =
      `${body.model} · ${body.model_calls} model call(s) · ${body.prompt_tokens + body.completion_tokens} tokens · tools: ${tools}`;
    if (body.tool_calls.some((c) => c.name === "place_order")) loadChanges();
  } catch (err) {
    $("answer").textContent = "No answer.";
    $("ask-error").textContent = err.message;
    $("ask-error").hidden = false;
  } finally {
    $("ask-button").disabled = false;
    $("ask-button").textContent = "Ask";
  }
}

$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const question = $("question").value.trim();
  if (!question) {
    $("ask-error").textContent = "Type a question first.";
    $("ask-error").hidden = false;
    return;
  }
  ask(question);
});
$("question").addEventListener("input", () => ($("ask-error").hidden = true));
document.querySelectorAll(".chip").forEach((chip) =>
  chip.addEventListener("click", () => {
    $("question").value = chip.textContent;
    $("question").focus();
  }),
);

// ---------- Recent changes ----------
async function loadChanges() {
  try {
    const response = await fetch("/api/changes");
    if (!response.ok) throw new Error();
    const { changes } = await response.json();
    $("changes").innerHTML = changes.length
      ? `<table><thead><tr><th>When (UTC)</th><th>Order</th><th>Customer</th><th>Lines</th><th>Total</th><th>Client</th></tr></thead><tbody>${changes
          .map(
            (c) =>
              `<tr><td>${escapeHtml(c.at.replace("T", " ").slice(0, 19))}</td><td>${c.order_id}</td><td>${escapeHtml(
                c.customer_name || "",
              )}</td><td>${c.line_count}</td><td>${c.total?.toFixed(2) ?? ""}</td><td>${escapeHtml(c.client || "")}</td></tr>`,
          )
          .join("")}</tbody></table>`
      : '<p class="meta">No changes yet. Orders placed and approved will be listed here.</p>';
  } catch {
    $("changes").innerHTML = '<p class="error">Could not load recent changes.</p>';
  }
}
$("refresh-changes").addEventListener("click", loadChanges);

// ---------- Live log ----------
const methodsById = new Map(); // JSON-RPC id -> method, to label responses

function describeMcp(direction, m) {
  if (m.method) {
    if (m.id !== undefined) methodsById.set(m.id, m.method);
    const tool = m.method === "tools/call" ? ` ${m.params?.name ?? ""}` : "";
    const retry = m.params?.inputResponses ? " (with approval answer)" : "";
    return `${m.method}${tool}${retry}${m.id !== undefined ? ` #${m.id}` : ""}`;
  }
  const method = methodsById.get(m.id) || "response";
  if (m.error) return `error for ${method} #${m.id}: ${m.error.message}`;
  const r = m.result || {};
  if (r.inputRequests) return `${method} #${m.id} → needs input: asks the user to approve`;
  if (r.isError) return `${method} #${m.id} → tool error`;
  return `result of ${method} #${m.id}`;
}

function describeAi(e) {
  if (e.stage === "request") return [`step ${e.step}`, `request to ${e.model} (${e.messages} messages)`];
  const tokens = e.prompt_tokens != null ? ` · ${e.prompt_tokens}+${e.completion_tokens} tokens` : "";
  if (e.tool_calls.length) return [`step ${e.step}`, `model calls ${e.tool_calls.map((c) => c.name).join(", ")}${tokens}`];
  return [`step ${e.step}`, `model answered${tokens}`];
}

function addLogEntry(e) {
  let cls, label, summary, body;
  if (e.kind === "mcp") {
    cls = `mcp-entry ${e.direction}`;
    label = e.direction === "out" ? "→ server" : "← server";
    summary = describeMcp(e.direction, e.message);
    body = e.message;
  } else if (e.kind === "ai") {
    cls = "ai";
    [label, summary] = describeAi(e);
    body = e;
  } else if (e.kind === "approval") {
    cls = "approval";
    label = "approval";
    summary =
      e.status === "requested" ? "server asks the user to approve" :
      e.status === "auto" ? `answered automatically (eval): ${e.approved ? "approved" : "declined"}` :
      `user ${e.approved ? "approved" : "declined"}`;
    body = e;
  } else {
    cls = "note";
    label = e.kind;
    summary = e.text;
    body = null;
  }
  const li = document.createElement("li");
  li.className = cls;
  const head = `<span class="time">${time(e.ts)}</span><span class="dir">${escapeHtml(label)}</span><span>${escapeHtml(summary)}</span>`;
  li.innerHTML = body
    ? `<details><summary>${head}</summary><pre>${escapeHtml(JSON.stringify(body, null, 2))}</pre></details>`
    : `<div class="summary">${head}</div>`;
  const log = $("log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.appendChild(li);
  if (atBottom) log.scrollTop = log.scrollHeight;
}

$("show-mcp").addEventListener("change", (e) => $("log").classList.toggle("hide-mcp", !e.target.checked));
$("show-ai").addEventListener("change", (e) => $("log").classList.toggle("hide-ai", !e.target.checked));
$("clear-log").addEventListener("click", () => ($("log").innerHTML = ""));

// ---------- Approval dialog ----------
let pendingApproval = null;
function showApproval(e) {
  pendingApproval = e.approval_id;
  $("approval-text").textContent = e.text;
  $("approval").showModal();
  $("decline").focus(); // the safe choice has focus
}
async function answerApproval(approve) {
  const id = pendingApproval;
  pendingApproval = null;
  $("approval").close();
  if (id) {
    await fetch(`/api/approvals/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approve }),
    });
  }
}
$("approve").addEventListener("click", () => answerApproval(true));
$("decline").addEventListener("click", () => answerApproval(false));
$("approval").addEventListener("cancel", (e) => {
  e.preventDefault(); // Escape declines instead of leaving the server waiting
  answerApproval(false);
});

// ---------- Event stream ----------
let lastEventId = 0; // the server replays its history on every (re)connect; skip what we've shown
function connectEvents() {
  const source = new EventSource("/api/events");
  source.onopen = () => {
    $("status").textContent = "Connected to the MCP server";
    $("status").className = "status ok";
  };
  source.onerror = () => {
    $("status").textContent = "Live log disconnected, retrying…";
    $("status").className = "status bad";
  };
  source.onmessage = (msg) => {
    const e = JSON.parse(msg.data);
    if (e.id <= lastEventId) return;
    lastEventId = e.id;
    addLogEntry(e);
    if (e.kind === "approval" && e.status === "requested") showApproval(e);
    if (e.kind === "approval" && e.status === "answered" && e.approval_id === pendingApproval) {
      pendingApproval = null;
      $("approval").close();
    }
  };
}

loadTools();
loadChanges();
connectEvents();
