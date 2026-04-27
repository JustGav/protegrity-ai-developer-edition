"""
Test rate-limit retry handling in protegrity_guard.py.

Sends rapid-fire protect/unprotect requests to stress the API rate limits
(50 req/s, burst 100) and verifies the retry logic handles them gracefully.

Usage:
    # Quick test (10 requests) — verifies the retry path works
    python tests/test_rate_limit_retry.py

    # Stress test (100 requests) — more likely to hit actual rate limits
    python tests/test_rate_limit_retry.py --stress

    # Concurrent stress test — 100 requests with 10 parallel threads
    python tests/test_rate_limit_retry.py --stress --concurrency 10

    # Via the running Docker container
    docker exec technical_app python tests/test_rate_limit_retry.py
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_rate_limit")

# Enable DEBUG on the guard module to see retry warnings
logging.getLogger("services.protegrity_guard").setLevel(logging.DEBUG)
logging.getLogger("services.protegrity_dev_edition_helper").setLevel(logging.DEBUG)


def _run_concurrent(fn, items, label, num_requests, concurrency, results_dict, times_list):
    """Execute fn(index, item) across items using a thread pool."""
    lock = threading.Lock()
    counter = [0]  # mutable counter for thread-safe indexing

    def _worker(item):
        with lock:
            counter[0] += 1
            idx = counter[0]
        t0 = time.time()
        try:
            result = fn(item)
            elapsed_ms = round((time.time() - t0) * 1000)
            with lock:
                times_list.append(elapsed_ms)
                results_dict["success"] += 1
            status = "OK"
            if elapsed_ms > 2000:
                with lock:
                    results_dict["retried"] += 1
                status += " (likely retried)"
            logger.info("  %s [%d/%d] %dms — %s", label, idx, num_requests, elapsed_ms, status)
        except Exception as e:
            elapsed_ms = round((time.time() - t0) * 1000)
            with lock:
                times_list.append(elapsed_ms)
                results_dict["error"] += 1
            logger.error("  %s [%d/%d] %dms — FAILED: %s", label, idx, num_requests, elapsed_ms, e)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_worker, item) for item in items]
        for f in as_completed(futures):
            f.result()  # propagate unexpected exceptions


def run_test(num_requests: int, concurrency: int = 1):
    from services.protegrity_guard import get_guard

    guard = get_guard()
    if not guard.sdk_available:
        print("ERROR: Protegrity SDK not available. Cannot run test.")
        sys.exit(1)

    mode = f"{concurrency} threads" if concurrency > 1 else "sequential"
    print(f"\n{'='*60}")
    print(f"Rate Limit Retry Test — {num_requests} requests ({mode})")
    print(f"{'='*60}\n")

    # ── Test 1: Rapid protect_text calls ────────────────────────────
    print(f"[Test 1] protect_text — {num_requests} calls, {mode}\n")

    test_texts = [
        f"My name is John Smith and my email is john{i}@example.com"
        for i in range(num_requests)
    ]

    protect_results = {"success": 0, "error": 0, "retried": 0}
    protect_times = []
    t_start = time.time()

    if concurrency > 1:
        _run_concurrent(
            lambda text: guard.find_and_protect(text),
            test_texts, "protect", num_requests, concurrency,
            protect_results, protect_times,
        )
    else:
        for i, text in enumerate(test_texts):
            t0 = time.time()
            try:
                result = guard.find_and_protect(text)
                elapsed_ms = round((time.time() - t0) * 1000)
                protect_times.append(elapsed_ms)

                if result.transformed_text != text:
                    protect_results["success"] += 1
                    status = "OK"
                else:
                    protect_results["success"] += 1
                    status = "OK (no PII found)"

                if elapsed_ms > 2000:
                    protect_results["retried"] += 1
                    status += " (likely retried)"

                logger.info(
                    "  protect [%d/%d] %dms — %s",
                    i + 1, num_requests, elapsed_ms, status,
                )
            except Exception as e:
                elapsed_ms = round((time.time() - t0) * 1000)
                protect_times.append(elapsed_ms)
                protect_results["error"] += 1
                logger.error("  protect [%d/%d] %dms — FAILED: %s", i + 1, num_requests, elapsed_ms, e)

    t_total = round((time.time() - t_start) * 1000)
    avg_ms = round(sum(protect_times) / len(protect_times)) if protect_times else 0
    print(f"\n  Protect results: {protect_results}")
    print(f"  Total: {t_total}ms | Avg: {avg_ms}ms | "
          f"Effective rate: {num_requests / (t_total / 1000):.1f} req/s\n")

    # ── Test 2: Rapid unprotect_text calls ──────────────────────────
    # First protect one text to get a token, then unprotect it N times
    print(f"[Test 2] unprotect_text — {num_requests} calls, {mode}\n")

    # Let the API recover after Test 1 before generating tokens
    if concurrency > 1:
        cooldown = min(concurrency // 5, 30)  # scale with concurrency: 10→2s, 50→10s, 100→20s
        print(f"  (pausing {cooldown}s for API cooldown before tokenising sample...)")
        time.sleep(cooldown)

    sample_text = "Customer John Smith, SSN 123-45-6789, email john@bank.com"
    tokenized = None
    for attempt in range(1, 6):
        sample = guard.find_and_protect(sample_text)
        if re.search(r'\[([A-Z_]+)\]', sample.transformed_text):
            tokenized = sample.transformed_text
            break
        logger.warning("  Protect attempt %d produced no tokens, retrying in 3s...", attempt)
        time.sleep(3)

    if tokenized is None:
        tokenized = sample.transformed_text

    has_tags = bool(re.search(r'\[([A-Z_]+)\]', tokenized))
    print(f"  Tokenized sample ({len(tokenized)} chars, tags={'YES' if has_tags else 'NO'}):")
    print(f"    {tokenized[:120]}{'...' if len(tokenized) > 120 else ''}")
    if not has_tags:
        print("  WARNING: No entity tags found — protect call may have failed silently.")
        print("           Unprotect will be a no-op (regex finds nothing to de-tokenize).\n")

    unprotect_results = {"success": 0, "error": 0, "retried": 0}
    unprotect_times = []
    t_start = time.time()

    if concurrency > 1:
        _run_concurrent(
            lambda _: guard.find_and_unprotect(tokenized),
            range(num_requests), "unprotect", num_requests, concurrency,
            unprotect_results, unprotect_times,
        )
    else:
        for i in range(num_requests):
            t0 = time.time()
            try:
                result = guard.find_and_unprotect(tokenized)
                elapsed_ms = round((time.time() - t0) * 1000)
                unprotect_times.append(elapsed_ms)
                unprotect_results["success"] += 1

                status = "OK"
                if elapsed_ms > 2000:
                    unprotect_results["retried"] += 1
                    status += " (likely retried)"

                logger.info(
                    "  unprotect [%d/%d] %dms — %s",
                    i + 1, num_requests, elapsed_ms, status,
                )
            except Exception as e:
                elapsed_ms = round((time.time() - t0) * 1000)
                unprotect_times.append(elapsed_ms)
                unprotect_results["error"] += 1
                logger.error("  unprotect [%d/%d] %dms — FAILED: %s", i + 1, num_requests, elapsed_ms, e)

    t_total = round((time.time() - t_start) * 1000)
    avg_ms = round(sum(unprotect_times) / len(unprotect_times)) if unprotect_times else 0
    print(f"\n  Unprotect results: {unprotect_results}")
    print(f"  Total: {t_total}ms | Avg: {avg_ms}ms | "
          f"Effective rate: {num_requests / (t_total / 1000):.1f} req/s\n")

    # ── Test 3: Semantic Guardrail rapid calls ──────────────────────
    print(f"[Test 3] semantic_guardrail — {num_requests} calls, {mode}\n")

    sgr_results = {"success": 0, "error": 0, "retried": 0}
    sgr_times = []
    t_start = time.time()

    test_messages = [
        f"What is the balance on account {100000 + i}?"
        for i in range(num_requests)
    ]

    if concurrency > 1:
        _run_concurrent(
            lambda msg: guard.semantic_guardrail_check(msg, threshold=0.7),
            test_messages, "guardrail", num_requests, concurrency,
            sgr_results, sgr_times,
        )
    else:
        for i, msg in enumerate(test_messages):
            t0 = time.time()
            try:
                result = guard.semantic_guardrail_check(msg, threshold=0.7)
                elapsed_ms = round((time.time() - t0) * 1000)
                sgr_times.append(elapsed_ms)
                sgr_results["success"] += 1

                status = f"OK (score={result.risk_score:.3f})"
                if elapsed_ms > 2000:
                    sgr_results["retried"] += 1
                    status += " (likely retried)"

                logger.info(
                    "  guardrail [%d/%d] %dms — %s",
                    i + 1, num_requests, elapsed_ms, status,
                )
            except Exception as e:
                elapsed_ms = round((time.time() - t0) * 1000)
                sgr_times.append(elapsed_ms)
                sgr_results["error"] += 1
                logger.error("  guardrail [%d/%d] %dms — FAILED: %s", i + 1, num_requests, elapsed_ms, e)

    t_total = round((time.time() - t_start) * 1000)
    avg_ms = round(sum(sgr_times) / len(sgr_times)) if sgr_times else 0
    print(f"\n  Guardrail results: {sgr_results}")
    print(f"  Total: {t_total}ms | Avg: {avg_ms}ms | "
          f"Effective rate: {num_requests / (t_total / 1000):.1f} req/s\n")

    # ── Summary ─────────────────────────────────────────────────────
    total_ok = protect_results["success"] + unprotect_results["success"] + sgr_results["success"]
    total_err = protect_results["error"] + unprotect_results["error"] + sgr_results["error"]
    total_retried = protect_results["retried"] + unprotect_results["retried"] + sgr_results["retried"]

    print(f"{'='*60}")
    print(f"SUMMARY: {total_ok} succeeded, {total_err} failed, "
          f"{total_retried} likely retried")
    print(f"{'='*60}")

    if total_err > 0:
        print("\nWARNING: Some requests failed. Check logs above for details.")
        print("If errors show '429' or 'rate limit', the retry logic was triggered")
        print("but max retries were exhausted.")
        sys.exit(1)
    else:
        print("\nAll requests succeeded. Retry logic handled any rate limits gracefully.")
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Protegrity API rate-limit retry handling")
    parser.add_argument("--stress", action="store_true", help="Run 100 requests (more likely to hit rate limits)")
    parser.add_argument("--concurrency", "-c", type=int, default=1,
                        help="Number of parallel threads (default: 1 = sequential)")
    args = parser.parse_args()

    num = 100 if args.stress else 10
    run_test(num, concurrency=args.concurrency)
