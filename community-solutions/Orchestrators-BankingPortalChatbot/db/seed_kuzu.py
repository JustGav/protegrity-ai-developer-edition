#!/usr/bin/env python3
"""
Seed KùzuDB from customers_protected.json (or fallback to customers.json).

Usage:
    python db/seed_kuzu.py           # seed (idempotent)
    python db/seed_kuzu.py --check   # print current node counts, no write
    python db/seed_kuzu.py --rebuild # drop all data and re-seed
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env early so KUZU_DB_PATH is available to knowledge_graph module
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from common.knowledge_graph import (
    _conn,
    _create_schema,
    _is_empty,
    build_graph,
    KUZU_DB_PATH,
)


def count_nodes() -> dict:
    conn = _conn()
    tables = ["Customer", "Account", "CreditCard", "Transaction", "Loan"]
    counts = {}
    for t in tables:
        result = conn.execute(f"MATCH (n:{t}) RETURN COUNT(n) AS cnt")
        while result.has_next():
            counts[t] = result.get_next()[0]
    return counts


def rebuild() -> None:
    """Drop all node/rel tables and re-seed from scratch."""
    conn = _conn()
    rels  = ["HAS_ACCOUNT", "HAS_CARD", "HAS_TRANSACTION", "ACCOUNT_TRANSACTION", "HAS_LOAN"]
    nodes = ["Customer", "Account", "CreditCard", "Transaction", "Loan"]
    for r in rels:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {r}")
        except Exception:
            pass
    for n in nodes:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {n}")
        except Exception:
            pass
    print("[seed_kuzu] All tables dropped.")
    _create_schema()
    build_graph()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed KùzuDB knowledge graph")
    parser.add_argument("--check",   action="store_true", help="Print counts only")
    parser.add_argument("--rebuild", action="store_true", help="Drop and re-seed")
    args = parser.parse_args()

    print(f"[seed_kuzu] Database path: {KUZU_DB_PATH}")

    if args.check:
        _create_schema()
        counts = count_nodes()
        for table, cnt in counts.items():
            print(f"  {table}: {cnt}")
        return

    if args.rebuild:
        rebuild()
    else:
        _create_schema()
        if _is_empty():
            build_graph()
        else:
            print("[seed_kuzu] Graph already populated — use --rebuild to re-seed.")

    counts = count_nodes()
    total = sum(counts.values())
    for table, cnt in counts.items():
        print(f"  {table}: {cnt}")
    print(f"  Total nodes: {total}")


if __name__ == "__main__":
    main()
