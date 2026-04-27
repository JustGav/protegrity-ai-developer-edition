#!/usr/bin/env python3
"""
db/seed.py — Load customer data from JSON into PostgreSQL.

Reads banking_data/customers_protected.json (falls back to customers.json)
and upserts all rows into the database.

Usage:
    python db/seed.py              # seed with default .env settings
    python db/seed.py --check      # only report row counts, do not insert
    python db/seed.py --truncate   # truncate tables before seeding
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Allow running from project root or from within db/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from db.connection import get_connection  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed")

DATA_DIR = PROJECT_ROOT / "banking_data"


def _find_data_file() -> Path:
    protected = DATA_DIR / "customers_protected.json"
    if protected.exists():
        return protected
    fallback = DATA_DIR / "customers.json"
    if fallback.exists():
        log.warning("customers_protected.json not found — falling back to customers.json")
        return fallback
    raise FileNotFoundError(f"No customer data file found in {DATA_DIR}")


def seed(truncate: bool = False) -> None:
    data_file = _find_data_file()
    log.info("Loading data from %s", data_file.name)
    with open(data_file) as f:
        customers: list[dict] = json.load(f)
    log.info("Found %d customers", len(customers))

    with get_connection() as conn:
        with conn.cursor() as cur:
            if truncate:
                log.info("Truncating tables ...")
                cur.execute("TRUNCATE transactions, credit_cards, accounts, customers RESTART IDENTITY CASCADE")

            for c in customers:
                cid = c["customer_id"]

                # ── customers ──────────────────────────────────────
                cur.execute(
                    """
                    INSERT INTO customers
                        (customer_id, username, password_hash, name, dob, ssn,
                         email, phone, address, data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        username      = EXCLUDED.username,
                        password_hash = EXCLUDED.password_hash,
                        name          = EXCLUDED.name,
                        dob           = EXCLUDED.dob,
                        ssn           = EXCLUDED.ssn,
                        email         = EXCLUDED.email,
                        phone         = EXCLUDED.phone,
                        address       = EXCLUDED.address,
                        data          = EXCLUDED.data
                    """,
                    (
                        cid,
                        c.get("username"),
                        c.get("password_hash"),
                        c.get("name"),
                        c.get("dob"),
                        c.get("ssn"),
                        c.get("email"),
                        c.get("phone"),
                        c.get("address"),
                        json.dumps(c),
                    ),
                )

                # ── accounts ───────────────────────────────────────
                for a in c.get("accounts", []):
                    cur.execute(
                        """
                        INSERT INTO accounts
                            (account_id, customer_id, account_number, routing_number,
                             type, balance, currency, opened_date, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (account_id) DO UPDATE SET
                            balance = EXCLUDED.balance,
                            status  = EXCLUDED.status
                        """,
                        (
                            a["account_id"],
                            cid,
                            a.get("account_number"),
                            a.get("routing_number"),
                            a.get("type"),
                            a.get("balance"),
                            a.get("currency", "USD"),
                            a.get("opened_date") or None,
                            a.get("status"),
                        ),
                    )

                # ── credit_cards ───────────────────────────────────
                for cc in c.get("credit_cards", []):
                    cur.execute(
                        """
                        INSERT INTO credit_cards
                            (card_id, customer_id, card_number, card_type, card_tier,
                             expiration, cvv, credit_limit, current_balance,
                             available_credit, status, reward_points)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (card_id) DO UPDATE SET
                            current_balance  = EXCLUDED.current_balance,
                            available_credit = EXCLUDED.available_credit,
                            reward_points    = EXCLUDED.reward_points,
                            status           = EXCLUDED.status
                        """,
                        (
                            cc["card_id"],
                            cid,
                            cc.get("card_number"),
                            cc.get("card_type"),
                            cc.get("card_tier"),
                            cc.get("expiration"),
                            cc.get("cvv"),
                            cc.get("credit_limit"),
                            cc.get("current_balance"),
                            cc.get("available_credit"),
                            cc.get("status"),
                            cc.get("reward_points"),
                        ),
                    )

                # ── transactions ───────────────────────────────────
                for t in c.get("transactions", []):
                    cur.execute(
                        """
                        INSERT INTO transactions
                            (transaction_id, customer_id, account_id, date,
                             category, merchant, amount, type, description, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (transaction_id) DO NOTHING
                        """,
                        (
                            t["transaction_id"],
                            cid,
                            t.get("account_id"),
                            t.get("date"),
                            t.get("category"),
                            t.get("merchant"),
                            t.get("amount"),
                            t.get("type"),
                            t.get("description"),
                            t.get("status"),
                        ),
                    )

    # Summary
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM customers")
            nc = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM accounts")
            na = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM credit_cards")
            ncc = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM transactions")
            nt = cur.fetchone()[0]

    log.info("Seed complete — customers=%d  accounts=%d  credit_cards=%d  transactions=%d",
             nc, na, ncc, nt)


def check() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in ("customers", "accounts", "credit_cards", "transactions"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                log.info("  %-20s %d rows", table, cur.fetchone()[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed banking data into PostgreSQL")
    parser.add_argument("--check",    action="store_true", help="Report counts only")
    parser.add_argument("--truncate", action="store_true", help="Truncate before seeding")
    args = parser.parse_args()

    if args.check:
        check()
    else:
        seed(truncate=args.truncate)
