"""
Banking Cloud Portal — Customer-facing Flask application.

Features:
  - Customer login (from config/customer_users.json)
  - Dashboard: accounts, credit cards, loans, recent transactions
  - AI Chatbot: powered by LangGraph + Protegrity dual-gate protection
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# ── Paths ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
KB_DIR = PROJECT_ROOT / "banking_data" / "knowledge_base"
HISTORY_DIR = APP_DIR / "chat_history"
HISTORY_DIR.mkdir(exist_ok=True)

# ── Flask App ────────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(APP_DIR / "static"),
)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "banking-cloud-portal-secret-2026"
)

log = logging.getLogger(__name__)

# ── Load Customer Users ──────────────────────────────────────────────

_users_path = PROJECT_ROOT / "config" / "customer_users.json"
with open(_users_path) as _f:
    CUSTOMER_USERS: dict = json.load(_f)

# ── Load Customer Data ───────────────────────────────────────────────

_customers_path = PROJECT_ROOT / "banking_data" / "customers_protected.json"
if not _customers_path.exists():
    _customers_path = PROJECT_ROOT / "banking_data" / "customers.json"
    log.warning("customers_protected.json not found, falling back to customers.json")
with open(_customers_path) as _f:
    _customers_list: list[dict] = json.load(_f)

CUSTOMERS_BY_ID: dict[str, dict] = {c["customer_id"]: c for c in _customers_list}


# ── Protegrity helpers ───────────────────────────────────────────────


def _unprotect_text(text: str) -> str:
    """Unprotect a Protegrity-tokenized field via find_and_unprotect."""
    if not text or "[" not in text:
        return text
    try:
        from services.protegrity_guard import get_guard
        result = get_guard().find_and_unprotect(text)
        return result.transformed_text
    except Exception as exc:
        log.warning("Protegrity unprotect failed: %s", exc)
        return text

# ── Chat Histories ───────────────────────────────────────────────────

_chat_histories: dict[str, list] = {}
_trace_logs: dict[str, list] = {}
MAX_TRACE_LOGS = 30


def _history_key(customer_id: str) -> str:
    return f"biz_{customer_id}"


def _get_history(customer_id: str) -> list[dict]:
    key = _history_key(customer_id)
    if key not in _chat_histories:
        fp = HISTORY_DIR / f"{key}.json"
        if fp.exists():
            with open(fp) as f:
                _chat_histories[key] = json.load(f)
        else:
            _chat_histories[key] = []
    return _chat_histories[key]


def _save_history(customer_id: str):
    key = _history_key(customer_id)
    fp = HISTORY_DIR / f"{key}.json"
    with open(fp, "w") as f:
        json.dump(_chat_histories.get(key, []), f)


def _append_trace_log(customer_id: str, entry: dict):
    logs = _trace_logs.setdefault(customer_id, [])
    logs.insert(0, entry)
    del logs[MAX_TRACE_LOGS:]


# ── Auth helpers ─────────────────────────────────────────────────────


def _login_required(fn):
    """Decorator that redirects unauthenticated users to login."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "customer_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════

# ── Login / Logout ───────────────────────────────────────────────────


@app.route("/bank/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        pw_hash = hashlib.sha256(password.encode()).hexdigest()

        user = CUSTOMER_USERS.get(username)
        if user and user["password_hash"] == pw_hash:
            session["username"] = username
            session["customer_id"] = user["customer_id"]
            session["customer_name"] = user["name"]
            return redirect(url_for("dashboard"))
        error = "Invalid username or password"

    return render_template("login.html", error=error)


@app.route("/bank/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("login"))


# ── Dashboard ────────────────────────────────────────────────────────


@app.route("/bank/dashboard")
@_login_required
def dashboard():
    customer_id = session["customer_id"]
    customer = CUSTOMERS_BY_ID.get(customer_id, {})
    # Unprotect PII fields via Protegrity before passing to template
    display_customer = {
        **customer,
        "name":    _unprotect_text(customer.get("name", "")),
        "email":   _unprotect_text(customer.get("email", "")),
        "phone":   _unprotect_text(customer.get("phone", "")),
        "address": _unprotect_text(customer.get("address", "")),
        "dob":     _unprotect_text(customer.get("dob", "")),
    }
    return render_template(
        "dashboard.html",
        customer=display_customer,
        customer_name=session["customer_name"],
    )


# ── API: Customer Data ───────────────────────────────────────────────


@app.route("/bank/api/summary")
@_login_required
def api_summary():
    """Return dashboard summary data as JSON."""
    customer_id = session["customer_id"]
    customer = CUSTOMERS_BY_ID.get(customer_id, {})

    accounts = customer.get("accounts", [])

    # Unprotect credit card numbers via Protegrity
    cards = []
    for cc in customer.get("credit_cards", []):
        card = dict(cc)
        card["card_number"] = _unprotect_text(cc.get("card_number", ""))
        cards.append(card)

    contracts = customer.get("contracts", [])
    transactions = sorted(
        customer.get("transactions", []),
        key=lambda t: t.get("date", ""),
        reverse=True,
    )[:20]

    total_balance = sum(a.get("balance", 0) for a in accounts)
    total_credit_used = sum(c.get("current_balance", 0) for c in customer.get("credit_cards", []))
    total_credit_limit = sum(c.get("credit_limit", 0) for c in customer.get("credit_cards", []))

    return jsonify(
        {
            "customer_id": customer_id,
            "name":  _unprotect_text(customer.get("name", "")),
            "email": _unprotect_text(customer.get("email", "")),
            "phone": _unprotect_text(customer.get("phone", "")),
            "address": _unprotect_text(customer.get("address", "")),
            "dob": _unprotect_text(customer.get("dob", "")),
            "accounts": accounts,
            "credit_cards": cards,
            "contracts": contracts,
            "recent_transactions": transactions,
            "totals": {
                "balance": round(total_balance, 2),
                "credit_used": round(total_credit_used, 2),
                "credit_limit": round(total_credit_limit, 2),
                "credit_available": round(
                    total_credit_limit - total_credit_used, 2
                ),
                "num_accounts": len(accounts),
                "num_cards": len(cards),
                "num_loans": len(contracts),
            },
        }
    )


# ── API: Chat ────────────────────────────────────────────────────────


@app.route("/bank/api/chat", methods=["POST"])
@_login_required
def api_chat():
    """Process a chat message through LangGraph + Protegrity gates."""
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    customer_id = session["customer_id"]
    t0 = time.time()
    trace_id = int(t0 * 1000)
    trace = []

    from services.pipeline_emitter import SOURCE_BUSINESS, PipelineRunEmitter

    emitter = PipelineRunEmitter(SOURCE_BUSINESS, customer_id, user_message)

    try:
        # ── Gate 1: Protect input ────────────────────────────────
        from services.protegrity_guard import get_guard

        guard = get_guard()

        t_g1 = time.time()
        gate1 = guard.gate1_input(user_message, risk_threshold=0.7)
        trace.append(
            {
                "step": "Gate 1 — Input Protection",
                "duration_ms": round((time.time() - t_g1) * 1000),
                "risk_score": getattr(gate1, "risk_score", 0),
                "accepted": getattr(gate1, "risk_accepted", True),
                "pii_elements": len(getattr(gate1, "elements_found", [])),
                "elements_found": [
                    e.get("entity_type", "unknown")
                    for e in getattr(gate1, "elements_found", [])
                ],
                "original": user_message,
                "protected": getattr(gate1, "transformed_text", user_message),
            }
        )

        emitter.gate1(
            original=user_message,
            protected=getattr(gate1, "transformed_text", user_message),
            duration_ms=round((time.time() - t_g1) * 1000),
            risk_score=getattr(gate1, "risk_score", 0),
            accepted=getattr(gate1, "risk_accepted", True),
            pii_elements=len(getattr(gate1, "elements_found", [])),
            elements_found=[
                e.get("entity_type", "unknown")
                for e in getattr(gate1, "elements_found", [])
            ],
        )

        if not getattr(gate1, "risk_accepted", True):
            explanation = getattr(gate1, "metadata", {}).get(
                "explanation", "Blocked by semantic guardrail"
            )
            total_ms = round((time.time() - t0) * 1000)
            blocked_response = f"🚫 {explanation}"
            emitter.complete(blocked=True, total_ms=total_ms, response=blocked_response)
            _append_trace_log(
                customer_id,
                {
                    "id": trace_id,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "user_message": user_message,
                    "response_preview": f"Blocked: {explanation}",
                    "blocked": True,
                    "duration_ms": total_ms,
                    "trace": trace,
                },
            )
            return jsonify(
                {
                    "response": f"🚫 {explanation}",
                    "blocked": True,
                    "trace": trace,
                    "trace_id": trace_id,
                    "duration_ms": total_ms,
                }
            )

        protected_message = getattr(gate1, "transformed_text", user_message)

        # ── Load KB context (pre-tokenized) ──────────────────────
        t_kb = time.time()
        kb_file = KB_DIR / f"{customer_id}.txt"
        protected_context = ""
        if kb_file.exists():
            protected_context = kb_file.read_text().strip()
            trace.append(
                {
                    "step": "KB File Retrieval",
                    "duration_ms": round((time.time() - t_kb) * 1000),
                    "file": kb_file.name,
                    "chars": len(protected_context),
                    "preview": protected_context[:400],
                }
            )
            emitter.kb_retrieval(
                {
                    "duration_ms": round((time.time() - t_kb) * 1000),
                    "file": kb_file.name,
                    "chars": len(protected_context),
                    "preview": protected_context[:400],
                }
            )
        else:
            kb_miss = {
                "duration_ms": round((time.time() - t_kb) * 1000),
                "error": f"Not found: {customer_id}.txt",
            }
            trace.append({"step": "KB File Retrieval", **kb_miss})
            emitter.kb_retrieval(kb_miss)

        # Register tokens for Gate 2 resolution
        if protected_context:
            from services.protegrity_guard import register_tokens_from_context

            register_tokens_from_context(protected_context)

        # ── Call LangGraph orchestrator ──────────────────────────
        os.environ["ORCHESTRATOR"] = "langgraph"

        history = _get_history(customer_id)

        t_orch = time.time()
        from orchestrators import ask

        result = ask(
            protected_message,
            customer_id=customer_id,
            conversation_history=history[-20:] if history else None,
            protected_context=protected_context,
        )
        trace.append(
            {
                "step": "LangGraph Orchestrator",
                "duration_ms": round((time.time() - t_orch) * 1000),
                "orchestrator": "langgraph",
                "sub_trace": result.trace,
                "response_preview": result.answer[:500],
            }
        )
        emitter.orchestrator(
            {
                "duration_ms": round((time.time() - t_orch) * 1000),
                "orchestrator": "langgraph",
                "sub_trace": result.trace,
                "response_preview": result.answer[:500],
            }
        )

        raw_answer = result.answer

        # ── Gate 2: Unprotect output ─────────────────────────────
        t_g2 = time.time()
        gate2 = guard.gate2_output(raw_answer, restore=True)
        final_answer = getattr(gate2, "transformed_text", raw_answer)
        trace.append(
            {
                "step": "Gate 2 — Output Unprotection",
                "duration_ms": round((time.time() - t_g2) * 1000),
                "raw_response": raw_answer,
                "final_response": final_answer,
            }
        )
        emitter.gate2(
            raw_response=raw_answer,
            final_response=final_answer,
            duration_ms=round((time.time() - t_g2) * 1000),
        )

        # ── Update history ───────────────────────────────────────
        history.append({"role": "user", "content": protected_message})
        history.append({"role": "assistant", "content": raw_answer})
        _save_history(customer_id)

        total_ms = round((time.time() - t0) * 1000)
        emitter.complete(blocked=False, total_ms=total_ms, response=final_answer)
        _append_trace_log(
            customer_id,
            {
                "id": trace_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "user_message": user_message,
                "protected_message": protected_message,
                "response_preview": final_answer[:300],
                "blocked": False,
                "duration_ms": total_ms,
                "trace": trace,
            },
        )

        return jsonify(
            {
                "response": final_answer,
                "blocked": False,
                "trace": trace,
                "trace_id": trace_id,
                "duration_ms": total_ms,
            }
        )

    except Exception as e:
        log.exception("Chat error")
        return jsonify({"error": str(e), "trace": trace, "trace_id": trace_id}), 500


@app.route("/bank/api/chat/clear", methods=["POST"])
@_login_required
def api_chat_clear():
    """Clear chat history for the logged-in customer."""
    customer_id = session["customer_id"]
    key = _history_key(customer_id)
    _chat_histories[key] = []
    _save_history(customer_id)
    return jsonify({"status": "ok"})


@app.route("/bank/api/traces")
@_login_required
def api_traces():
    """Return pipeline trace logs for the logged-in customer."""
    customer_id = session["customer_id"]
    return jsonify({"traces": _trace_logs.get(customer_id, [])})


@app.route("/bank/api/traces/clear", methods=["POST"])
@_login_required
def api_traces_clear():
    """Clear pipeline trace logs for the logged-in customer."""
    customer_id = session["customer_id"]
    _trace_logs[customer_id] = []
    return jsonify({"status": "ok"})


# ── API: Pre-prompts ─────────────────────────────────────────────────

PRE_PROMPTS = [
    "Show my personal details",
    "What accounts do I have?",
    "What credit cards do I have?",
    "List my recent transactions",
    "What loans do I have and their status?",
    "What is my total balance across all accounts?",
    "Show my reward points",
]


@app.route("/bank/api/prompts")
@_login_required
def api_prompts():
    return jsonify({"prompts": PRE_PROMPTS})


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("BUSINESS_PORT", 5003))
    app.run(host="0.0.0.0", port=port, debug=True)
