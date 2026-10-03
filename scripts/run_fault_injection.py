"""
HW5 Part 3: retry demonstrations + the 150-call fault-injection experiment.

Usage (from the repo root, MySQL running):
    python3 scripts/run_fault_injection.py

Part A shows the retry policy's three outcomes (plus a timeout).
Part B runs 50 calls at each injected failure rate (0%, 20%, 50%) using
VERIFY_SEED, and writes every call to reports/hw05/raw/.
"""
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recall_tools import tools
from recall_tools.retry import INTERACTIVE_POLICY, FlakyStore, ResilientStore, RetryPolicy
from recall_tools.store import DbStore

SID4 = 7875
VERIFY_SEED = 260000 + SID4          # 267875
RATES = [0.0, 0.2, 0.5]
CALLS_PER_RATE = 50
RAW_DIR = os.path.join("reports", "hw05", "raw")
CALL_INPUT = {"query": "spinach", "limit": 3}


def now():
    return datetime.now().isoformat(timespec="seconds")


def demo(title, script, policy, slow_s=0.0):
    flaky = FlakyStore(DbStore(), script=script, slow_s=slow_s)
    store = ResilientStore(flaky, policy)
    start = time.perf_counter()
    result = tools.search_notices(store, CALL_INPUT)
    ms = (time.perf_counter() - start) * 1000
    print(f"\n--- {title}")
    print(f"    injected per attempt : {flaky.outcomes}")
    print(f"    attempts used        : {store.last_call['attempts']} of {policy.max_attempts}")
    for line in store.last_call["errors"]:
        print(f"    {line}")
    print(f"    backoff waited       : {store.last_call['waited_s']:.1f}s   total {ms:.0f} ms")
    shown = {"ok": result["ok"], "error": result["error"],
             "data": None if result["data"] is None else f"{result['data']['count']} notices"}
    print(f"    returned envelope    : {json.dumps(shown)}")


def p99(values):
    ordered = sorted(values)
    rank = max(1, -(-99 * len(ordered) // 100))  # nearest-rank: ceil(0.99 * n)
    return ordered[rank - 1]


def run_rate(rate, policy):
    """50 tool calls against a store that fails `rate` of the time (seeded)."""
    flaky = FlakyStore(DbStore(), failure_rate=rate, seed=VERIFY_SEED)
    store = ResilientStore(flaky, policy)
    rows = []
    for i in range(1, CALLS_PER_RATE + 1):
        before = len(flaky.outcomes)
        start = time.perf_counter()
        result = tools.search_notices(store, CALL_INPUT)
        latency_ms = (time.perf_counter() - start) * 1000
        rows.append({
            "timestamp": now(),
            "failure_rate": rate,
            "call_index": i,
            "ok": result["ok"],
            "attempts": store.last_call["attempts"],
            "attempt_outcomes": "|".join(flaky.outcomes[before:]),
            "latency_ms": round(latency_ms, 2),
            "error": result["error"] or "",
        })
    return rows, flaky.outcomes


def main():
    policy = INTERACTIVE_POLICY
    os.makedirs(RAW_DIR, exist_ok=True)
    print(f"HW5 Part 3 fault injection -- Pinal Pawar (SID4 {SID4}) -- {now()}")
    print(f"VERIFY_SEED={VERIFY_SEED}  policy: max_attempts={policy.max_attempts}, "
          f"timeout={policy.timeout_s}s, backoff={policy.base_delay_s}s doubling, cap {policy.max_delay_s}s")

    DbStore().search("spinach", None, 1)  # warm up the DB connection so call 1 isn't an outlier

    print("\n=== Part A: retry policy demonstrations ===")
    demo("1. success on the first attempt", ["ok"], policy)
    demo("2. failure on the first attempt, success after a retry", ["fail", "ok"], policy)
    demo("3. timeout on the first attempt, success after a retry", ["slow", "ok"],
         RetryPolicy(max_attempts=3, timeout_s=0.5, base_delay_s=0.1, max_delay_s=1.0), slow_s=1.0)
    demo("4. failure on every allowed attempt -> clean error, no crash", ["fail", "fail", "fail"], policy)

    print("\n=== Part B: 50 calls at each injected failure rate ===")
    all_rows, summary = [], []
    for rate in RATES:
        rows, outcomes = run_rate(rate, policy)
        # Reproducibility check: the same seed must give the same sequence again.
        replay = FlakyStore(None, failure_rate=rate, seed=VERIFY_SEED)
        replayed = ["fail" if replay._rng.random() < rate else "ok" for _ in outcomes]
        latencies = [r["latency_ms"] for r in rows]
        summary.append({
            "injected_failure_rate": f"{int(rate * 100)}%",
            "calls": len(rows),
            "success_rate": f"{100 * sum(r['ok'] for r in rows) / len(rows):.0f}%",
            "mean_latency_ms": round(statistics.mean(latencies), 1),
            "p99_latency_ms": round(p99(latencies), 1),
            "attempts_total": sum(r["attempts"] for r in rows),
            "same_seed_same_sequence": replayed == outcomes,
            "first_12_attempt_outcomes": "".join("F" if o == "fail" else "." for o in outcomes[:12]),
        })
        all_rows.extend(rows)

    csv_path = os.path.join(RAW_DIR, "fault_injection_calls.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    json_path = os.path.join(RAW_DIR, "fault_injection_summary.json")
    with open(json_path, "w") as f:
        json.dump({"verify_seed": VERIFY_SEED, "policy": policy.__dict__, "generated_at": now(),
                   "results": summary}, f, indent=2)

    print(f"\n{'Injected failure rate':<24}{'Success rate':<15}{'Mean latency (ms)':<20}{'p99 latency (ms)':<18}")
    for s in summary:
        print(f"{s['injected_failure_rate']:<24}{s['success_rate']:<15}{s['mean_latency_ms']:<20}{s['p99_latency_ms']:<18}")
    print()
    for s in summary:
        print(f"  {s['injected_failure_rate']:>4}: {s['attempts_total']} attempts for {s['calls']} calls, "
              f"first attempts {s['first_12_attempt_outcomes']}  same seed -> same sequence: {s['same_seed_same_sequence']}")
    print(f"\nSaved {len(all_rows)} call records -> {csv_path}")
    print(f"Saved summary            -> {json_path}")
    print(f"Finished {now()}")


if __name__ == "__main__":
    main()
