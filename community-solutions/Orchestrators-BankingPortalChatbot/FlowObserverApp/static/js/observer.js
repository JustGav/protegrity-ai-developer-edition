/* FlowObserverApp — SSE client + pipeline UI */

const runs = new Map();
let lastEventId = 0;
let sourceFilter = "all";
let showFullPayloads = false;
let activeRunId = null;

const NODE_ORDER = ["customer", "gate1", "kb", "orchestrator", "llm", "gate2", "response"];

document.addEventListener("DOMContentLoaded", () => {
    setupControls();
    connectStream();
});

function setupControls() {
    document.querySelectorAll(".filter-chip").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".filter-chip").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            sourceFilter = btn.dataset.filter;
            renderTimeline();
        });
    });

    document.getElementById("fullPayloads").addEventListener("change", (e) => {
        showFullPayloads = e.target.checked;
        renderTimeline();
    });

    document.getElementById("clearEventsBtn").addEventListener("click", async () => {
        await fetch("/observe/api/clear", { method: "POST" });
        runs.clear();
        lastEventId = 0;
        activeRunId = null;
        renderDiagram(null);
        renderTimeline();
        connectStream();
    });
}

function connectStream() {
    const url = `/observe/api/stream?since=${lastEventId}`;
    const source = new EventSource(url);

    source.onmessage = (msg) => {
        try {
            const event = JSON.parse(msg.data);
            ingestEvent(event);
        } catch (err) {
            console.error("Bad event payload", err);
        }
    };

    source.onerror = () => {
        source.close();
        setTimeout(connectStream, 2000);
    };
}

function ingestEvent(event) {
    lastEventId = Math.max(lastEventId, event.id);
    if (!runs.has(event.run_id)) {
        runs.set(event.run_id, {
            run_id: event.run_id,
            source_app: event.source_app,
            events: [],
            started_at: event.created_at,
            user_message: "",
            customer_id: "",
            blocked: false,
            total_ms: 0,
            active_node: "customer",
            completed_nodes: new Set(["customer"]),
        });
    }

    const run = runs.get(event.run_id);
    run.events.push(event);

    if (event.step === "run_start") {
        run.user_message = event.payload.user_message || "";
        run.customer_id = event.payload.customer_id || "";
    }
    if (event.payload?.node) {
        run.active_node = event.payload.node;
        const idx = NODE_ORDER.indexOf(event.payload.node);
        if (idx >= 0) {
            NODE_ORDER.slice(0, idx + 1).forEach((n) => run.completed_nodes.add(n));
        }
    }
    if (event.step === "run_complete") {
        run.blocked = !!event.payload.blocked;
        run.total_ms = event.payload.total_ms || 0;
        run.active_node = "response";
        run.completed_nodes.add("response");
    }

    activeRunId = event.run_id;
    renderDiagram(run);
    renderTimeline();
}

function renderDiagram(run) {
    const label = document.getElementById("activeRunLabel");
    document.querySelectorAll(".pipe-node").forEach((node) => {
        node.classList.remove("active", "done", "blocked", "state-clear", "state-protected");
        const key = node.dataset.node;
        if (!run) return;

        const dataState = getNodeDataState(key, run);
        if (dataState) node.classList.add(`state-${dataState}`);

        if (run.blocked && key === "gate1") node.classList.add("blocked");
        if (run.completed_nodes.has(key)) node.classList.add("done");
        if (run.active_node === key && eventIsInProgress(run)) node.classList.add("active");
    });

    if (!run) {
        label.textContent = "Waiting for chat activity…";
        return;
    }
    const src = run.source_app === "business" ? "Banking Portal" : "Technical Portal";
    label.textContent = `${src} · ${truncate(run.user_message, 60)}`;
}

function getNodeDataState(nodeKey, run) {
    const reached = run.completed_nodes.has(nodeKey) || run.active_node === nodeKey;

    switch (nodeKey) {
        case "customer":
            return reached || run.events.length ? "clear" : null;
        case "gate1": {
            if (!reached) return null;
            const gate1 = run.events.find((e) => e.step === "gate1");
            if (!gate1 || run.blocked || gate1.payload?.accepted === false) return "clear";
            return "protected";
        }
        case "kb":
        case "orchestrator":
        case "llm":
            return reached ? "protected" : null;
        case "gate2": {
            if (!reached) return null;
            if (run.events.some((e) => e.step === "gate2")) return "clear";
            return "protected";
        }
        case "response":
            if (run.blocked) return null;
            return run.events.some((e) => e.step === "run_complete") ? "clear" : null;
        default:
            return null;
    }
}

function eventIsInProgress(run) {
    const last = run.events[run.events.length - 1];
    return last && last.step !== "run_complete";
}

function renderTimeline() {
    const container = document.getElementById("timeline");
    const sorted = [...runs.values()].sort((a, b) => b.started_at - a.started_at);
    const visible = sorted.filter((run) => matchesFilter(run.source_app));

    document.getElementById("runCountLabel").textContent = `${visible.length} run${visible.length === 1 ? "" : "s"}`;

    if (!visible.length) {
        container.innerHTML = `<p class="empty-state">Send a chat message in the Banking or Technical portal to see live pipeline events.</p>`;
        return;
    }

    container.innerHTML = visible.map((run, idx) => renderRunCard(run, idx === 0)).join("");
    container.querySelectorAll(".run-header").forEach((header) => {
        header.addEventListener("click", () => header.parentElement.classList.toggle("open"));
    });
}

function matchesFilter(sourceApp) {
    if (sourceFilter === "all") return true;
    return sourceApp === sourceFilter;
}

function runDisplayEvents(run) {
    const events = run.events.filter((e) => e.step !== "run_start");
    const hasLlmRequest = events.some((e) => e.step === "llm_request");
    if (!hasLlmRequest) return events;
    return events.filter((e) => {
        if (e.step === "orchestrator" && hasLlmRequest) return false;
        if (e.step !== "orchestrator_step") return true;
        const name = (e.payload?.step || "").toLowerCase();
        if (name.includes("llm")) return false;
        if (Array.isArray(e.payload?.turn_messages) || Array.isArray(e.payload?.messages)) return false;
        return true;
    });
}

function getTurnMessages(source) {
    if (Array.isArray(source.turn_messages) && source.turn_messages.length) {
        return source.turn_messages;
    }
    if (Array.isArray(source.messages) && source.messages.length) {
        const users = source.messages.filter((m) => m.role === "user");
        return users.length ? [users[users.length - 1]] : source.messages.slice(-1);
    }
    return [];
}

function renderPriorTurnsMeta(payload) {
    const n = payload.prior_turns || 0;
    if (!n) return "";
    return `<div class="step-meta">${n} prior conversation turn${n === 1 ? "" : "s"} sent to the LLM (not shown in this run)</div>`;
}

function renderRunCard(run, openDefault) {
    const srcClass = run.source_app === "business" ? "business" : "technical";
    const srcLabel = run.source_app === "business" ? "Business" : "Technical";
    const time = new Date(run.started_at * 1000).toLocaleTimeString();
    const status = run.blocked ? "blocked" : `${run.total_ms || "…"}ms`;
    const customer = run.customer_id ? ` · ${escapeHtml(run.customer_id)}` : "";

    return `
        <article class="run-card ${openDefault ? "open" : ""}" data-run="${escapeHtml(run.run_id)}">
            <div class="run-header">
                <div class="run-title">
                    <span class="source-badge ${srcClass}">${srcLabel}</span>
                    <div class="run-message-block">
                        <span class="run-message-label">User message</span>
                        <span class="run-message-text">${escapeHtml(truncate(run.user_message, 80))}</span>
                    </div>
                </div>
                <div class="run-meta">${time}${customer} · ${status}</div>
            </div>
            <div class="run-body">
                ${runDisplayEvents(run).map(renderStep).join("")}
            </div>
        </article>`;
}

function renderStep(event) {
    const p = event.payload || {};
    const ms = p.duration_ms != null ? `${p.duration_ms}ms` : "";
    const title = stepTitle(event.step, p);
    let body = "";

    if (event.step === "gate1") {
        body = renderCompare("Original input", p.original, "Protected output", p.protected, "clear", "protected");
        body += `<div class="step-meta">Risk ${p.risk_score ?? 0} · PII ${p.pii_elements ?? 0}${p.accepted === false ? " · BLOCKED" : ""}</div>`;
    } else if (event.step === "gate2") {
        const raw = p.raw_response || p.raw_preview || "";
        const final = p.final_response || p.final_preview || "";
        body = renderCompare("LLM output (tokenized)", raw, "Detokenized response", final, "protected", "clear");
        if (p.protegrity_user) body += `<div class="step-meta">Unprotect as ${escapeHtml(p.protegrity_user)}</div>`;
    } else if (event.step === "llm_request") {
        const turnMessages = getTurnMessages(p);
        if (turnMessages.length) {
            body = `<div class="msg-list">${turnMessages.map((m) => renderMessage(m)).join("")}</div>`;
        }
        body += renderPriorTurnsMeta(p);
        if (p.response_preview) {
            body += `<div class="step-meta">Response preview</div><div class="compare-box compare-protected ${showFullPayloads ? "full" : ""}"><div class="compare-label">Tokenized response</div><pre>${escapeHtml(truncateText(p.response_preview))}</pre></div>`;
        }
    } else if (event.step === "run_complete") {
        body = `<div class="compare-box compare-clear ${showFullPayloads ? "full" : ""}"><div class="compare-label">Final response (in the clear)</div><pre>${escapeHtml(truncateText(p.response || ""))}</pre></div>`;
    } else {
        body = renderGenericPayload(p);
    }

    return `
        <div class="step-row ${escapeHtml(event.step)}">
            <div class="step-title">${escapeHtml(title)} ${ms ? `<span class="step-meta">${ms}</span>` : ""}</div>
            ${body}
        </div>`;
}

function stepTitle(step, payload) {
    const map = {
        gate1: "Gate 1 — Input protection",
        kb_retrieval: "KB retrieval",
        rag: "RAG retrieval",
        knowledge_graph: "Knowledge graph",
        orchestrator: `Orchestrator — ${payload.orchestrator || "pipeline"}`,
        orchestrator_step: payload.step || "Orchestrator step",
        llm_request: "LLM request / response",
        gate2: "Gate 2 — Output unprotection",
        run_complete: payload.blocked ? "Run blocked" : "Run complete",
    };
    return map[step] || step;
}

function renderCompare(leftLabel, leftVal, rightLabel, rightVal, leftKind = "clear", rightKind = "protected") {
    const full = showFullPayloads ? "full" : "";
    return `
        <div class="compare-grid">
            <div class="compare-box compare-${leftKind} ${full}">
                <div class="compare-label">${escapeHtml(leftLabel)}</div>
                <pre>${escapeHtml(truncateText(leftVal || ""))}</pre>
            </div>
            <div class="compare-box compare-${rightKind} ${full}">
                <div class="compare-label">${escapeHtml(rightLabel)}</div>
                <pre>${escapeHtml(truncateText(rightVal || ""))}</pre>
            </div>
        </div>`;
}

function renderMessage(msg) {
    const full = showFullPayloads ? "full" : "";
    return `
        <div class="msg-item compare-protected ${full}">
            <div class="msg-role">${escapeHtml(msg.role || "message")}</div>
            <pre>${escapeHtml(truncateText(msg.content || ""))}</pre>
        </div>`;
}

function renderGenericPayload(payload) {
    const skip = new Set(["node", "messages", "turn_messages", "sub_trace", "prior_turns"]);
    const lines = Object.entries(payload)
        .filter(([k]) => !skip.has(k))
        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`);
    if (!lines.length) return "";
    return `<div class="compare-box"><pre>${escapeHtml(truncateText(lines.join("\n")))}</pre></div>`;
}

function truncateText(text) {
    if (showFullPayloads) return String(text || "");
    const s = String(text || "");
    return s.length > 400 ? `${s.slice(0, 400)}…` : s;
}

function truncate(text, n) {
    const s = String(text || "");
    return s.length > n ? `${s.slice(0, n)}…` : s;
}

function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function toggleRunCard(el) {
    el.classList.toggle("open");
}
