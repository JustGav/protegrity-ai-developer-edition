"""FlowObserverApp — Realtime chat pipeline observer for Business + Technical portals."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from services.pipeline_events import clear_events, get_events_since, get_recent_events, init_db

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(APP_DIR / "static"),
)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "flow-observer-portal-secret-key-2026"
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

USERS_FILE = PROJECT_ROOT / "config" / "users.json"
with open(USERS_FILE) as _uf:
    TECH_USERS = json.load(_uf)

init_db()


def _login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


@app.route("/observe/")
def index():
    return redirect(url_for("dashboard")) if "username" in session else redirect(url_for("login"))


@app.route("/observe/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = TECH_USERS.get(username)
        if user and user["password_hash"] == hashlib.sha256(password.encode()).hexdigest():
            session["username"] = username
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        error = "Invalid credentials."
    return render_template("login.html", error=error)


@app.route("/observe/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/observe/dashboard")
@_login_required
def dashboard():
    return render_template(
        "dashboard.html",
        username=session["username"],
        role=session["role"],
    )


@app.route("/observe/api/events")
@_login_required
def api_events():
    since = int(request.args.get("since", 0))
    if since:
        events = get_events_since(since)
    else:
        events = get_recent_events(200)
    return jsonify({"events": events})


@app.route("/observe/api/stream")
@_login_required
def api_stream():
    since = int(request.args.get("since", 0))

    def generate():
        last_id = since
        backlog = get_events_since(last_id) if last_id else get_recent_events(200)
        for event in backlog:
            last_id = max(last_id, event["id"])
            yield f"data: {json.dumps(event)}\n\n"
        while True:
            new_events = get_events_since(last_id)
            for event in new_events:
                last_id = event["id"]
                yield f"data: {json.dumps(event)}\n\n"
            yield ": keepalive\n\n"
            time.sleep(0.4)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/observe/api/clear", methods=["POST"])
@_login_required
def api_clear():
    clear_events()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("OBSERVER_PORT", 5004))
    app.run(host="0.0.0.0", port=port, debug=False)
