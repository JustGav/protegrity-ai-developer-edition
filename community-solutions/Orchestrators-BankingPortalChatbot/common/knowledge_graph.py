"""
Knowledge Graph backed by KùzuDB (embedded graph database).

Node tables : Customer, Account, CreditCard, Transaction, Loan
Rel tables  : HAS_ACCOUNT, HAS_CARD, HAS_TRANSACTION,
              ACCOUNT_TRANSACTION, HAS_LOAN

All PII fields stored as Protegrity tokens — the graph never contains real PII.

Public API (unchanged from the previous NetworkX implementation):
    get_graph()              → KuzuGraphWrapper
                               (.number_of_nodes(), .number_of_edges())
    query_customer(cid)      → Dict with customer data + relations dict
    search_nodes(q, type)    → List of matching node dicts
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Path configuration ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "banking_data" / "customers_protected.json"
_FALLBACK_FILE = PROJECT_ROOT / "banking_data" / "customers.json"

# Kuzu 0.11+ stores the database as a single file (not a directory).
# KUZU_DB_PATH should point to the FILE (e.g. ./kuzu_data/banking.kuzu).
# The parent directory is created automatically if it doesn't exist.
KUZU_DB_PATH = Path(os.getenv("KUZU_DB_PATH", str(PROJECT_ROOT / "kuzu_data" / "banking.kuzu")))

# Open the database in read-only mode when KUZU_READ_ONLY=true.
# Set this on any container that should NOT seed the graph (e.g. business-app).
_KUZU_READ_ONLY = os.getenv("KUZU_READ_ONLY", "false").lower() == "true"

# ── Schema DDL ─────────────────────────────────────────────────────────
_DDL = """
CREATE NODE TABLE IF NOT EXISTS Customer(
    customer_id  STRING,
    name         STRING,
    email        STRING,
    phone        STRING,
    ssn          STRING,
    address      STRING,
    dob          STRING,
    PRIMARY KEY (customer_id)
);

CREATE NODE TABLE IF NOT EXISTS Account(
    account_id     STRING,
    account_number STRING,
    routing_number STRING,
    acct_type      STRING,
    balance        DOUBLE,
    currency       STRING,
    opened_date    STRING,
    status         STRING,
    PRIMARY KEY (account_id)
);

CREATE NODE TABLE IF NOT EXISTS CreditCard(
    card_id          STRING,
    card_number      STRING,
    card_type        STRING,
    card_tier        STRING,
    expiration       STRING,
    credit_limit     DOUBLE,
    current_balance  DOUBLE,
    available_credit DOUBLE,
    reward_points    INT64,
    status           STRING,
    PRIMARY KEY (card_id)
);

CREATE NODE TABLE IF NOT EXISTS Transaction(
    transaction_id STRING,
    date           STRING,
    amount         DOUBLE,
    category       STRING,
    merchant       STRING,
    txn_type       STRING,
    status         STRING,
    account_id     STRING,
    PRIMARY KEY (transaction_id)
);

CREATE NODE TABLE IF NOT EXISTS Loan(
    contract_id        STRING,
    loan_type          STRING,
    remaining_balance  DOUBLE,
    status             STRING,
    PRIMARY KEY (contract_id)
);

CREATE REL TABLE IF NOT EXISTS HAS_ACCOUNT       (FROM Customer    TO Account);
CREATE REL TABLE IF NOT EXISTS HAS_CARD          (FROM Customer    TO CreditCard);
CREATE REL TABLE IF NOT EXISTS HAS_TRANSACTION   (FROM Customer    TO Transaction);
CREATE REL TABLE IF NOT EXISTS ACCOUNT_TRANSACTION(FROM Account    TO Transaction);
CREATE REL TABLE IF NOT EXISTS HAS_LOAN          (FROM Customer    TO Loan);
"""

# ── Thread-local connections ───────────────────────────────────────────
# The Database object is shared; each thread gets its own Connection.
_db: Any = None          # kuzu.Database singleton
_tl = threading.local()  # thread-local Connection storage
_db_lock = threading.Lock()


def _get_db():
    """Return (or lazily create) the shared KùzuDB Database object."""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                try:
                    import kuzu
                    KUZU_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    _db = kuzu.Database(str(KUZU_DB_PATH), read_only=_KUZU_READ_ONLY)
                    log.info("[KuzuDB] Opened database at %s", KUZU_DB_PATH)
                except ImportError:
                    log.error("[KuzuDB] kuzu package not installed — pip install kuzu")
                    raise
    return _db


def _conn():
    """Return a per-thread Connection, creating it on first use."""
    if not hasattr(_tl, "conn") or _tl.conn is None:
        import kuzu
        _tl.conn = kuzu.Connection(_get_db())
    return _tl.conn


def _query(cypher: str, params: Optional[dict] = None) -> List[Dict]:
    """Execute a Cypher query and return results as a list of dicts."""
    conn = _conn()
    result = conn.execute(cypher, parameters=params or {})
    columns = result.get_column_names()
    rows = []
    while result.has_next():
        row = result.get_next()
        rows.append(dict(zip(columns, row)))
    return rows


def _is_empty() -> bool:
    """Return True if the Customer table has no rows (database not seeded)."""
    try:
        rows = _query("MATCH (n:Customer) RETURN COUNT(n) AS cnt")
        return (rows[0]["cnt"] if rows else 0) == 0
    except Exception:
        return True


# ── Schema creation & seeding ──────────────────────────────────────────

def _create_schema() -> None:
    """Create all node and rel tables (idempotent — uses IF NOT EXISTS)."""
    conn = _conn()
    for stmt in _DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except Exception as exc:
                log.debug("DDL stmt info: %s — %s", stmt[:60], exc)


def build_graph() -> None:
    """Build the KùzuDB graph from customers_protected.json (or fallback).

    Idempotent — skips seeding if Customer rows already exist.
    """
    _create_schema()

    if not _is_empty():
        log.info("[KuzuDB] Graph already populated — skipping build.")
        return

    src = DATA_FILE if DATA_FILE.exists() else _FALLBACK_FILE
    if not src.exists():
        log.error("[KuzuDB] No customer data file found at %s", src)
        return

    with open(src) as f:
        customers = json.load(f)
    log.info("[KuzuDB] Seeding graph from %s (%d customers) …", src.name, len(customers))

    conn = _conn()

    for cust in customers:
        cid = cust["customer_id"]

        # Customer node
        conn.execute(
            "MERGE (c:Customer {customer_id: $cid}) "
            "SET c.name=$name, c.email=$email, c.phone=$phone, "
            "    c.ssn=$ssn, c.address=$address, c.dob=$dob",
            parameters={
                "cid":     cid,
                "name":    cust.get("name", ""),
                "email":   cust.get("email", ""),
                "phone":   cust.get("phone", ""),
                "ssn":     cust.get("ssn", ""),
                "address": cust.get("address", ""),
                "dob":     cust.get("dob", ""),
            },
        )

        # Accounts
        for acct in cust.get("accounts", []):
            aid = acct.get("account_id", "")
            if not aid:
                continue
            conn.execute(
                "MERGE (a:Account {account_id: $aid}) "
                "SET a.account_number=$acct_num, a.routing_number=$routing, "
                "    a.acct_type=$atype, a.balance=$balance, "
                "    a.currency=$currency, a.opened_date=$opened, a.status=$status",
                parameters={
                    "aid":      aid,
                    "acct_num": acct.get("account_number", ""),
                    "routing":  acct.get("routing_number", ""),
                    "atype":    acct.get("type", ""),
                    "balance":  float(acct.get("balance", 0) or 0),
                    "currency": acct.get("currency", "USD"),
                    "opened":   str(acct.get("opened_date", "")),
                    "status":   acct.get("status", ""),
                },
            )
            conn.execute(
                "MATCH (c:Customer {customer_id: $cid}), (a:Account {account_id: $aid}) "
                "MERGE (c)-[:HAS_ACCOUNT]->(a)",
                parameters={"cid": cid, "aid": aid},
            )

        # Credit cards
        for card in cust.get("credit_cards", []):
            card_id = card.get("card_id", "")
            if not card_id:
                continue
            conn.execute(
                "MERGE (cc:CreditCard {card_id: $card_id}) "
                "SET cc.card_number=$card_num, cc.card_type=$card_type, "
                "    cc.card_tier=$card_tier, cc.expiration=$expiry, "
                "    cc.credit_limit=$limit, cc.current_balance=$balance, "
                "    cc.available_credit=$avail, cc.reward_points=$points, "
                "    cc.status=$status",
                parameters={
                    "card_id":   card_id,
                    "card_num":  card.get("card_number", ""),
                    "card_type": card.get("card_type", ""),
                    "card_tier": card.get("card_tier", ""),
                    "expiry":    card.get("expiration", ""),
                    "limit":     float(card.get("credit_limit", 0) or 0),
                    "balance":   float(card.get("current_balance", 0) or 0),
                    "avail":     float(card.get("available_credit", 0) or 0),
                    "points":    int(card.get("reward_points", 0) or 0),
                    "status":    card.get("status", ""),
                },
            )
            conn.execute(
                "MATCH (c:Customer {customer_id: $cid}), (cc:CreditCard {card_id: $card_id}) "
                "MERGE (c)-[:HAS_CARD]->(cc)",
                parameters={"cid": cid, "card_id": card_id},
            )

        # Transactions
        for txn in cust.get("transactions", []):
            tid = txn.get("transaction_id", "")
            if not tid:
                continue
            conn.execute(
                "MERGE (t:Transaction {transaction_id: $tid}) "
                "SET t.date=$date, t.amount=$amount, t.category=$category, "
                "    t.merchant=$merchant, t.txn_type=$ttype, "
                "    t.status=$status, t.account_id=$acct_id",
                parameters={
                    "tid":      tid,
                    "date":     str(txn.get("date", "")),
                    "amount":   float(txn.get("amount", 0) or 0),
                    "category": txn.get("category", ""),
                    "merchant": txn.get("merchant", ""),
                    "ttype":    txn.get("type", ""),
                    "status":   txn.get("status", ""),
                    "acct_id":  txn.get("account_id", ""),
                },
            )
            conn.execute(
                "MATCH (c:Customer {customer_id: $cid}), (t:Transaction {transaction_id: $tid}) "
                "MERGE (c)-[:HAS_TRANSACTION]->(t)",
                parameters={"cid": cid, "tid": tid},
            )
            # Account → Transaction edge
            acct_id = txn.get("account_id", "")
            if acct_id:
                conn.execute(
                    "MATCH (a:Account {account_id: $aid}), (t:Transaction {transaction_id: $tid}) "
                    "MERGE (a)-[:ACCOUNT_TRANSACTION]->(t)",
                    parameters={"aid": acct_id, "tid": tid},
                )

        # Contracts / Loans
        for contract in cust.get("contracts", []):
            ctr_id = contract.get("contract_id", "")
            if not ctr_id:
                continue
            conn.execute(
                "MERGE (l:Loan {contract_id: $ctr_id}) "
                "SET l.loan_type=$ltype, l.remaining_balance=$balance, l.status=$status",
                parameters={
                    "ctr_id":  ctr_id,
                    "ltype":   contract.get("type", ""),
                    "balance": float(contract.get("remaining_balance", 0) or 0),
                    "status":  contract.get("status", ""),
                },
            )
            conn.execute(
                "MATCH (c:Customer {customer_id: $cid}), (l:Loan {contract_id: $ctr_id}) "
                "MERGE (c)-[:HAS_LOAN]->(l)",
                parameters={"cid": cid, "ctr_id": ctr_id},
            )

    log.info("[KuzuDB] Graph build complete.")


# ── Public API ─────────────────────────────────────────────────────────

class KuzuGraphWrapper:
    """Thin wrapper that mimics the nx.DiGraph interface used by callers."""

    def number_of_nodes(self) -> int:
        try:
            rows = _query("MATCH (n) RETURN COUNT(n) AS cnt")
            return rows[0]["cnt"] if rows else 0
        except Exception:
            return 0

    def number_of_edges(self) -> int:
        try:
            rows = _query("MATCH ()-[r]->() RETURN COUNT(r) AS cnt")
            return rows[0]["cnt"] if rows else 0
        except Exception:
            return 0


_graph_wrapper = KuzuGraphWrapper()
_graph_initialized = False
_graph_lock = threading.Lock()


def get_graph() -> KuzuGraphWrapper:
    """Return the KuzuGraphWrapper, building the graph lazily on first call."""
    global _graph_initialized
    if not _graph_initialized:
        with _graph_lock:
            if not _graph_initialized:
                try:
                    if _KUZU_READ_ONLY:
                        _get_db()  # open the connection; skip seeding (technical-app owns that)
                    else:
                        build_graph()
                    _graph_initialized = True
                except Exception as exc:
                    log.error("[KuzuDB] Failed to initialize graph: %s", exc)
    return _graph_wrapper


def query_customer(customer_id: str) -> Dict[str, Any]:
    """Return customer node + all connected entities.

    Return format is identical to the previous NetworkX implementation
    so callers require no changes.
    """
    get_graph()  # ensure DB is seeded
    try:
        # Customer properties
        rows = _query(
            "MATCH (c:Customer {customer_id: $cid}) "
            "RETURN c.customer_id, c.name, c.email, c.phone, c.ssn, c.address, c.dob",
            {"cid": customer_id},
        )
        if not rows:
            return {}
        r = rows[0]
        data: Dict[str, Any] = {
            "customer_id": r["c.customer_id"],
            "name":        r["c.name"],
            "email":       r["c.email"],
            "phone":       r["c.phone"],
            "ssn":         r["c.ssn"],
            "address":     r["c.address"],
            "dob":         r["c.dob"],
        }

        relations: Dict[str, List] = {}

        # Accounts
        acct_rows = _query(
            "MATCH (c:Customer {customer_id: $cid})-[:HAS_ACCOUNT]->(a:Account) "
            "RETURN a.account_id, a.acct_type, a.balance, a.currency, a.status",
            {"cid": customer_id},
        )
        if acct_rows:
            relations["HAS_ACCOUNT"] = [
                {"id": r["a.account_id"], "node_type": "Account",
                 "acct_type": r["a.acct_type"], "balance": r["a.balance"],
                 "currency": r["a.currency"], "status": r["a.status"]}
                for r in acct_rows
            ]

        # Credit cards
        card_rows = _query(
            "MATCH (c:Customer {customer_id: $cid})-[:HAS_CARD]->(cc:CreditCard) "
            "RETURN cc.card_id, cc.card_type, cc.card_tier, cc.current_balance, "
            "       cc.available_credit, cc.credit_limit, cc.status",
            {"cid": customer_id},
        )
        if card_rows:
            relations["HAS_CARD"] = [
                {"id": r["cc.card_id"], "node_type": "CreditCard",
                 "card_type": r["cc.card_type"], "card_tier": r["cc.card_tier"],
                 "current_balance": r["cc.current_balance"],
                 "available_credit": r["cc.available_credit"],
                 "credit_limit": r["cc.credit_limit"], "status": r["cc.status"]}
                for r in card_rows
            ]

        # Transactions (most recent 20)
        txn_rows = _query(
            "MATCH (c:Customer {customer_id: $cid})-[:HAS_TRANSACTION]->(t:Transaction) "
            "RETURN t.transaction_id, t.category, t.amount, t.merchant, t.txn_type, "
            "       t.status, t.date "
            "ORDER BY t.date DESC LIMIT 20",
            {"cid": customer_id},
        )
        if txn_rows:
            relations["HAS_TRANSACTION"] = [
                {"id": r["t.transaction_id"], "node_type": "Transaction",
                 "category": r["t.category"], "amount": r["t.amount"],
                 "merchant": r["t.merchant"], "txn_type": r["t.txn_type"],
                 "status": r["t.status"], "date": r["t.date"]}
                for r in txn_rows
            ]

        # Loans
        loan_rows = _query(
            "MATCH (c:Customer {customer_id: $cid})-[:HAS_LOAN]->(l:Loan) "
            "RETURN l.contract_id, l.loan_type, l.remaining_balance, l.status",
            {"cid": customer_id},
        )
        if loan_rows:
            relations["HAS_LOAN"] = [
                {"id": r["l.contract_id"], "node_type": "Loan",
                 "loan_type": r["l.loan_type"],
                 "remaining_balance": r["l.remaining_balance"],
                 "status": r["l.status"]}
                for r in loan_rows
            ]

        data["relations"] = relations
        return data

    except Exception as exc:
        log.error("[KuzuDB] query_customer failed for %s: %s", customer_id, exc)
        return {}


def search_nodes(query: str, node_type: Optional[str] = None) -> List[Dict]:
    """Search graph nodes by substring match.

    Searches Customer, Account, CreditCard, and Transaction nodes.
    """
    get_graph()
    q = query.lower()
    results: List[Dict] = []

    try:
        searches = (
            [] if node_type and node_type != "Customer" else [
                ("MATCH (n:Customer) "
                 "WHERE lower(n.customer_id) CONTAINS $q OR lower(n.name) CONTAINS $q "
                 "RETURN n.customer_id AS id, 'Customer' AS node_type, n.name AS name",
                 lambda r: {"id": r["id"], "node_type": "Customer", "name": r["name"]}),
            ]
        ) + (
            [] if node_type and node_type != "Account" else [
                ("MATCH (n:Account) WHERE lower(n.account_id) CONTAINS $q "
                 "RETURN n.account_id AS id, 'Account' AS node_type, n.acct_type AS acct_type",
                 lambda r: {"id": r["id"], "node_type": "Account", "acct_type": r["acct_type"]}),
            ]
        ) + (
            [] if node_type and node_type != "CreditCard" else [
                ("MATCH (n:CreditCard) WHERE lower(n.card_id) CONTAINS $q "
                 "RETURN n.card_id AS id, 'CreditCard' AS node_type, n.card_type AS card_type",
                 lambda r: {"id": r["id"], "node_type": "CreditCard", "card_type": r["card_type"]}),
            ]
        ) + (
            [] if node_type and node_type != "Transaction" else [
                ("MATCH (n:Transaction) WHERE lower(n.transaction_id) CONTAINS $q "
                 "   OR lower(n.merchant) CONTAINS $q OR lower(n.category) CONTAINS $q "
                 "RETURN n.transaction_id AS id, 'Transaction' AS node_type, "
                 "       n.merchant AS merchant, n.category AS category",
                 lambda r: {"id": r["id"], "node_type": "Transaction",
                            "merchant": r["merchant"], "category": r["category"]}),
            ]
        )

        for cypher, mapper in searches:
            for row in _query(cypher, {"q": q}):
                results.append(mapper(row))

    except Exception as exc:
        log.error("[KuzuDB] search_nodes failed: %s", exc)

    return results


# Keep backward-compat alias — some code may call save_graph()
def save_graph() -> None:
    """No-op: KùzuDB persists automatically."""
    pass

