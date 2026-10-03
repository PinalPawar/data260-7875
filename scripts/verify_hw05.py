"""
HW5 self-check / smoke test. Writes reports/hw05/verification.json.

A smoke test: start things up and check the basics work, not every edge
case. It never modifies application code, and every check is read-only.

Before running (from the repo root):
    1. MySQL running, backend running:  python3 -m uvicorn main:app --port 8675
    2. python3 scripts/verify_hw05.py

If the backend or a server is down the script reports FAIL for that check
instead of crashing. Set HW5_COMMIT=<hash> to record the tagged commit when
the folder is not a git checkout.
"""
import asyncio
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SID4 = 7875
PORT_BASE = 8000 + (SID4 % 900)      # 8675
PREFIX = f"s{SID4}"
SEED = SID4
VERIFY_SEED = 260000 + SID4          # 267875
DOMAIN_ID = SID4 % 8                 # 3
BASE_URL = f"http://localhost:{PORT_BASE}"
DEMO_EMAIL, DEMO_PASSWORD = "pinal@example.com", "hw4-demo-pass"
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": str(detail)})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def commit_hash():
    if os.getenv("HW5_COMMIT"):
        return os.environ["HW5_COMMIT"]
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        if top.returncode == 0 and Path(top.stdout.strip()).resolve() == ROOT.resolve():
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=5)
            if head.returncode == 0:
                return head.stdout.strip()
    except Exception:
        pass
    return "not a git checkout -- see the hw5 tag on GitHub"


def check_backend():
    try:
        anon = requests.get(f"{BASE_URL}/api/manufacturers", timeout=5)
        check("backend responds on PORT_BASE", True, f"port {PORT_BASE}, HTTP {anon.status_code}")
        check("anonymous request is refused", anon.status_code == 401, f"HTTP {anon.status_code}")
    except Exception as exc:
        check("backend responds on PORT_BASE", False, type(exc).__name__)
        return
    try:
        session = requests.Session()
        login = session.post(f"{BASE_URL}/api/auth/login",
                             json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=5)
        check("login works", login.status_code == 200, f"HTTP {login.status_code}")
        page = session.get(f"{BASE_URL}/api/manufacturers", params={"page": 1, "page_size": 2}, timeout=5)
        body = page.json() if page.status_code == 200 else {}
        check("manufacturers list is paginated", page.status_code == 200 and len(body.get("items", [])) <= 2
              and "total" in body, f"total={body.get('total')}")
        first = (body.get("items") or [{}])[0].get("id")
        rel = session.get(f"{BASE_URL}/api/manufacturers/{first}/notices", params={"limit": 3}, timeout=5)
        check("relationship endpoint returns notices", rel.status_code == 200 and isinstance(rel.json(), list),
              f"HTTP {rel.status_code}")
        missing = session.get(f"{BASE_URL}/api/manufacturers/999999", timeout=5)
        check("unknown manufacturer returns 404", missing.status_code == 404, f"HTTP {missing.status_code}")
    except Exception as exc:
        check("backend API checks", False, type(exc).__name__)


async def _call_server(script, tool, arguments):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / script)],
                                   env=dict(os.environ), cwd=str(ROOT))
    with open(os.devnull, "w") as quiet:
        async with stdio_client(params, errlog=quiet) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = [t.name for t in (await session.list_tools()).tools]
                result = await session.call_tool(tool, arguments)
                return names, result.isError, result.content[0].text if result.content else ""


def check_mcp_servers():
    try:
        names, is_error, _ = asyncio.run(asyncio.wait_for(
            _call_server("mcp_servers/meals_server.py", "search_meals_by_name", {"query": "Arrabiata"}), 60))
        check("meals MCP server starts with 4 tools", len(names) == 4, ", ".join(names))
        check("meals MCP server answers a tool call", not is_error, "search_meals_by_name")
    except Exception as exc:
        check("meals MCP server starts and answers", False, type(exc).__name__)
    try:
        names, is_error, text = asyncio.run(asyncio.wait_for(
            _call_server("mcp_servers/recall_server.py", "recall_stats", {"group_by": "category"}), 60))
        check("domain MCP server starts with exactly 3 tools", len(names) == 3, ", ".join(names))
        envelope = json.loads(text)
        check("domain tool call returns the {ok, data, error} envelope",
              not is_error and set(envelope) == {"ok", "data", "error"} and envelope["ok"] is True,
              f"ok={envelope.get('ok')}")
    except Exception as exc:
        check("domain MCP server starts and answers", False, type(exc).__name__)


def check_tool_layer():
    try:
        from recall_tools.execute import execute_tool
        from recall_tools.store import InMemoryStore
        store = InMemoryStore([])
        bad = json.loads(execute_tool("get_notice_detail", {"notice_code": "ABC-123"}, store=store))
        check("execute_tool rejects an invalid input without raising", bad["ok"] is False and bad["data"] is None)
        blocked = json.loads(execute_tool("search_notices", {"query": "someone@example.com"}, store=store))
        check("execute_tool enforces the safety rule", blocked["ok"] is False
              and str(blocked["error"]).startswith("safety rule"))
    except Exception as exc:
        check("execute_tool checks", False, type(exc).__name__)
    try:
        run = subprocess.run([sys.executable, str(ROOT / "tests" / "test_hw05_tools.py")], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        last = (run.stdout.strip().splitlines() or [""])[-1]
        check("offline test suite passes", run.returncode == 0, last)
    except Exception as exc:
        check("offline test suite passes", False, type(exc).__name__)


def check_raw_files():
    raw = ROOT / "reports" / "hw05" / "raw"
    try:
        with open(raw / "fault_injection_calls.csv") as f:
            rows = list(csv.DictReader(f))
        per_rate = {rate: sum(r["failure_rate"] == rate for r in rows) for rate in ("0.0", "0.2", "0.5")}
        check("150 fault-injection call records (3 rates x 50)", len(rows) == 150
              and all(n == 50 for n in per_rate.values()), f"{len(rows)} rows")
    except Exception as exc:
        check("150 fault-injection call records (3 rates x 50)", False, type(exc).__name__)
    try:
        with open(raw / "agent_runs.jsonl") as f:
            events = [json.loads(line) for line in f if line.strip()]
        ends = [e for e in events if e["event"] == "run_end"]
        reasons = sorted({e["stop_reason"] for e in ends})
        check("agent log has at least 4 runs with a stop reason", len(ends) >= 4, f"{len(ends)} runs: {reasons}")
    except Exception as exc:
        check("agent log has at least 4 runs with a stop reason", False, type(exc).__name__)
    for name in ("mcp_inspector_meals_server.json", "mcp_inspector_recall_server.json"):
        check(f"raw/{name} present", (raw / name).is_file())


def main():
    print(f"HW5 smoke test -- Pinal Pawar (SID4 {SID4}) -- {datetime.now().isoformat(timespec='seconds')}")
    check_backend()
    check_mcp_servers()
    check_tool_layer()
    check_raw_files()

    passed = sum(c["passed"] for c in checks)
    report = {
        "homework": 5,
        "sid4": SID4,
        "port_base": PORT_BASE,
        "prefix": PREFIX,
        "domain_id": DOMAIN_ID,
        "seed": SEED,
        "verify_seed": VERIFY_SEED,
        "commit_hash": commit_hash(),
        "model": f"{MODEL} (local, via Ollama)",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": f"{passed}/{len(checks)} checks passed",
        "checks": checks,
    }
    out = ROOT / "reports" / "hw05" / "verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\n{passed}/{len(checks)} checks passed -> {out.relative_to(ROOT)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
