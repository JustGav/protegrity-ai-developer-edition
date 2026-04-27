"""
Quick smoke test — run directly without pytest.

Usage:
    cd /home/azure_usr/protegrity_ai_integrations/protegrity_demo/orchestration/BankingPortalChatbot
    python tests/smoke_test.py
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

passed = 0
failed = 0
skipped = 0


def check(label, condition, skip_reason=None):
    global passed, failed, skipped
    if skip_reason:
        print(f"  ⏭  {label} — SKIPPED ({skip_reason})")
        skipped += 1
        return
    if condition:
        print(f"  ✅ {label}")
        passed += 1
    else:
        print(f"  ❌ {label}")
        failed += 1


def main():
    global passed, failed, skipped
    print()
    print("=" * 60)
    print("  Orchestration Layer — Smoke Test")
    print("=" * 60)

    # ── 1. Config ────────────────────────────────────────────
    print("\n📋 1. orchestration_config")
    try:
        import config.orchestration_config as cfg
        check("Module imports", True)
        check(f"ORCHESTRATOR = {cfg.ORCHESTRATOR!r}", cfg.ORCHESTRATOR in ("langgraph", "crewai", "llamaindex"))
        check(f"LLM_PROVIDER = {cfg.LLM_PROVIDER!r}", cfg.LLM_PROVIDER in ("openai", "anthropic", "groq"))
        check(f"Model = {cfg.get_model_name()!r}", len(cfg.get_model_name()) > 0)
        check("Gate settings valid", 0 <= cfg.GUARDRAIL_RISK_THRESHOLD <= 1)
    except Exception as e:
        check(f"Module imports — {e}", False)

    # ── 2. Base classes ──────────────────────────────────────
    print("\n📋 2. orchestrators.base")
    try:
        from orchestrators.base import BaseOrchestrator, PipelineResult
        check("PipelineResult import", True)
        r = PipelineResult(answer="test", blocked=False)
        check("PipelineResult creation", r.answer == "test")
        check("PipelineResult defaults", r.rag_context == [] and r.kg_context == {})
    except Exception as e:
        check(f"Import — {e}", False)

    # ── 3. Gate dataclasses ──────────────────────────────────
    print("\n📋 3. common.protegrity_gates (dataclasses + skip mode)")
    try:
        from common.protegrity_gates import Gate1Result, Gate2Result, gate1_protect, gate2_unprotect
        check("Gate classes import", True)

        g1 = gate1_protect("Hello world", skip_gates=True)
        check("gate1_protect(skip=True) passthrough", g1.protected_text == "Hello world")
        check("gate1 not blocked", g1.blocked is False)

        g2 = gate2_unprotect("Hello [PERSON]X[/PERSON]", skip_gates=True)
        check("gate2_unprotect(skip=True) passthrough", g2.restored_text == "Hello [PERSON]X[/PERSON]")
    except ImportError as e:
        # services.protegrity_guard may not be available in this copy
        check("Gate classes import", None, skip_reason=f"missing dependency: {e}")

    # ── 4. Knowledge Graph (KùzuDB) ──────────────────────────
    print("\n📋 4. common.knowledge_graph")
    try:
        import common.knowledge_graph as kg
        check("Module imports", True)

        G = kg.get_graph()
        check("get_graph() returns wrapper", hasattr(G, "number_of_nodes"))
        check("graph has nodes", G.number_of_nodes() > 0)
        check("graph has edges", G.number_of_edges() > 0)

        result = kg.query_customer("CUST-100000")
        check("query_customer found", result.get("customer_id") == "CUST-100000")
        check("query_customer has relations", bool(result.get("relations")))

        empty = kg.query_customer("CUST-NONEXISTENT")
        check("query_customer empty", empty == {})

        search = kg.search_nodes("CUST-100000", node_type="Customer")
        check("search_nodes found", len(search) >= 1)
    except ImportError as e:
        check("kuzu import", None, skip_reason=f"not installed: {e}")

    # ── 5. RAG retriever (structure only) ────────────────────
    print("\n📋 5. common.rag_retriever")
    try:
        from common.rag_retriever import retrieve, rebuild_index, KB_DIR, CHROMA_DIR
        check("Module imports", True)
        check(f"KB_DIR path set", "knowledge_base" in KB_DIR)
        check(f"CHROMA_DIR path set", "chroma_db" in CHROMA_DIR)
    except ImportError as e:
        check("rag_retriever import", None, skip_reason=f"not installed: {e}")

    # ── 6. LLM factory (structure only) ──────────────────────
    print("\n📋 6. llm_providers.factory")
    try:
        from llm_providers.factory import get_llm, get_llm_for_langchain
        check("Factory imports", True)
    except Exception as e:
        check(f"Import — {e}", False)

    # ── 7. Orchestrator factory ──────────────────────────────
    print("\n📋 7. orchestrators.factory")
    try:
        from orchestrators.factory import get_orchestrator
        check("Factory imports", True)
    except Exception as e:
        check(f"Import — {e}", False)

    # ── 8. Optional: check if orchestrator libs installed ────
    print("\n📋 8. Optional dependencies")
    for lib, pkg in [("langgraph", "langgraph"), ("crewai", "crewai"), ("llama_index", "llama-index-core")]:
        try:
            __import__(lib)
            check(f"{pkg} installed", True)
        except ImportError:
            check(f"{pkg}", None, skip_reason="not installed")

    for lib, pkg in [("openai", "openai"), ("anthropic", "anthropic"), ("groq", "groq")]:
        try:
            __import__(lib)
            check(f"{pkg} SDK installed", True)
        except ImportError:
            check(f"{pkg}", None, skip_reason="not installed")

    # ── Summary ──────────────────────────────────────────────
    print()
    print("=" * 60)
    total = passed + failed + skipped
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped / {total} total")
    if failed == 0:
        print("  🎉 All checks passed!")
    else:
        print("  ⚠️  Some checks failed — review above.")
    print("=" * 60)
    print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
