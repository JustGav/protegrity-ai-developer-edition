"""Tests for shared pipeline event store."""
from __future__ import annotations

import pytest


@pytest.fixture()
def events_db(tmp_path, monkeypatch):
    db_file = tmp_path / "pipeline_events.db"
    monkeypatch.setattr("services.pipeline_events.DB_PATH", db_file)
    from services import pipeline_events

    pipeline_events.init_db()
    yield pipeline_events
    if db_file.exists():
        db_file.unlink()


def test_publish_and_fetch(events_db):
    run_id = events_db.new_run_id("business")
    eid = events_db.publish_event(run_id, "business", "run_start", {"user_message": "hello"})
    assert eid == 1

    events = events_db.get_events_since(0)
    assert len(events) == 1
    assert events[0]["step"] == "run_start"
    assert events[0]["payload"]["user_message"] == "hello"


def test_get_recent_events(events_db):
    run_id = events_db.new_run_id("technical")
    for step in ("run_start", "gate1", "run_complete"):
        events_db.publish_event(run_id, "technical", step, {"ok": True})

    recent = events_db.get_recent_events(10)
    assert len(recent) == 3
    assert recent[-1]["step"] == "run_complete"


def test_clear_events(events_db):
    run_id = events_db.new_run_id("business")
    events_db.publish_event(run_id, "business", "run_start", {})
    events_db.clear_events()
    assert events_db.get_recent_events() == []
