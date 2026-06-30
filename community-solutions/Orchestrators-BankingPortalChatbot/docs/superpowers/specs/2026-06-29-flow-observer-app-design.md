# FlowObserverApp — Realtime Pipeline Observer Design

**Date:** 2026-06-29  
**Status:** Approved

## Summary

Third admin Flask app (`FlowObserverApp`, port **5004**) that live-streams chat pipeline events from BusinessCustomerApp and TechnicalApp. Uses TechnicalApp credentials (`config/users.json`), Protegrity orange UI, animated pipeline diagram plus event timeline, filterable by source app, with side-by-side Gate 1/Gate 2 views and optional full payload expansion.

## Architecture

- Shared module `services/pipeline_events.py` — SQLite-backed append-only event log (`data/pipeline_events.db`) for cross-process publishing from three Flask apps.
- `services/pipeline_emitter.py` — helper used by chat handlers to emit step events in realtime.
- FlowObserverApp — login, dashboard, SSE stream `/observe/api/stream`.

## Event Model

Steps: `run_start`, `gate1`, `kb_retrieval`, `rag`, `knowledge_graph`, `orchestrator`, `orchestrator_step`, `llm_request`, `gate2`, `run_complete`.

Each event: `{ id, run_id, source_app, step, created_at, payload }`.

## UI

- Filters: Business / Technical / All
- Checkbox: Show full payloads
- Diagram: Customer → Gate 1 → KB → Orchestrator → LLM → Gate 2 → Response
- Timeline: expandable run cards with step detail and gate side-by-sides

## Out of Scope

Non-chat traffic, config changes, demo replay button, Redis/WebSocket.
