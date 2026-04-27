"""
db/connection.py — PostgreSQL connection pool for the Banking Portal.

Reads DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD from the environment
(populated from .env via python-dotenv).

Usage:
    from db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Connection parameters from environment ────────────────────────────
_DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME", "protegrity"),
    "user":     os.getenv("DB_USER", "protegrity"),
    "password": os.getenv("DB_PASSWORD", "protegrity"),
    "connect_timeout": 10,
}

# ── Thread-safe connection pool (initialised lazily) ──────────────────
_pool: pool.ThreadedConnectionPool | None = None


def get_pool() -> pool.ThreadedConnectionPool:
    """Return (or create) the singleton connection pool."""
    global _pool
    if _pool is None or _pool.closed:
        log.info(
            "Creating PostgreSQL connection pool → %s@%s:%s/%s",
            _DB_CONFIG["user"],
            _DB_CONFIG["host"],
            _DB_CONFIG["port"],
            _DB_CONFIG["dbname"],
        )
        _pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            **_DB_CONFIG,
        )
    return _pool


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Context manager that checks out a connection from the pool and
    returns it when the block exits (commits or rolls back on error)."""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def close_pool() -> None:
    """Cleanly close all connections in the pool (call on app shutdown)."""
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
        log.info("PostgreSQL connection pool closed.")
        _pool = None
