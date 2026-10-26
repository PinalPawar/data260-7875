"""
HW7 self-check / smoke test. Writes reports/hw07/verification.json.

A smoke test: start the system and check that the basic things work, not every edge case.
Checks test behaviour (status codes, envelopes, stop reasons, row counts), never exact model
wording. It never modifies application code. Its only writes are temporary: one test notice
(created by writer1, deleted by mod1), a Reflexion store and a file-tool sandbox in a temp
folder, all removed again at the end.

Before running (from the repo root, conda env data260):
    1. MySQL and Ollama running (qwen3:1.7b pulled)
    2. backend running:  python main.py
    3. python scripts/verify_hw07.py            # add --skip-model to leave out the two model runs

A check that cannot run (server down, Ollama down) is reported as FAIL instead of crashing.
Set HW7_COMMIT=<hash> to record the commit when the folder is not a git checkout.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)

SID4 = 7875
PORT_BASE = 8000 + (SID4 % 900)  # 8675
PREFIX = f"s{SID4}"
SEED = SID4
VERIFY_SEED = 260000 + SID4  # 267875
DOMAIN_ID = SID4 % 8  # 3
BASE_URL = f"http://localhost:{PORT_BASE}"
HW = ROOT / "reports" / "hw07"
PART2_MODEL = "qwen3:1.7b"
PART4_MODEL = "qwen3:8b"

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": str(detail)[:300]})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def guarded(name, fn):
    """Run one group of checks; any exception becomes a FAIL with the error message."""
    try:
        fn()
    except Exception as exc:  # smoke test: report, never crash
        check(name, False, f"{type(exc).__name__}: {exc}")


def commit_hash():
    if os.getenv("HW7_COMMIT"):
        return os.environ["HW7_COMMIT"]
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top.returncode == 0 and Path(top.stdout.strip()).resolve() == ROOT.resolve():
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
            )
            if head.returncode == 0:
                return head.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "not a git checkout -- see the hw7 tag on GitHub"


def env(name):
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set in .env")
    return value


def offline_suite(path):
    """Run one offline test file in a subprocess; pass = exit code 0."""
    p = subprocess.run(
        [sys.executable, path], cwd=ROOT, capture_output=True, text=True, timeout=300
    )
    last = (p.stdout.strip().splitlines() or ["no output"])[-1]
    check(f"offline tests {path}", p.returncode == 0, last)


# --- Part 1: JWT auth, roles, MySQL users, linting --------------------------------------
def login(username, password):
    return requests.post(
        f"{BASE_URL}/auth/login", data={"username": username, "password": password}, timeout=10
    )


def part1():
    r = requests.get(f"{BASE_URL}/docs", timeout=10)
    check(
        "backend responds on PORT_BASE",
        r.status_code == 200,
        f"port {PORT_BASE}, HTTP {r.status_code}",
    )
    tokens = {}
    for user, var in (
        ("reader1", "HW7_READER_PASSWORD"),
        ("writer1", "HW7_WRITER_PASSWORD"),
        ("mod1", "HW7_MODERATOR_PASSWORD"),
    ):
        r = login(user, env(var))
        tokens[user] = r.json().get("access_token") if r.status_code == 200 else None
    check(
        "POST /auth/login returns a token for valid credentials (3 roles)",
        all(tokens.values()),
        ", ".join(u for u, t in tokens.items() if t),
    )
    r = login("writer1", "wrong-password-" + str(VERIFY_SEED))
    check(
        "POST /auth/login with a wrong password returns 401",
        r.status_code == 401,
        f"HTTP {r.status_code}",
    )
    r = login(f"nobody_{VERIFY_SEED}", "x")
    check(
        "POST /auth/login with an unknown user returns 401",
        r.status_code == 401,
        f"HTTP {r.status_code}",
    )

    def hdr(user):
        return {"Authorization": f"Bearer {tokens[user]}"}

    r = requests.get(f"{BASE_URL}/auth/me", timeout=10)
    check("GET /auth/me without a token returns 401", r.status_code == 401, f"HTTP {r.status_code}")
    r = requests.get(
        f"{BASE_URL}/auth/me", headers={"Authorization": "Bearer not.a.jwt"}, timeout=10
    )
    check(
        "GET /auth/me with an invalid token returns 401",
        r.status_code == 401,
        f"HTTP {r.status_code}",
    )
    r = requests.get(f"{BASE_URL}/auth/me", headers=hdr("writer1"), timeout=10)
    me = r.json() if r.status_code == 200 else {}
    check(
        "GET /auth/me returns identity and role",
        me.get("role") == "writer",
        f"HTTP {r.status_code}, {me}",
    )
    r = requests.get(f"{BASE_URL}/api/notices?limit=1", headers=hdr("reader1"), timeout=10)
    check("GET /api/notices as reader returns 200", r.status_code == 200, f"HTTP {r.status_code}")
    r = requests.get(f"{BASE_URL}/api/notices?limit=1", timeout=10)
    check(
        "GET /api/notices without a token returns 401",
        r.status_code == 401,
        f"HTTP {r.status_code}",
    )

    mr = requests.get(
        f"{BASE_URL}/api/manufacturers?limit=1", headers=hdr("reader1"), timeout=10
    ).json()
    items = mr if isinstance(mr, list) else (mr.get("items") or mr.get("manufacturers") or [{}])
    body = {
        "product": f"Verify {VERIFY_SEED}",
        "units_affected": 1,
        "email": "qa@example.com",
        "manufacturer_id": (items[0] or {}).get("id", 1),
        "description": "hw7 smoke test",
        "category": "bacterialContamination",
    }
    rng = random.Random(VERIFY_SEED)
    body["notice_code"] = f"RCL-2026-{rng.randint(90000, 99998)}"
    r = requests.post(f"{BASE_URL}/api/notices", json=body, headers=hdr("reader1"), timeout=10)
    check("POST /api/notices as reader returns 403", r.status_code == 403, f"HTTP {r.status_code}")
    for _ in range(5):  # retry on the rare notice_code clash
        r = requests.post(f"{BASE_URL}/api/notices", json=body, headers=hdr("writer1"), timeout=10)
        if r.status_code != 409:
            break
        body["notice_code"] = f"RCL-2026-{rng.randint(90000, 99998)}"
    check("POST /api/notices as writer returns 201", r.status_code == 201, f"HTTP {r.status_code}")
    if r.status_code == 201:
        nid = r.json()["id"]
        r = requests.delete(f"{BASE_URL}/api/notices/{nid}", headers=hdr("writer1"), timeout=10)
        check(
            "DELETE /api/notices/{id} as writer returns 403",
            r.status_code == 403,
            f"HTTP {r.status_code}",
        )
        r = requests.delete(f"{BASE_URL}/api/notices/{nid}", headers=hdr("mod1"), timeout=10)
        check(
            "DELETE /api/notices/{id} as moderator succeeds (test notice removed)",
            r.status_code in (200, 204),
            f"HTTP {r.status_code}",
        )

    from sqlalchemy import inspect, text

    from database import engine

    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    check(
        "MySQL users table has id, username, password_hash, role",
        {"id", "username", "password_hash", "role"} <= cols,
        ", ".join(sorted(cols)),
    )
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT username, role, password_hash FROM users "
                "WHERE username IN ('reader1','writer1','mod1')"
            )
        ).fetchall()
    check(
        "demo users stored with bcrypt hashes only",
        len(rows) == 3 and all(r[2].startswith("$2") for r in rows),
        ", ".join(f"{r[0]}={r[1]}" for r in rows),
    )
    check(
        "ruff.toml and .pre-commit-config.yaml present",
        (ROOT / "ruff.toml").exists() and (ROOT / ".pre-commit-config.yaml").exists(),
    )


# --- Part 2: hand-written agent loop --------------------------------------------------------
def part2(use_model):
    from recall_tools.execute import execute_tool
    from recall_tools.task_checks import load_cases, verify_task

    cases = load_cases()
    err = json.loads(
        execute_tool("get_notice_detail", {"notice_code": cases["error_case"]["notice_code"]})
    )
    check(
        "execute_tool returns a useful message for a nonexistent ID",
        err["ok"] is False and "not found" in err.get("error", ""),
        err.get("error"),
    )
    if not use_model:
        return
    from recall_tools.agent_loop import hw1_chat, run_agent

    task = next(t for t in cases["tasks"] if t["id"] == "A")
    result = run_agent(task["prompt"], chat=hw1_chat(temperature=0.0, seed=VERIFY_SEED))
    verdict = verify_task(task, result)
    check(
        f"run_agent completes verification task A ({PART2_MODEL}, seed {VERIFY_SEED})",
        verdict["passed"],
        f"stop={result.get('stop_reason')}, tool calls={result.get('tool_calls')}",
    )
    result = run_agent(
        cases["error_case"]["prompt"], chat=hw1_chat(temperature=0.0, seed=VERIFY_SEED)
    )
    check(
        "agent answers the nonexistent-ID case without crashing",
        bool(result.get("answer")) and result.get("stop_reason") != "error",
        f"stop={result.get('stop_reason')}",
    )


# --- Part 3: Reflexion ---------------------------------------------------------------------
def part3(use_model):
    from recall_tools import reflexion

    check(
        "Reflexion bounds: 2 retries, tool-call and token budgets",
        reflexion.MAX_RETRIES == 2
        and reflexion.TOOL_CALL_BUDGET > 0
        and reflexion.TOKEN_BUDGET > 0,
        f"retries={reflexion.MAX_RETRIES}, calls={reflexion.TOOL_CALL_BUDGET}, "
        f"tokens={reflexion.TOKEN_BUDGET}",
    )
    offline_suite("tests/test_hw07_reflexion.py")
    if not use_model:
        return
    from recall_tools.agent_loop import hw1_chat
    from recall_tools.task_checks import load_cases

    task = next(t for t in load_cases()["tasks"] if t["id"] == "B")
    tmp = tempfile.mkdtemp(prefix="verify_hw07_reflexion_")
    try:
        run = reflexion.run_reflexion(
            task,
            user_id=f"verify_{VERIFY_SEED}",
            chat_for=lambda i: hw1_chat(temperature=0.0, seed=VERIFY_SEED + i),
            store=reflexion.ReflectionStore(os.path.join(tmp, "reflections.jsonl")),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    check(
        "run_reflexion ends with a clean stop reason",
        run["status"] in ("success", "budget_exhausted", "human_review") and run["retries"] <= 2,
        f"status={run['status']}, retries={run['retries']}, tool calls={run['tool_calls']}",
    )


# --- Part 4: Bay Wheels MRKL agent ---------------------------------------------------------
def part4():
    from bike_agent import cost_check
    from bike_agent.pricing_page import PricingSnapshotCache, extract_snippets
    from bike_agent.tools import calculator, csv_sql, load_trips, policy_retriever

    fixture = "tests/fixtures/baywheels_pricing_sample.html"
    env_ = policy_retriever(PricingSnapshotCache(save=False), fixture, "month pass price", 3)
    shape = {"success", "data", "source", "ts"} <= set(env_)
    passages = env_.get("data", {}).get("passages", [])
    check(
        "policy_retriever returns the common envelope with text/source/score passages",
        shape and passages and set(passages[0]) == {"text", "source", "score"},
        f"{len(passages)} passages",
    )
    c = calculator("29*12 + 0.17*10", "USD")
    check(
        "calculator evaluates arithmetic without eval",
        c["success"] and c["data"]["value"] == 349.7,
        c.get("data"),
    )
    check("calculator rejects non-whitelisted input", not calculator("__import__('os')")["success"])
    prices = cost_check.parse_prices(extract_snippets(open(fixture).read())[0])
    for name, expect in (
        ("scenario_membership.csv", "Buy Monthly Membership"),
        ("scenario_payperuse.csv", "Pay Per Ride/Minute"),
    ):
        path = ROOT / "data" / "bikeshare" / name
        conn = load_trips(path.read_text(encoding="utf-8"))
        q = csv_sql(conn, "SELECT COUNT(*) AS n FROM trips")
        n = q["data"]["rows"][0]["n"]
        usage = csv_sql(conn, cost_check.usage_sql(prices["member_free_min"]))["data"]["rows"][0]
        ref = cost_check.compute_costs(usage, prices)
        check(
            f"{name}: >= 500 rows and the cost model picks '{expect}'",
            n >= 500 and ref["decision"] == expect and q["data"]["source"] == "uploaded.csv",
            f"{n} rows, PPU ${ref['pay_per_use_total']} vs member ${ref['membership_total']}",
        )
    snaps = sorted((HW / "raw" / "pricing_snapshots").glob("pricing_*.json"))
    ok = bool(snaps) and all(
        {"url", "accessed_utc", "sha256_text"} <= set(json.loads(s.read_text())) for s in snaps
    )
    check(
        "pricing snapshots saved with URL, access time and SHA-256", ok, f"{len(snaps)} snapshots"
    )
    runs = sorted((HW / "raw" / "part4_runs").glob("run_*.json"))
    finals = {}
    for p in runs:
        d = json.loads(p.read_text())
        name = (d.get("input") or {}).get("csv_name", "")
        comp = (d.get("check") or {}).get("comparison") or []
        if (
            d.get("answer")
            and comp
            and all(x["match"] for x in comp)
            and d["metrics"]["stop_reason"] == "final_answer"
        ):
            finals[name] = (d["answer"]["decision"], d["check"]["reference"]["decision"])
    check(
        "saved UI runs: both scenarios have a run whose six figures and decision match the check",
        all(
            finals.get(n, ("a", "b"))[0] == finals.get(n, ("a", "b"))[1]
            for n in ("scenario_membership.csv", "scenario_payperuse.csv")
        ),
        {k: v[0] for k, v in finals.items()},
    )
    offline_suite("tests/test_hw07_bike_agent.py")


# --- Part 5: prompt injection --------------------------------------------------------------
def part5():
    from run_hw07_part5 import compromised_model

    from bike_agent.agent import run_bike_agent
    from bike_agent.attacks import HOSTILE_FIXTURE, score_all
    from bike_agent.tools import csv_sql, load_trips

    check(
        "hostile fixture saved with the verification cases",
        (ROOT / HOSTILE_FIXTURE).exists(),
        HOSTILE_FIXTURE,
    )
    text = (ROOT / "data" / "bikeshare" / "scenario_payperuse.csv").read_text(encoding="utf-8")
    refused = []
    for sql in (
        "DELETE FROM trips",
        "SELECT 1; DROP TABLE trips",
        "WITH x AS (SELECT 1) DELETE FROM trips",
    ):
        conn = load_trips(text)
        refused.append(
            not csv_sql(conn, sql)["success"]
            and conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 500
        )
    check("csv_sql refuses non-SELECT SQL at the tool boundary (no model)", all(refused), refused)
    before = text.count("\n") - 1
    r = run_bike_agent(
        text,
        HOSTILE_FIXTURE,
        model=compromised_model(text),
        sql_guard="strict",
        label_untrusted=True,
        save_snapshot=False,
        apply_decision_guard=True,
        redact_csv_rows=True,
    )
    s = score_all(r, text, before)
    check(
        "compromised model vs all defenses: no attack succeeds",
        not any(v["succeeded"] for v in s.values()),
        {k: v["succeeded"] for k, v in s.items()},
    )
    offline_suite("tests/test_hw07_attacks.py")


# --- Part 6: file tools and safety gate ----------------------------------------------------
def part6():
    from file_tools import tools as ft
    from file_tools.gate import SAFE_PREFIXES, confirm_bash, is_destructive

    root = tempfile.mkdtemp(prefix="verify_hw07_sandbox_")
    try:
        for name, body in (("a.py", "x = 1\n"), ("b.py", "DEBUG = True\n"), ("c.py", "y = 2\n")):
            ft.write_file(root, name, body)
        g = ft.glob_files(root, "*.py")["data"]["matches"]
        s = ft.search_in_files(root, "DEBUG", file_pattern="*.py")["data"]["files"]
        rd = ft.read_file(root, s[0], max_lines=5)["data"]["content"] if s else ""
        check(
            "glob -> search -> read finds the DEBUG file in a temp sandbox",
            len(g) == 3 and s == ["b.py"] and "DEBUG" in rd,
            f"glob={g}, search={s}",
        )
        d = ft.edit_file(root, "b.py", "DEBUG = True", "DEBUG = False")
        check(
            "edit_file returns a short diff", d["success"] and "+DEBUG = False" in d["data"]["diff"]
        )
        check(
            "file tools refuse paths outside the sandbox", not ft.read_file(root, "../x")["success"]
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
    allow = ["ls -la", "cat utils.py", "grep -n DEBUG *.py", "wc -l *.py", "echo done > notes.txt"]
    block = [
        "rm -rf build",
        "sudo rm app.py",
        "ls && chmod -R 777 .",
        "echo pwned > /etc/hosts",
        "dd if=/dev/zero of=/dev/disk2",
    ]
    check("safety gate allows the 5 safe commands", all(confirm_bash(c)["allow"] for c in allow))
    check(
        "safety gate blocks the 5 destructive commands (0 false allows)",
        not any(confirm_bash(c)["allow"] for c in block),
    )
    check(
        "is_destructive returns a bool and ignores SAFE_PREFIXES",
        is_destructive("ls && chmod -R 777 .") is True
        and isinstance(is_destructive("ls"), bool)
        and "ls" in SAFE_PREFIXES,
    )
    check(
        "explicit confirmation allows a destructive command",
        confirm_bash("rm -rf build", auto_approve=True)["allow"] is True,
    )
    offline_suite("tests/test_hw07_file_tools.py")


# --- deliverables ---------------------------------------------------------------------------
def deliverables():
    for rel in (
        "RUN_LOG.txt",
        "METRICS.md",
        "AI_USE.md",
        "Pawar_HW7.pdf",
        "cases/verification_tasks.json",
        "cases/hostile_pricing_fixture.html",
    ):
        check(f"reports/hw07/{rel} exists", (HW / rel).exists())
    raw = HW / "raw"
    for pattern in (
        "part2_reliability_*",
        "part3_*",
        "part4_scenario_summaries.json",
        "part5_table.json",
        "part6_results.json",
    ):
        check(f"raw/{pattern} saved", any(raw.glob(pattern)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-model", action="store_true", help="skip the two Ollama runs")
    args = ap.parse_args()
    use_model = not args.skip_model
    print(f"HW7 verification - Pinal Pawar (SID4 {SID4}) - {datetime.now():%Y-%m-%d %H:%M:%S}")
    guarded("Part 1 checks", part1)
    guarded("Part 2 checks", lambda: part2(use_model))
    guarded("Part 3 checks", lambda: part3(use_model))
    guarded("Part 4 checks", part4)
    guarded("Part 5 checks", part5)
    guarded("Part 6 checks", part6)
    guarded("deliverable checks", deliverables)
    passed = sum(c["passed"] for c in checks)
    out = {
        "homework": 7,
        "sid4": SID4,
        "port_base": PORT_BASE,
        "prefix": PREFIX,
        "domain_id": DOMAIN_ID,
        "seed": SEED,
        "verify_seed": VERIFY_SEED,
        "commit_hash": commit_hash(),
        "model": {
            "part2_part3_agent_loop": (
                f"{PART2_MODEL} (local, Ollama), temperature 0, seed {VERIFY_SEED}"
            )
            if use_model
            else "skipped (--skip-model)",
            "part4_part5_bike_agent": f"{PART4_MODEL} via LangGraph (live runs saved in "
            "raw/part4_runs, not re-run here); the Part 5 smoke test uses the scripted "
            "compromised model",
            "part6": "pure Python, no model",
        },
        "config": {
            "jwt_algorithm": "HS256",
            "reflexion_max_retries": 2,
            "bike_agent_recursion_limit": 34,
            "model_max_rows": 24,
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": f"{passed}/{len(checks)} checks passed",
        "checks": checks,
    }
    with open(HW / "verification.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n{out['summary']} -> reports/hw07/verification.json")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
