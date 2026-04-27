#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# docker/entrypoint.sh
#
# Container entrypoint for both TechnicalApp and BusinessCustomerApp.
# 1. Waits until the Protegrity classification_service is reachable.
# 2. Waits until PostgreSQL is ready, then seeds data if the table is empty.
# 3. Starts the appropriate Flask app based on APP_TYPE env var.
#
# Environment variables:
#   APP_TYPE           technical | business  (required)
#   PROTEGRITY_HOST    http://classification_service:8050  (default)
#   DB_HOST            banking_postgres  (default)
#   DB_PORT            5432             (default)
#   TECH_PORT          5002  (default)
#   BUSINESS_PORT      5003  (default)
#   PTY_WAIT_TIMEOUT   120   seconds (default)
#   DB_WAIT_TIMEOUT    60    seconds (default)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_TYPE="${APP_TYPE:-technical}"
PROTEGRITY_HOST="${PROTEGRITY_HOST:-http://classification_service:8050}"
PTY_WAIT_TIMEOUT="${PTY_WAIT_TIMEOUT:-120}"
DB_HOST="${DB_HOST:-banking_postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_WAIT_TIMEOUT="${DB_WAIT_TIMEOUT:-60}"
WAIT_INTERVAL=5

# ── Helper ────────────────────────────────────────────────────────────
log()  { echo "[entrypoint] $*"; }
warn() { echo "[entrypoint] WARNING: $*" >&2; }

# ── Wait for Protegrity classification service ────────────────────────
log "Checking Protegrity classification service at ${PROTEGRITY_HOST} ..."

_pty_host="${PROTEGRITY_HOST#http://}"
_pty_host="${_pty_host#https://}"
_pty_hostname="${_pty_host%%:*}"
_pty_port="${_pty_host##*:}"
[ "${_pty_port}" = "${_pty_hostname}" ] && _pty_port="8050"

elapsed=0
until nc -z -w 3 "${_pty_hostname}" "${_pty_port}" 2>/dev/null; do
    if [ "${elapsed}" -ge "${PTY_WAIT_TIMEOUT}" ]; then
        warn "Protegrity not reachable after ${PTY_WAIT_TIMEOUT}s — starting in degraded mode."
        break
    fi
    log "Protegrity not ready yet — retrying in ${WAIT_INTERVAL}s (${elapsed}/${PTY_WAIT_TIMEOUT}s elapsed) ..."
    sleep "${WAIT_INTERVAL}"
    elapsed=$((elapsed + WAIT_INTERVAL))
done
[ "${elapsed}" -lt "${PTY_WAIT_TIMEOUT}" ] && log "Protegrity is reachable."

# ── Wait for PostgreSQL ───────────────────────────────────────────────
log "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT} ..."
elapsed=0
until nc -z -w 3 "${DB_HOST}" "${DB_PORT}" 2>/dev/null; do
    if [ "${elapsed}" -ge "${DB_WAIT_TIMEOUT}" ]; then
        warn "PostgreSQL not reachable after ${DB_WAIT_TIMEOUT}s — banking service will use JSON fallback."
        break
    fi
    log "PostgreSQL not ready yet — retrying in ${WAIT_INTERVAL}s (${elapsed}/${DB_WAIT_TIMEOUT}s elapsed) ..."
    sleep "${WAIT_INTERVAL}"
    elapsed=$((elapsed + WAIT_INTERVAL))
done

if nc -z -w 3 "${DB_HOST}" "${DB_PORT}" 2>/dev/null; then
    log "PostgreSQL is reachable."

    # Only the technical-app container runs the seed to avoid a race condition
    # when both containers start at the same time and both try to insert data.
    if [ "${APP_TYPE}" = "technical" ]; then
        ROW_COUNT=$(python - <<'PYEOF'
import os, sys
try:
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "banking_postgres"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "protegrity"),
        user=os.getenv("DB_USER", "protegrity"),
        password=os.getenv("DB_PASSWORD", "protegrity"),
        connect_timeout=10,
    )
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM customers")
    print(cur.fetchone()[0])
    conn.close()
except Exception as e:
    print("0")
PYEOF
)
        if [ "${ROW_COUNT}" = "0" ]; then
            log "Database is empty — seeding customer data ..."
            cd /app
            python db/seed.py && log "Seed complete." || warn "Seed failed — check db/seed.py logs."
        else
            log "Database already contains ${ROW_COUNT} customer(s) — skipping seed."
        fi

        # ── Seed KùzuDB knowledge graph ───────────────────────────────
        log "Checking KùzuDB knowledge graph ..."
        cd /app
        # Force read-write for the check and seed: KUZU_READ_ONLY=true is set for Flask
        # (after seeding is done) but the entrypoint must open the DB in write mode.
        KG_STATUS=$(KUZU_READ_ONLY=false python - <<'PYEOF'
import os, sys, json
os.environ["KUZU_READ_ONLY"] = "false"
sys.path.insert(0, "/app")
try:
    from common.knowledge_graph import _conn, _create_schema, _query
    _create_schema()
    rows = _query("MATCH (n:Customer) RETURN COUNT(n) AS cnt")
    db_count = rows[0]["cnt"] if rows else 0

    # Count expected customers from the source JSON
    data_file = "/app/banking_data/customers_protected.json"
    fallback   = "/app/banking_data/customers.json"
    src = data_file if os.path.exists(data_file) else fallback
    with open(src) as f:
        expected = len(json.load(f))

    if db_count == 0:
        print("empty")
    elif db_count < expected:
        print(f"partial:{db_count}/{expected}")
    else:
        print("ok")
except Exception as e:
    print("empty")
PYEOF
)
        case "${KG_STATUS}" in
            ok)
                log "KùzuDB graph is fully populated — skipping seed." ;;
            empty)
                log "KùzuDB graph is empty — seeding ..."
                KUZU_READ_ONLY=false python db/seed_kuzu.py && log "KùzuDB seed complete." || warn "KùzuDB seed failed — check db/seed_kuzu.py logs." ;;
            partial:*)
                log "KùzuDB graph is incomplete (${KG_STATUS#partial:}) — rebuilding ..."
                KUZU_READ_ONLY=false python db/seed_kuzu.py --rebuild && log "KùzuDB rebuild complete." || warn "KùzuDB rebuild failed — check db/seed_kuzu.py logs." ;;
        esac
    fi
fi

# ── Launch the correct app ────────────────────────────────────────────
cd /app

case "${APP_TYPE}" in
    technical)
        PORT="${TECH_PORT:-5002}"
        log "Starting TechnicalApp on port ${PORT} ..."
        exec python TechnicalApp/run.py
        ;;

    business)
        PORT="${BUSINESS_PORT:-5003}"
        log "Starting BusinessCustomerApp on port ${PORT} ..."
        exec python BusinessCustomerApp/run.py
        ;;

    *)
        echo "[entrypoint] ERROR: Unknown APP_TYPE='${APP_TYPE}'. Must be 'technical' or 'business'." >&2
        exit 1
        ;;
esac
