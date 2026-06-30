"""
CLI entry point for orchestrated pipeline.

Usage:
    ORCHESTRATOR=langgraph LLM_PROVIDER=ollama python -m orchestrators
"""

import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(_ROOT) / ".env", override=False)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from common.protegrity_gates import gate1_protect, gate2_unprotect
from config.orchestration_config import RISK_THRESHOLD, PROTEGRITY_USER
from orchestrators import ask

orch_name = os.environ.get("ORCHESTRATOR", "langgraph")
provider = os.environ.get("LLM_PROVIDER", "ollama")
print(f"\n{'='*60}")
print(f"  Orchestrator : {orch_name}")
print(f"  LLM Provider : {provider}")
print(f"{'='*60}\n")

cid = input("Customer ID [CUST-100000]: ").strip() or "CUST-100000"

while True:
    try:
        query = input("\nYou: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nBye.")
        break
    if not query or query.lower() in ("exit", "quit", "q"):
        break

    # Gate 1: protect user input
    gate1 = gate1_protect(query, risk_threshold=RISK_THRESHOLD)
    if gate1.blocked:
        print(f"\n🚫 Blocked by Gate 1 — risk {gate1.risk_score:.2f}. {gate1.guardrail_explanation}")
        continue

    # Orchestrator: protected-in, protected-out
    result = ask(gate1.protected_text, customer_id=cid)

    # Gate 2: unprotect LLM output
    gate2 = gate2_unprotect(result.answer, protegrity_user=PROTEGRITY_USER)
    final_answer = gate2.restored_text

    print(f"\n🤖 {final_answer}")
    print(f"\n   [Gate 1] risk={gate1.risk_score:.2f} | PII={gate1.pii_entities} | blocked={gate1.blocked}")
    print(f"   [Gate 2] tokens_resolved={gate2.tokens_resolved}")
