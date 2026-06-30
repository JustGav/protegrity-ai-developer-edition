"""
Integration test script for TechnicalApp — exercises the full pipeline.

Tests all combinations of:
  - Pre-prompts (7 from the UI)
  - Customers (CUST-100000 to CUST-100014)
  - Orchestrators (direct, langgraph, crewai, llamaindex)
  - LLM provider (ollama)
  - Data source combinations per orchestrator

Usage:
    # Start the app first:
    python TechnicalApp/run.py &

    # Run all tests (default: http://localhost:5002):
    python tests/test_app_integration.py

    # Custom base URL:
    APP_URL=http://localhost:5002 python tests/test_app_integration.py

    # Run specific suite:
    python tests/test_app_integration.py --suite quick     # 1 prompt × 1 customer × direct/ollama
    python tests/test_app_integration.py --suite prompts   # all prompts × 1 customer × direct/ollama
    python tests/test_app_integration.py --suite matrix    # 1 prompt × 1 customer × all orchestrator/LLM combos
    python tests/test_app_integration.py --suite full      # all prompts × 3 customers × all combos
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

# ── Configuration ────────────────────────────────────────────────────

BASE_URL = os.environ.get("APP_URL", "http://localhost:5002")
LOGIN_URL = f"{BASE_URL}/tech/login"
CONFIG_URL = f"{BASE_URL}/tech/api/config"
CHAT_URL = f"{BASE_URL}/tech/api/chat"
CLEAR_URL = f"{BASE_URL}/tech/api/chat/clear"

DEFAULT_USER = "admin"
DEFAULT_PASS = "Adm!n@S3cure2026"

# Pre-prompts from the chat UI
PRE_PROMPTS = [
    "Show my personal details",
    "Give me details about my credit card 583315869235",
    "give me all details about this account number 9697354961",
    "Give me the weather today",
    "What credit cards do I have?",
    "List my recent transactions",
    "What loans do I have and their status?",
]

ALL_CUSTOMERS = [f"CUST-{100000 + i}" for i in range(15)]

ORCHESTRATORS = ["direct", "langgraph", "crewai", "llamaindex"]
LLM_PROVIDERS = ["ollama"]

# Data sources allowed per orchestrator
ORCHESTRATOR_DATA_SOURCES: dict[str, dict[str, bool]] = {
    "direct":     {"kb": True, "rag": False, "kg": False},
    "langgraph":  {"kb": True, "rag": True,  "kg": True},
    "crewai":     {"kb": True, "rag": False, "kg": True},
    "llamaindex": {"kb": True, "rag": True,  "kg": False},
}


# ── Result tracking ─────────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float = 0
    error: str = ""
    response_preview: str = ""
    trace_steps: list = field(default_factory=list)


class TestRunner:
    def __init__(self):
        self.session = requests.Session()
        self.results: list[TestResult] = []
        self.authenticated = False

    # ── Auth ──────────────────────────────────────────────────────

    def login(self, username: str = DEFAULT_USER, password: str = DEFAULT_PASS) -> bool:
        try:
            resp = self.session.post(LOGIN_URL, data={
                "username": username,
                "password": password,
            }, allow_redirects=False)
            if resp.status_code in (302, 200):
                self.authenticated = True
                print(f"  ✅ Logged in as '{username}'")
                return True
            print(f"  ❌ Login failed: HTTP {resp.status_code}")
            return False
        except requests.ConnectionError:
            print(f"  ❌ Cannot connect to {BASE_URL} — is the app running?")
            return False

    # ── Config ────────────────────────────────────────────────────

    def get_config(self) -> dict | None:
        resp = self.session.get(CONFIG_URL)
        if resp.status_code == 200:
            return resp.json()
        return None

    def set_config(self, **kwargs) -> dict | None:
        resp = self.session.post(CONFIG_URL, json=kwargs)
        if resp.status_code == 200:
            return resp.json()
        print(f"    ⚠️  Config update failed: {resp.status_code} {resp.text[:200]}")
        return None

    def clear_chat(self, customer_id: str):
        self.session.post(CLEAR_URL, json={"customer_id": customer_id})

    # ── Chat ──────────────────────────────────────────────────────

    def send_chat(self, message: str, customer_id: str) -> dict:
        resp = self.session.post(CHAT_URL, json={
            "message": message,
            "customer_id": customer_id,
        })
        return resp.json() if resp.status_code == 200 else {"error": resp.text}

    # ── Test execution ────────────────────────────────────────────

    def run_test(
        self,
        name: str,
        message: str,
        customer_id: str,
        orchestrator: str,
        llm_provider: str,
        expect_blocked: bool = False,
    ) -> TestResult:
        """Run a single chat test with the given configuration."""
        t0 = time.time()
        try:
            # Configure
            data_sources = ORCHESTRATOR_DATA_SOURCES[orchestrator]
            config_resp = self.set_config(
                orchestrator=orchestrator,
                llm_provider=llm_provider,
                guardrail_enabled=True,
                discovery_enabled=True,
                show_trace=True,
                kb_enabled=data_sources["kb"],
                rag_enabled=data_sources["rag"],
                kg_enabled=data_sources["kg"],
            )
            if config_resp is None:
                return TestResult(name=name, passed=False, error="Config update failed")

            # Clear history for clean test
            self.clear_chat(customer_id)

            # Send message
            result = self.send_chat(message, customer_id)
            duration = (time.time() - t0) * 1000

            if "error" in result:
                return TestResult(
                    name=name, passed=False, duration_ms=duration,
                    error=result["error"][:200],
                )

            response_text = result.get("response", "")
            trace = result.get("trace", [])
            trace_steps = [s.get("step", "?") for s in trace]

            # Validate response
            if expect_blocked:
                passed = "blocked" in response_text.lower() or any(
                    s.get("blocked") for s in trace
                )
            else:
                passed = len(response_text) > 10

            return TestResult(
                name=name,
                passed=passed,
                duration_ms=duration,
                response_preview=response_text[:120],
                trace_steps=trace_steps,
            )
        except Exception as e:
            return TestResult(
                name=name, passed=False,
                duration_ms=(time.time() - t0) * 1000,
                error=str(e)[:200],
            )

    def add_result(self, result: TestResult):
        self.results.append(result)
        status = "✅" if result.passed else "❌"
        duration = f"{result.duration_ms:.0f}ms"
        print(f"  {status} [{duration:>6s}] {result.name}")
        if result.error:
            print(f"           Error: {result.error}")

    # ── Summary ───────────────────────────────────────────────────

    def print_summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        total_time = sum(r.duration_ms for r in self.results)

        print(f"\n{'='*70}")
        print(f"  RESULTS: {passed}/{total} passed, {failed} failed  |  Total: {total_time/1000:.1f}s")
        print(f"{'='*70}")

        if failed:
            print("\n  FAILURES:")
            for r in self.results:
                if not r.passed:
                    print(f"    ❌ {r.name}")
                    if r.error:
                        print(f"       {r.error}")
        print()


# ── Test Suites ──────────────────────────────────────────────────────

def suite_quick(runner: TestRunner):
    """Quick smoke test — 1 prompt, 1 customer, direct/ollama."""
    print("\n── Quick Smoke Test ─────────────────────────────────────")
    result = runner.run_test(
        name="quick | direct/ollama | CUST-100000",
        message=PRE_PROMPTS[0],
        customer_id="CUST-100000",
        orchestrator="direct",
        llm_provider="ollama",
    )
    runner.add_result(result)


def suite_prompts(runner: TestRunner):
    """All pre-prompts with 1 customer, direct/ollama."""
    print("\n── All Pre-Prompts (direct/ollama, CUST-100000) ────────")
    for i, prompt in enumerate(PRE_PROMPTS):
        label = prompt[:50]
        expect_blocked = "weather" in prompt.lower()
        result = runner.run_test(
            name=f"prompt[{i}] '{label}...'",
            message=prompt,
            customer_id="CUST-100000",
            orchestrator="direct",
            llm_provider="ollama",
            expect_blocked=expect_blocked,
        )
        runner.add_result(result)


def suite_matrix(runner: TestRunner):
    """All orchestrator × LLM provider combinations, 1 prompt, 1 customer."""
    print("\n── Orchestrator × LLM Matrix (CUST-100000) ─────────────")
    prompt = PRE_PROMPTS[0]  # "Show my personal details"
    for orch in ORCHESTRATORS:
        for llm in LLM_PROVIDERS:
            sources = ORCHESTRATOR_DATA_SOURCES[orch]
            src_label = "+".join(k.upper() for k, v in sources.items() if v)
            result = runner.run_test(
                name=f"{orch}/{llm} [{src_label}]",
                message=prompt,
                customer_id="CUST-100000",
                orchestrator=orch,
                llm_provider=llm,
            )
            runner.add_result(result)


def suite_customers(runner: TestRunner):
    """All customers with direct/ollama."""
    print("\n── All Customers (direct/ollama) ────────────────────────")
    prompt = PRE_PROMPTS[0]
    for cid in ALL_CUSTOMERS:
        result = runner.run_test(
            name=f"direct/ollama | {cid}",
            message=prompt,
            customer_id=cid,
            orchestrator="direct",
            llm_provider="ollama",
        )
        runner.add_result(result)


def suite_data_sources(runner: TestRunner):
    """Test data source toggling per orchestrator."""
    print("\n── Data Source Variations ───────────────────────────────")
    prompt = PRE_PROMPTS[0]
    # LangGraph supports all 3 data sources — test combinations
    for kb, rag, kg in [(True, False, False), (True, True, False), (True, False, True), (True, True, True)]:
        src = "+".join(
            [s for s, v in [("KB", kb), ("RAG", rag), ("KG", kg)] if v]
        ) or "NONE"
        runner.set_config(
            orchestrator="langgraph", llm_provider="ollama",
            kb_enabled=kb, rag_enabled=rag, kg_enabled=kg,
            guardrail_enabled=True, discovery_enabled=True, show_trace=True,
        )
        runner.clear_chat("CUST-100000")
        result = runner.run_test(
            name=f"langgraph/ollama [{src}]",
            message=prompt,
            customer_id="CUST-100000",
            orchestrator="langgraph",
            llm_provider="ollama",
        )
        runner.add_result(result)


def suite_protegrity_users(runner: TestRunner):
    """Test different Protegrity user roles (Gate 2 unprotection)."""
    print("\n── Protegrity User Roles (Gate 2) ───────────────────────")
    prompt = PRE_PROMPTS[0]
    for puser in ["superuser", "Marketing", "Finance", "Support"]:
        runner.set_config(
            orchestrator="direct", llm_provider="ollama",
            protegrity_user=puser,
            guardrail_enabled=True, discovery_enabled=True, show_trace=True,
        )
        runner.clear_chat("CUST-100000")
        result = runner.run_test(
            name=f"direct/ollama | protegrity_user={puser}",
            message=prompt,
            customer_id="CUST-100000",
            orchestrator="direct",
            llm_provider="ollama",
        )
        runner.add_result(result)


def suite_full(runner: TestRunner):
    """Full matrix — all prompts × 3 customers × all orchestrator/LLM combos."""
    print("\n── Full Integration Matrix ─────────────────────────────")
    customers = ["CUST-100000", "CUST-100005", "CUST-100010"]
    for orch in ORCHESTRATORS:
        for llm in LLM_PROVIDERS:
            for cid in customers:
                for i, prompt in enumerate(PRE_PROMPTS):
                    label = prompt[:40]
                    expect_blocked = "weather" in prompt.lower()
                    result = runner.run_test(
                        name=f"{orch}/{llm} | {cid} | prompt[{i}]",
                        message=prompt,
                        customer_id=cid,
                        orchestrator=orch,
                        llm_provider=llm,
                        expect_blocked=expect_blocked,
                    )
                    runner.add_result(result)


SUITES = {
    "quick": suite_quick,
    "prompts": suite_prompts,
    "matrix": suite_matrix,
    "customers": suite_customers,
    "datasources": suite_data_sources,
    "roles": suite_protegrity_users,
    "full": suite_full,
}


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Integration tests for TechnicalApp")
    parser.add_argument(
        "--suite", default="quick",
        choices=list(SUITES.keys()) + ["all"],
        help="Test suite to run (default: quick)",
    )
    parser.add_argument("--user", default=DEFAULT_USER, help="Login username")
    parser.add_argument("--password", default=DEFAULT_PASS, help="Login password")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"  TechnicalApp Integration Tests")
    print(f"  URL: {BASE_URL}")
    print(f"  Suite: {args.suite}")
    print(f"{'='*70}")

    runner = TestRunner()

    # Authenticate
    print("\n── Authentication ──────────────────────────────────────")
    if not runner.login(args.user, args.password):
        print("\n  ❌ Cannot proceed without authentication. Exiting.")
        sys.exit(1)

    # Run selected suite(s)
    if args.suite == "all":
        for name, fn in SUITES.items():
            if name != "full":  # skip full in "all" — too many tests
                fn(runner)
    else:
        SUITES[args.suite](runner)

    # Summary
    runner.print_summary()
    sys.exit(0 if all(r.passed for r in runner.results) else 1)


if __name__ == "__main__":
    main()
