"""
HW4 Part 3, steps 4-7: measure list-naive vs list-fixed at page sizes
10/50/200, 30 requests each (180 total), recording SQL query count and
p50/p95/p99 latency per request. Writes:

  reports/hw04/raw/n1_raw.csv     -- all 180 individual request records
  reports/hw04/raw/n1_raw.json    -- same data, JSON
  reports/hw04/METRICS.md         -- the filled-in summary table from the PDF

Requires the backend running on PORT_BASE (8675) and already seeded via
scripts/seed_hw04_part3.py.

Usage:
    python3 scripts/measure_n1.py
"""
import csv
import json
import os
import sys
import time

import numpy as np
import requests

BASE_URL = "http://localhost:8675"
DEMO_EMAIL = "pinal@example.com"
DEMO_PASSWORD = "hw4-demo-pass"
PAGE_SIZES = [10, 50, 200]
VERSIONS = ["naive", "fixed"]
REQUESTS_PER_CONFIG = 30

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "hw04")
RAW_DIR = os.path.join(OUT_DIR, "raw")


def login() -> requests.Session:
    session = requests.Session()
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    resp.raise_for_status()
    return session


def run_one(session: requests.Session, version: str, page_size: int):
    endpoint = f"{BASE_URL}/api/notices/list-{version}"
    start = time.perf_counter()
    resp = session.get(endpoint, params={"page": 1, "page_size": page_size})
    elapsed_ms = (time.perf_counter() - start) * 1000
    resp.raise_for_status()
    body = resp.json()
    return elapsed_ms, body["sql_query_count"], len(body["results"])


def percentile(values, p):
    return float(np.percentile(values, p))


if __name__ == "__main__":
    os.makedirs(RAW_DIR, exist_ok=True)
    session = login()

    raw_records = []
    summary = {}  # (page_size, version) -> {"sql_stmts": int, "latencies": [ms,...]}

    for page_size in PAGE_SIZES:
        for version in VERSIONS:
            latencies = []
            sql_counts = []
            for i in range(REQUESTS_PER_CONFIG):
                elapsed_ms, sql_count, row_count = run_one(session, version, page_size)
                latencies.append(elapsed_ms)
                sql_counts.append(sql_count)
                raw_records.append({
                    "page_size": page_size,
                    "version": version,
                    "request_index": i,
                    "latency_ms": round(elapsed_ms, 3),
                    "sql_query_count": sql_count,
                    "rows_returned": row_count,
                })
            summary[(page_size, version)] = {
                "sql_stmts": sql_counts[0],  # constant per config by design; sanity-checked below
                "sql_stmts_all_equal": len(set(sql_counts)) == 1,
                "p50": percentile(latencies, 50),
                "p95": percentile(latencies, 95),
                "p99": percentile(latencies, 99),
            }
            print(f"page_size={page_size:<4} version={version:<6} "
                  f"sql_stmts/req={sql_counts[0]:<4} "
                  f"p50={summary[(page_size, version)]['p50']:.2f}ms "
                  f"p95={summary[(page_size, version)]['p95']:.2f}ms "
                  f"p99={summary[(page_size, version)]['p99']:.2f}ms")

    # --- raw data (all 180 requests) ---
    with open(os.path.join(RAW_DIR, "n1_raw.json"), "w") as f:
        json.dump(raw_records, f, indent=2)

    with open(os.path.join(RAW_DIR, "n1_raw.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(raw_records[0].keys()))
        writer.writeheader()
        writer.writerows(raw_records)

    # --- METRICS.md summary table ---
    lines = [
        "# HW4 Part 3 - N+1 Measurement Results\n",
        "| Page size | Version | SQL stmts/req | p50 (ms) | p95 (ms) | p99 (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for page_size in PAGE_SIZES:
        for version in VERSIONS:
            s = summary[(page_size, version)]
            lines.append(
                f"| {page_size} | {version} | {s['sql_stmts']} | {s['p50']:.2f} | {s['p95']:.2f} | {s['p99']:.2f} |"
            )

    lines.append("\n## Speed-up (naive p50 / fixed p50) at each page size\n")
    for page_size in PAGE_SIZES:
        naive_p50 = summary[(page_size, "naive")]["p50"]
        fixed_p50 = summary[(page_size, "fixed")]["p50"]
        speedup = naive_p50 / fixed_p50 if fixed_p50 > 0 else float("inf")
        lines.append(f"- Page size {page_size}: naive {naive_p50:.2f}ms vs fixed {fixed_p50:.2f}ms -> **{speedup:.2f}x faster**")

    with open(os.path.join(OUT_DIR, "METRICS.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print("\nWrote reports/hw04/raw/n1_raw.{json,csv} and reports/hw04/METRICS.md")
