"""Shared pipeline event store for cross-process realtime observation."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "pipeline_events.db"
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_app TEXT NOT NULL,
    step TEXT NOT NULL,
    created_at REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_id ON pipeline_events(id);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_run ON pipeline_events(run_id);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def new_run_id(source_app: str) -> str:
    return f"{source_app}-{int(time.time() * 1000)}"


def publish_event(
    run_id: str,
    source_app: str,
    step: str,
    payload: dict,
) -> int | None:
    """Append a pipeline event. Returns row id or None on failure."""
    try:
        init_db()
        row = {
            "run_id": run_id,
            "source_app": source_app,
            "step": step,
            "created_at": time.time(),
            "payload": json.dumps(payload, default=str),
        }
        with _lock:
            conn = _connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO pipeline_events (run_id, source_app, step, created_at, payload)
                    VALUES (:run_id, :source_app, :step, :created_at, :payload)
                    """,
                    row,
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()
    except Exception as exc:
        log.warning("pipeline_events publish failed: %s", exc)
        return None


def get_events_since(event_id: int = 0, limit: int = 500) -> list[dict]:
    init_db()
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT id, run_id, source_app, step, created_at, payload
                FROM pipeline_events
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (event_id, limit),
            ).fetchall()
            return [_row_to_event(r) for r in rows]
        finally:
            conn.close()


def get_recent_events(limit: int = 200) -> list[dict]:
    init_db()
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT id, run_id, source_app, step, created_at, payload
                FROM pipeline_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            events = [_row_to_event(r) for r in reversed(rows)]
            return events
        finally:
            conn.close()


def clear_events() -> None:
    init_db()
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM pipeline_events")
            conn.commit()
        finally:
            conn.close()


def _row_to_event(row: sqlite3.Row) -> dict:
    payload = json.loads(row["payload"])
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "source_app": row["source_app"],
        "step": row["step"],
        "created_at": row["created_at"],
        "payload": payload,
    }
