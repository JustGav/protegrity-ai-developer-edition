"""Banking data service — reads customer data from PostgreSQL.

Replaced the original JSON-file backend with a PostgreSQL connection pool
(db.connection).  All query methods have the same public signatures so the
rest of the application is unaffected.

Fallback: if the database is unreachable at startup the service transparently
falls back to the JSON files so local development without Postgres still works.
"""
from __future__ import annotations
import json, hashlib, logging
from pathlib import Path
from typing import Optional

from services.protegrity_guard import _strip_pii_tags

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "banking_data"
CUSTOMERS_FILE = DATA_DIR / "customers_protected.json"

# Lazy-loaded guard reference for unprotecting tokenised fields
_guard = None


def _get_guard():
    global _guard
    if _guard is None:
        try:
            from services.protegrity_guard import get_guard
            _guard = get_guard()
        except Exception as e:
            log.warning("Could not load protegrity_guard: %s", e)
    return _guard


def _unprotect(text: str) -> str:
    guard = _get_guard()
    if guard is not None:
        try:
            result = guard.find_and_unprotect(text)
            return result.transformed_text
        except Exception as e:
            log.warning("find_and_unprotect failed: %s — stripping tags", e)
    return _strip_pii_tags(text)


# ── Database helper ───────────────────────────────────────────────────

def _get_db_conn():
    """Return a db connection context-manager, or None if unavailable."""
    try:
        from db.connection import get_connection
        return get_connection
    except Exception as exc:
        log.debug("db.connection unavailable: %s", exc)
        return None


# ── Service class ─────────────────────────────────────────────────────

class BankingService:
    """Provides customer data queries backed by PostgreSQL.

    Falls back to JSON files if the database is not reachable (e.g. during
    local development without Docker Compose).
    """

    def __init__(self):
        self._db_available: bool = self._check_db()
        if not self._db_available:
            # Load JSON files into memory as fallback
            self._json_customers: dict[str, dict] = {}
            self._load_json_fallback()

    # ── Internal helpers ──────────────────────────────────────────────

    def _check_db(self) -> bool:
        get_conn = _get_db_conn()
        if get_conn is None:
            return False
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM customers LIMIT 1")
            log.info("[BankingService] PostgreSQL backend active.")
            return True
        except Exception as exc:
            log.warning("[BankingService] PostgreSQL not available (%s) — using JSON fallback.", exc)
            return False

    def _load_json_fallback(self):
        src = CUSTOMERS_FILE if CUSTOMERS_FILE.exists() else DATA_DIR / "customers.json"
        if src.exists():
            with open(src) as f:
                for c in json.load(f):
                    self._json_customers[c["customer_id"]] = c
            log.info("[BankingService] JSON fallback: loaded %d customers from %s",
                     len(self._json_customers), src.name)

    # ── Public API ────────────────────────────────────────────────────

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        pw_hash = hashlib.sha256(password.encode()).hexdigest()

        if self._db_available:
            return self._authenticate_db(username, pw_hash)
        return self._authenticate_json(username, pw_hash)

    def _authenticate_db(self, username: str, pw_hash: str) -> Optional[dict]:
        get_conn = _get_db_conn()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT customer_id, name FROM customers WHERE username = %s AND password_hash = %s",
                    (username, pw_hash),
                )
                row = cur.fetchone()
        if not row:
            return None
        customer_id, raw_name = row
        display_name = _unprotect(raw_name) if raw_name and "[" in raw_name else (raw_name or "Customer")
        return {"customer_id": customer_id, "name": display_name}

    def _authenticate_json(self, username: str, pw_hash: str) -> Optional[dict]:
        for c in self._json_customers.values():
            if c.get("username") == username and c.get("password_hash") == pw_hash:
                raw_name = c.get("name", "Customer")
                display_name = _unprotect(raw_name) if "[" in raw_name else raw_name
                return {"customer_id": c["customer_id"], "name": display_name}
        return None

    def get_all_customers(self) -> list[dict]:
        if self._db_available:
            return self._get_all_customers_db()
        return list(self._json_customers.values())

    def _get_all_customers_db(self) -> list[dict]:
        get_conn = _get_db_conn()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM customers ORDER BY customer_id")
                return [row[0] for row in cur.fetchall()]

    def get_customer(self, customer_id: str) -> dict | None:
        if self._db_available:
            return self._get_customer_db(customer_id)
        return self._json_customers.get(customer_id)

    def _get_customer_db(self, customer_id: str) -> dict | None:
        get_conn = _get_db_conn()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM customers WHERE customer_id = %s", (customer_id,))
                row = cur.fetchone()
        return row[0] if row else None

    def get_account_summary(self, customer_id: str) -> Optional[dict]:
        if self._db_available:
            return self._get_account_summary_db(customer_id)
        return self._get_account_summary_json(customer_id)

    def _get_account_summary_db(self, customer_id: str) -> Optional[dict]:
        get_conn = _get_db_conn()
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Customer name
                cur.execute("SELECT name FROM customers WHERE customer_id = %s", (customer_id,))
                row = cur.fetchone()
                if not row:
                    return None
                raw_name = row[0] or ""
                display_name = _unprotect(raw_name) if "[" in raw_name else raw_name

                # Accounts
                cur.execute(
                    "SELECT account_id, account_number, type, balance, currency, status "
                    "FROM accounts WHERE customer_id = %s ORDER BY account_id",
                    (customer_id,),
                )
                accounts = []
                for account_id, acct_num, atype, balance, currency, status in cur.fetchall():
                    acct_num = acct_num or ""
                    clear_num = _unprotect(acct_num) if "[" in acct_num else acct_num
                    accounts.append({
                        "account_id": account_id,
                        "account_number_masked": "****" + clear_num[-4:],
                        "type": atype,
                        "balance": float(balance) if balance is not None else 0.0,
                        "currency": currency or "USD",
                        "status": status,
                    })

                # Credit cards
                cur.execute(
                    "SELECT card_id, card_number, card_type, card_tier, credit_limit, "
                    "       current_balance, available_credit, reward_points, status, expiration "
                    "FROM credit_cards WHERE customer_id = %s ORDER BY card_id",
                    (customer_id,),
                )
                cards = []
                for (card_id, card_num, card_type, card_tier, credit_limit,
                     current_balance, available_credit, reward_points, status, expiration) in cur.fetchall():
                    card_num = card_num or ""
                    clear_card = _unprotect(card_num) if "[" in card_num else card_num
                    cards.append({
                        "card_id": card_id,
                        "last_four": clear_card[-4:],
                        "card_type": card_type,
                        "card_tier": card_tier,
                        "credit_limit": float(credit_limit) if credit_limit is not None else 0.0,
                        "current_balance": float(current_balance) if current_balance is not None else 0.0,
                        "available_credit": float(available_credit) if available_credit is not None else 0.0,
                        "reward_points": reward_points or 0,
                        "status": status,
                        "expiration": expiration,
                    })

                # Recent transactions (last 20)
                cur.execute(
                    "SELECT transaction_id, account_id, date, category, merchant, "
                    "       amount, type, description, status "
                    "FROM transactions WHERE customer_id = %s "
                    "ORDER BY date DESC LIMIT 20",
                    (customer_id,),
                )
                txns = []
                for (txn_id, acct_id, date, category, merchant,
                     amount, ttype, description, tstatus) in cur.fetchall():
                    txns.append({
                        "transaction_id": txn_id,
                        "account_id": acct_id,
                        "date": date.isoformat() if date else None,
                        "category": category,
                        "merchant": merchant,
                        "amount": float(amount) if amount is not None else 0.0,
                        "type": ttype,
                        "description": description,
                        "status": tstatus,
                    })

                # Contracts — stored in JSONB data column
                cur.execute("SELECT data->'contracts' FROM customers WHERE customer_id = %s", (customer_id,))
                row = cur.fetchone()
                contracts = row[0] if row and row[0] else []

        return {
            "customer_id": customer_id,
            "name": display_name,
            "accounts": accounts,
            "credit_cards": cards,
            "contracts": contracts,
            "recent_transactions": txns,
        }

    def _get_account_summary_json(self, customer_id: str) -> Optional[dict]:
        c = self._json_customers.get(customer_id)
        if not c:
            return None
        raw_name = c.get("name", "")
        display_name = _unprotect(raw_name) if "[" in raw_name else raw_name
        accounts = []
        for a in c.get("accounts", []):
            acct_num = a.get("account_number", "")
            clear_num = _unprotect(acct_num) if "[" in acct_num else acct_num
            accounts.append({
                "account_id": a["account_id"],
                "account_number_masked": "****" + clear_num[-4:],
                "type": a["type"],
                "balance": a["balance"],
                "currency": a.get("currency", "USD"),
                "status": a["status"],
            })
        cards = []
        for cc in c.get("credit_cards", []):
            card_num = cc.get("card_number", "")
            clear_card = _unprotect(card_num) if "[" in card_num else card_num
            cards.append({
                "card_id": cc["card_id"],
                "last_four": clear_card[-4:],
                "card_type": cc["card_type"],
                "card_tier": cc["card_tier"],
                "credit_limit": cc["credit_limit"],
                "current_balance": cc["current_balance"],
                "available_credit": cc["available_credit"],
                "reward_points": cc["reward_points"],
                "status": cc["status"],
                "expiration": cc["expiration"],
            })
        txns = sorted(c.get("transactions", []), key=lambda t: t["date"], reverse=True)
        return {
            "customer_id": customer_id,
            "name": display_name,
            "accounts": accounts,
            "credit_cards": cards,
            "contracts": c.get("contracts", []),
            "recent_transactions": txns[:20],
        }


_service_instance = None


def get_banking_service() -> BankingService:
    global _service_instance
    if _service_instance is None:
        _service_instance = BankingService()
    return _service_instance