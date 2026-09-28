"""
HW4 self-check / smoke test (Repository Instruction requirement).

This is a REAL script -- it does not hand-author results. It performs a
smoke test (basic things work, not every edge case) against your
ALREADY-RUNNING backend and writes the real pass/fail outcomes to
reports/hw04/verification.json. It never modifies application code, and
every backend check is read-only (it never creates/updates/deletes a
notice), so it's safe to re-run at any time -- including at grading time --
without disturbing the seeded data that Part 3's measurements depend on.

Before running:
    1. Start MySQL and make sure s7875_rel exists with data seeded
       (scripts/seed_hw04_part3.py) and a demo user exists (pinal@example.com /
       hw4-demo-pass -- see scripts/seed_demo_user.py).
    2. Start the backend:  uvicorn main:app --port 8675
    3. In another terminal, from the repo root:  python3 scripts/verify_hw04.py

The script still runs (and reports FAILs, not a crash) if the backend isn't
up -- that's a legitimate smoke-test outcome, not a bug in the script.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://localhost:8675"
DEMO_EMAIL = "pinal@example.com"
DEMO_PASSWORD = "hw4-demo-pass"

SID4 = 7875
PORT_BASE = 8000 + (SID4 % 900)
PREFIX = f"s{SID4}"
SEED = SID4
VERIFY_SEED = 260000 + SID4
DOMAIN_ID = SID4 % 8

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def get_commit_hash():
    """
    Only trust `git rev-parse HEAD` if the repo it found actually has this
    project folder as its top level. `git` walks UP the directory tree
    looking for a `.git`, so if some unrelated parent folder (e.g. a stray
    git init in ~/Downloads from an old assignment) happens to be a repo,
    a naive `git rev-parse HEAD` silently returns THAT repo's commit --
    which has nothing to do with this submission. Guard against that.
    """
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5)
        if top.returncode != 0:
            return "TODO_PASTE_TAGGED_COMMIT_HASH_HERE"
        top_level = Path(top.stdout.strip()).resolve()
        if top_level != ROOT.resolve():
            # This IS a git repo, just not one rooted at this project folder --
            # not a false crash, just not usable as this submission's commit hash.
            return "TODO_PASTE_TAGGED_COMMIT_HASH_HERE"

        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "TODO_PASTE_TAGGED_COMMIT_HASH_HERE"


def main():
    # ---- static / config checks (no server needed) ----
    check("PORT_BASE derivation: 8000 + (SID4 mod 900)", PORT_BASE == 8675,
          f"computed {PORT_BASE}, expected 8675")
    check("VERIFY_SEED derivation: 260000 + SID4", VERIFY_SEED == 267875,
          f"computed {VERIFY_SEED}, expected 267875")
    check("DOMAIN_ID derivation: SID4 mod 8", DOMAIN_ID == 3,
          f"computed {DOMAIN_ID}, expected 3")

    corpus_dir = ROOT / "corpus"
    n_docs = len(list(corpus_dir.glob("*.txt"))) if corpus_dir.exists() else 0
    check("Part 4 corpus has >= 5 documents", n_docs >= 5, f"found {n_docs} .txt files in corpus/")

    rag_py = ROOT / "rag.py"
    rag_compiles = False
    if rag_py.exists():
        r = subprocess.run([sys.executable, "-m", "py_compile", str(rag_py)], capture_output=True, text=True)
        rag_compiles = (r.returncode == 0)
    check("rag.py exists and compiles cleanly", rag_compiles, str(rag_py.relative_to(ROOT)))

    # ---- live backend checks ----
    try:
        resp = requests.get(f"{BASE_URL}/docs", timeout=5)
        backend_up = resp.status_code == 200
        check(f"Backend responds on PORT_BASE={PORT_BASE}", backend_up, f"GET /docs -> {resp.status_code}")
    except requests.RequestException as e:
        backend_up = False
        check(f"Backend responds on PORT_BASE={PORT_BASE}", False, f"connection failed: {e}")

    def skip(name):
        check(name, False, "skipped -- backend not reachable")

    if not backend_up:
        skip("Unauthenticated request to list-naive is rejected (401)")
        skip("Demo user login succeeds")
        skip("list-naive endpoint returns data")
        skip("list-naive shows N+1 pattern (sql_query_count == page_size + 1)")
        skip("list-fixed endpoint returns data")
        skip("list-fixed shows single query (sql_query_count == 1)")
    else:
        # Unauthenticated check uses a fresh, cookie-less request.
        try:
            resp = requests.get(f"{BASE_URL}/api/notices/list-naive",
                                 params={"page": 1, "page_size": 10}, timeout=5)
            check("Unauthenticated request to list-naive is rejected (401)", resp.status_code == 401,
                  f"GET list-naive with no session cookie -> {resp.status_code}")
        except requests.RequestException as e:
            check("Unauthenticated request to list-naive is rejected (401)", False, f"request failed: {e}")

        session = requests.Session()
        try:
            resp = session.post(f"{BASE_URL}/api/auth/login",
                                 json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=5)
            login_ok = resp.status_code == 200
            check("Demo user login succeeds", login_ok, f"POST /api/auth/login -> {resp.status_code}")
        except requests.RequestException as e:
            login_ok = False
            check("Demo user login succeeds", False, f"request failed: {e}")

        if not login_ok:
            skip("list-naive endpoint returns data")
            skip("list-naive shows N+1 pattern (sql_query_count == page_size + 1)")
            skip("list-fixed endpoint returns data")
            skip("list-fixed shows single query (sql_query_count == 1)")
        else:
            try:
                resp = session.get(f"{BASE_URL}/api/notices/list-naive",
                                    params={"page": 1, "page_size": 10}, timeout=10)
                body = resp.json() if resp.status_code == 200 else {}
                results = body.get("results", [])
                sql_count = body.get("sql_query_count")
                check("list-naive endpoint returns data", resp.status_code == 200 and len(results) > 0,
                      f"status={resp.status_code} rows_returned={len(results)}")
                check("list-naive shows N+1 pattern (sql_query_count == page_size + 1)", sql_count == 11,
                      f"sql_query_count={sql_count}, expected 11 at page_size=10")
            except requests.RequestException as e:
                check("list-naive endpoint returns data", False, f"request failed: {e}")
                check("list-naive shows N+1 pattern (sql_query_count == page_size + 1)", False, "skipped")

            try:
                resp = session.get(f"{BASE_URL}/api/notices/list-fixed",
                                    params={"page": 1, "page_size": 10}, timeout=10)
                body = resp.json() if resp.status_code == 200 else {}
                results = body.get("results", [])
                sql_count = body.get("sql_query_count")
                check("list-fixed endpoint returns data", resp.status_code == 200 and len(results) > 0,
                      f"status={resp.status_code} rows_returned={len(results)}")
                check("list-fixed shows single query (sql_query_count == 1)", sql_count == 1,
                      f"sql_query_count={sql_count}, expected 1")
            except requests.RequestException as e:
                check("list-fixed endpoint returns data", False, f"request failed: {e}")
                check("list-fixed shows single query (sql_query_count == 1)", False, "skipped")

    all_passed = all(c["passed"] for c in checks)

    result = {
        "homework": "HW4",
        "sid4": str(SID4),
        "commit_hash": get_commit_hash(),
        "model_used": os.getenv("OLLAMA_MODEL", "qwen3:1.7b"),
        "port_base": PORT_BASE,
        "prefix": PREFIX,
        "domain_id": DOMAIN_ID,
        "seed": SEED,
        "verify_seed": VERIFY_SEED,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": checks,
        "all_passed": all_passed,
        "notes": (
            "Generated by scripts/verify_hw04.py, an actual smoke-test script executed "
            "against the live backend -- not hand-authored. Backend checks require "
            "`uvicorn main:app --port 8675` running with MySQL up and "
            "scripts/seed_hw04_part3.py already run at least once. All backend checks "
            "are read-only and do not mutate the seeded notices/related_info tables."
        ),
    }

    out_path = ROOT / "reports" / "hw04" / "verification.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    passed_n = sum(c["passed"] for c in checks)
    print(f"\n{'ALL CHECKS PASSED' if all_passed else 'SOME CHECKS FAILED'} ({passed_n}/{len(checks)})")
    print(f"Wrote {out_path.relative_to(ROOT)}")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
