/* ═══════════════════════════════════════════════════════════════
   Banking Cloud Portal — Dashboard & Chat JS
   ═══════════════════════════════════════════════════════════════ */

document.addEventListener("DOMContentLoaded", () => {
    loadDashboard();
    loadPrompts();
    setupChat();
    setupTraceModal();
});

// ── Formatting helpers ───────────────────────────────────────────

function fmt(n) {
    return new Intl.NumberFormat("en-US", {
        style: "currency", currency: "USD",
        minimumFractionDigits: 2,
    }).format(n);
}

function fmtDate(raw) {
    if (!raw) return "—";
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return raw.split("T")[0] || raw;
    return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function badge(status) {
    const cls = {
        active: "badge-active", pending: "badge-pending",
        closed: "badge-closed", completed: "badge-completed",
        paid_off: "badge-completed",
    }[status] || "badge-pending";
    return `<span class="badge ${cls}">${status}</span>`;
}

// ── Dashboard ────────────────────────────────────────────────────

async function loadDashboard() {
    try {
        const resp = await fetch("/bank/api/summary");
        if (resp.status === 401) { window.location.href = "/bank/login"; return; }
        const data = await resp.json();

        // Personal details
        document.getElementById("personalName").textContent = data.name || "—";
        document.getElementById("personalCustomerId").textContent = data.customer_id || "—";
        document.getElementById("personalEmail").textContent = data.email || "—";
        document.getElementById("personalPhone").textContent = data.phone || "—";
        document.getElementById("personalAddress").textContent = data.address || "—";
        document.getElementById("personalDob").textContent = fmtDate(data.dob);

        // Summary cards
        document.getElementById("totalBalance").textContent = fmt(data.totals.balance);
        document.getElementById("numAccounts").textContent = data.totals.num_accounts;
        document.getElementById("numCards").textContent = data.totals.num_cards;
        document.getElementById("numLoans").textContent = data.totals.num_loans;

        // Accounts table
        const acctBody = document.querySelector("#accountsTable tbody");
        acctBody.innerHTML = data.accounts.map(a => `
            <tr>
                <td><strong>${a.account_id}</strong></td>
                <td>${a.type}</td>
                <td>${a.account_number}</td>
                <td><strong>${fmt(a.balance)}</strong></td>
                <td>${badge(a.status)}</td>
            </tr>
        `).join("");

        // Credit cards table
        const cardBody = document.querySelector("#cardsTable tbody");
        cardBody.innerHTML = data.credit_cards.map(c => `
            <tr>
                <td><strong>${c.card_id}</strong></td>
                <td>${c.card_type} ${c.card_tier}</td>
                <td>${c.card_number}</td>
                <td>${fmt(c.current_balance)} / ${fmt(c.credit_limit)}</td>
                <td>${fmt(c.available_credit)}</td>
                <td>${(c.reward_points || 0).toLocaleString()}</td>
                <td>${badge(c.status)}</td>
            </tr>
        `).join("");

        // Loans table
        const loanBody = document.querySelector("#loansTable tbody");
        if (data.contracts.length === 0) {
            loanBody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:#9ca3af;">No active loans</td></tr>`;
        } else {
            loanBody.innerHTML = data.contracts.map(l => `
                <tr>
                    <td><strong>${l.contract_id || l.loan_id || "—"}</strong></td>
                    <td>${l.loan_type || l.type || "—"}</td>
                    <td>${fmt(l.principal || l.amount || 0)}</td>
                    <td>${(l.interest_rate || 0)}%</td>
                    <td>${fmt(l.monthly_payment || 0)}</td>
                    <td>${fmt(l.remaining_balance || 0)}</td>
                    <td>${badge(l.status || "active")}</td>
                </tr>
            `).join("");
        }

        // Transactions table
        const txBody = document.querySelector("#transactionsTable tbody");
        txBody.innerHTML = data.recent_transactions.map(t => {
            const isCredit = (t.type || "").toLowerCase() === "credit";
            const cls = isCredit ? "amount-positive" : "amount-negative";
            const sign = isCredit ? "+" : "-";
            return `
                <tr>
                    <td>${fmtDate(t.date)}</td>
                    <td>${t.merchant || t.description || "—"}</td>
                    <td>${t.category || "—"}</td>
                    <td class="${cls}">${sign}${fmt(Math.abs(t.amount))}</td>
                    <td>${badge(t.status)}</td>
                </tr>
            `;
        }).join("");

    } catch (err) {
        console.error("Dashboard load error:", err);
    }
}

// ── Chat Panel ───────────────────────────────────────────────────

function setupChat() {
    const panel = document.getElementById("chatPanel");
    const toggle = document.getElementById("chatToggle");
    const closeBtn = document.getElementById("closeChatBtn");
    const clearBtn = document.getElementById("clearChatBtn");
    const input = document.getElementById("chatInput");
    const sendBtn = document.getElementById("sendBtn");
    const dashboard = document.getElementById("dashboardPanel");

    function openChat() {
        panel.classList.add("open");
        toggle.classList.add("hidden");
        dashboard.classList.add("chat-open");
        input.focus();
    }

    function closeChat() {
        panel.classList.remove("open");
        toggle.classList.remove("hidden");
        dashboard.classList.remove("chat-open");
    }

    toggle.addEventListener("click", openChat);
    closeBtn.addEventListener("click", closeChat);

    clearBtn.addEventListener("click", async () => {
        await fetch("/bank/api/chat/clear", { method: "POST" });
        const messages = document.getElementById("chatMessages");
        messages.innerHTML = `
            <div class="chat-welcome">
                <p>👋 Chat history cleared. Ask me anything!</p>
                <div class="quick-prompts" id="quickPrompts"></div>
            </div>
        `;
        loadPrompts();
    });

    sendBtn.addEventListener("click", () => sendMessage());
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
}

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const msg = input.value.trim();
    if (!msg) return;

    input.value = "";
    addBubble(msg, "user");

    // Show typing indicator
    const typingId = addTypingIndicator();

    try {
        const resp = await fetch("/bank/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: msg }),
        });

        removeBubble(typingId);

        if (resp.status === 401) {
            window.location.href = "/bank/login";
            return;
        }

        const data = await resp.json();

        if (data.error) {
            addBubble("Sorry, something went wrong: " + data.error, "error");
        } else if (data.blocked) {
            addBubble(data.response, "error");
        } else {
            const duration = data.duration_ms ? `${(data.duration_ms / 1000).toFixed(1)}s` : "";
            addBubble(data.response, "assistant", duration);
        }

        if (data.trace) {
            addTraceEntry({
                id: data.trace_id || Date.now(),
                timestamp: new Date().toLocaleString(),
                user_message: msg,
                response_preview: data.response || data.error || "",
                blocked: !!data.blocked,
                duration_ms: data.duration_ms || 0,
                trace: data.trace,
            });
        }
    } catch (err) {
        removeBubble(typingId);
        addBubble("Connection error. Please try again.", "error");
    }
}

function addBubble(text, type, meta) {
    const container = document.getElementById("chatMessages");
    const id = "bubble-" + Date.now();
    const div = document.createElement("div");
    div.id = id;
    div.className = `chat-bubble ${type}`;

    // Convert newlines and basic markdown
    const formatted = text
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>");
    div.innerHTML = formatted;

    if (meta) {
        const metaDiv = document.createElement("div");
        metaDiv.className = "chat-meta";
        metaDiv.textContent = meta;
        div.appendChild(metaDiv);
    }

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function addTypingIndicator() {
    const container = document.getElementById("chatMessages");
    const id = "typing-" + Date.now();
    const div = document.createElement("div");
    div.id = id;
    div.className = "chat-bubble assistant";
    div.innerHTML = `<span class="typing-dots"><span></span><span></span><span></span></span>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeBubble(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ── Quick Prompts ────────────────────────────────────────────────

async function loadPrompts() {
    try {
        const resp = await fetch("/bank/api/prompts");
        const data = await resp.json();
        const containers = document.querySelectorAll("#quickPrompts");
        containers.forEach(container => {
            container.innerHTML = data.prompts.map(p =>
                `<button class="quick-prompt" onclick="usePrompt(this)">${p}</button>`
            ).join("");
        });
    } catch (err) {
        console.error("Failed to load prompts:", err);
    }
}

function usePrompt(el) {
    const input = document.getElementById("chatInput");
    input.value = el.textContent;
    // Open chat if not open
    const panel = document.getElementById("chatPanel");
    if (!panel.classList.contains("open")) {
        document.getElementById("chatToggle").click();
    }
    sendMessage();
}

// ── Pipeline Trace Modal ─────────────────────────────────────────

let traceEntries = [];

function setupTraceModal() {
    const overlay = document.getElementById("traceModalOverlay");
    const openBtn = document.getElementById("traceModalBtn");
    const closeBtn = document.getElementById("traceModalClose");
    const clearBtn = document.getElementById("traceClearBtn");

    openBtn.addEventListener("click", async () => {
        await loadTracesFromServer();
        renderTraceModal();
        overlay.hidden = false;
    });

    closeBtn.addEventListener("click", () => { overlay.hidden = true; });
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) overlay.hidden = true;
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
    });

    clearBtn.addEventListener("click", async () => {
        traceEntries = [];
        updateTraceBadge();
        renderTraceModal();
        await fetch("/bank/api/traces/clear", { method: "POST" });
    });

    loadTracesFromServer();
}

async function loadTracesFromServer() {
    try {
        const resp = await fetch("/bank/api/traces");
        if (resp.status === 401) return;
        const data = await resp.json();
        traceEntries = data.traces || [];
        updateTraceBadge();
    } catch (err) {
        console.error("Failed to load traces:", err);
    }
}

function addTraceEntry(entry) {
    if (entry.id != null && traceEntries.some((e) => e.id === entry.id)) {
        return;
    }
    traceEntries.unshift(entry);
    if (traceEntries.length > 30) traceEntries.length = 30;
    updateTraceBadge();
}

function getTurnMessages(step) {
    if (Array.isArray(step.turn_messages) && step.turn_messages.length) {
        return step.turn_messages;
    }
    if (Array.isArray(step.messages) && step.messages.length) {
        const users = step.messages.filter((m) => m.role === "user");
        return users.length ? [users[users.length - 1]] : step.messages.slice(-1);
    }
    return [];
}

function renderPriorTurnsMeta(step) {
    const n = step.prior_turns || 0;
    if (!n) return "";
    return `<div class="trace-step-meta">${n} prior conversation turn${n === 1 ? "" : "s"} sent to the LLM (not shown in this trace)</div>`;
}

function updateTraceBadge() {
    const badge = document.getElementById("traceBadge");
    if (badge) badge.textContent = String(traceEntries.length);
}

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function truncateTraceText(text, limit = 400) {
    const s = String(text || "");
    return s.length > limit ? `${s.slice(0, limit)}…` : s;
}

function getTraceStepClass(stepName) {
    const s = (stepName || "").toLowerCase();
    if (s.includes("gate 1")) return "trace-step-gate1";
    if (s.includes("gate 2")) return "trace-step-gate2";
    if (s.includes("kb") || s.includes("retrieve") || s.includes("langgraph") || s.includes("llm") || s.includes("orchestrator")) {
        return "trace-step-protected";
    }
    return "";
}

function renderCompareBox(label, value, kind) {
    return `
        <div class="compare-box compare-${kind}">
            <div class="compare-label">${escapeHtml(label)}</div>
            <pre>${escapeHtml(truncateTraceText(value))}</pre>
        </div>`;
}

function renderCompareGrid(leftLabel, leftVal, rightLabel, rightVal, leftKind, rightKind) {
    return `
        <div class="compare-grid">
            ${renderCompareBox(leftLabel, leftVal, leftKind)}
            ${renderCompareBox(rightLabel, rightVal, rightKind)}
        </div>`;
}

function renderTraceMessage(msg) {
    return `
        <div class="trace-msg compare-protected">
            <div class="trace-msg-role compare-label">${escapeHtml(msg.role || "message")}</div>
            <pre>${escapeHtml(truncateTraceText(msg.content))}</pre>
        </div>`;
}

function renderTraceStepBody(step) {
    const name = step.step || "";

    if (name.includes("Gate 1")) {
        let html = renderCompareGrid(
            "Original input",
            step.original,
            "Protected output",
            step.protected,
            "clear",
            "protected"
        );
        html += `<div class="trace-step-meta">Risk ${step.risk_score ?? 0} · PII ${step.pii_elements ?? 0}${step.accepted === false ? " · BLOCKED" : ""}</div>`;
        if (Array.isArray(step.elements_found) && step.elements_found.length) {
            html += `<div class="trace-step-meta">Entities: ${escapeHtml(step.elements_found.join(", "))}</div>`;
        }
        return html;
    }

    if (name.includes("Gate 2")) {
        return renderCompareGrid(
            "LLM output (tokenized)",
            step.raw_response,
            "Detokenized response",
            step.final_response,
            "protected",
            "clear"
        );
    }

    if (name.includes("KB File Retrieval")) {
        if (step.error) {
            return renderCompareBox("Error", step.error, "clear");
        }
        let html = renderCompareBox("KB context (tokenized)", step.preview || "", "protected");
        html += `<div class="trace-step-meta">${escapeHtml(step.file || "KB file")} · ${step.chars ?? 0} chars</div>`;
        return html;
    }

    if (name.includes("Orchestrator")) {
        let html = "";
        if (Array.isArray(step.sub_trace) && step.sub_trace.length) {
            html += `<div class="trace-substeps">${step.sub_trace.map((s) => renderTraceStepBlock(s, 1)).join("")}</div>`;
        } else if (step.response_preview) {
            html += renderCompareBox("Tokenized response", step.response_preview, "protected");
        }
        return html;
    }

    if (name.includes("Retrieve")) {
        let html = renderCompareBox("KB context (tokenized)", step.kb_preview || "", "protected");
        html += `<div class="trace-step-meta">${step.kb_chars ?? 0} chars</div>`;
        return html;
    }

    if (name.includes("LLM") || (Array.isArray(step.turn_messages) && step.turn_messages.length)) {
        let html = "";
        const turnMessages = getTurnMessages(step);
        if (turnMessages.length) {
            html += `<div class="trace-msg-list">${turnMessages.map(renderTraceMessage).join("")}</div>`;
        }
        html += renderPriorTurnsMeta(step);
        if (step.response_preview) {
            html += renderCompareBox("Tokenized response", step.response_preview, "protected");
        }
        return html;
    }

    return renderTraceGenericFields(step);
}

function renderTraceGenericFields(step) {
    const protectedKeys = {
        protected: "Protected value",
        preview: "Preview (tokenized)",
        kb_preview: "KB preview (tokenized)",
        response_preview: "Response preview (tokenized)",
        raw_response: "Raw response (tokenized)",
    };
    const clearKeys = {
        original: "Original value",
        final_response: "Final response",
    };
    let html = "";

    for (const [key, label] of Object.entries(clearKeys)) {
        if (step[key] != null && step[key] !== "") {
            html += renderCompareBox(label, step[key], "clear");
        }
    }
    for (const [key, label] of Object.entries(protectedKeys)) {
        if (step[key] != null && step[key] !== "") {
            html += renderCompareBox(label, step[key], "protected");
        }
    }

    const skip = new Set([
        "step", "duration_ms", "messages", "sub_trace",
        ...Object.keys(protectedKeys), ...Object.keys(clearKeys),
    ]);
    for (const [key, val] of Object.entries(step)) {
        if (skip.has(key) || val == null || val === "") continue;
        html += `<div class="trace-step-meta"><span class="label">${escapeHtml(key)}:</span> ${escapeHtml(formatTraceValue(val))}</div>`;
    }
    return html;
}

function formatTraceValue(val) {
    if (val === null || val === undefined) return "—";
    if (typeof val === "object") return JSON.stringify(val, null, 2);
    return String(val);
}

function renderTraceStepBlock(step, depth = 0) {
    const ms = step.duration_ms != null ? `${step.duration_ms}ms` : "";
    const stepClass = getTraceStepClass(step.step);
    return `
        <div class="trace-step ${stepClass}" style="margin-left:${depth * 8}px">
            <div class="trace-step-name">
                <span>${escapeHtml(step.step || "Step")}</span>
                ${ms ? `<span class="trace-step-time">${ms}</span>` : ""}
            </div>
            ${renderTraceStepBody(step)}
        </div>`;
}

function renderTraceModal() {
    const body = document.getElementById("traceModalBody");
    if (!traceEntries.length) {
        body.innerHTML = `<p class="trace-empty">Send a chat message to capture pipeline traces.</p>`;
        return;
    }

    body.innerHTML = traceEntries.map((entry, idx) => {
        const messageNum = traceEntries.length - idx;
        const title = entry.user_message || entry.protected_message || "Request";
        const meta = [
            entry.timestamp,
            entry.duration_ms ? `${entry.duration_ms}ms` : null,
            entry.blocked ? "blocked" : null,
        ].filter(Boolean).join(" · ");

        const steps = (entry.trace || []).map((s) => renderTraceStepBlock(s)).join("");
        const footer = entry.blocked
            ? `<div class="trace-step trace-step-gate1"><div class="trace-step-name"><span>Run blocked</span></div>${renderCompareBox("Blocked response", entry.response_preview || "Request blocked", "clear")}</div>`
            : "";

        return `
            <div class="trace-request ${idx === 0 ? "open" : ""}" data-trace-idx="${idx}" data-trace-id="${escapeHtml(String(entry.id ?? ""))}">
                <div class="trace-request-header" onclick="toggleTraceRequest(this.parentElement)">
                    <div class="trace-request-heading">
                        <span class="trace-request-label">Message ${messageNum}</span>
                        <span class="trace-request-title">${escapeHtml(title)}</span>
                    </div>
                    <span class="trace-request-meta">${escapeHtml(meta)}</span>
                </div>
                <div class="trace-request-body">${steps}${footer}</div>
            </div>`;
    }).join("");
}

function toggleTraceRequest(el) {
    el.classList.toggle("open");
}
