"""
HW6 self-check / smoke test. Writes reports/hw06/verification.json.

A smoke test: start the system and check that the basic things work, not every
edge case. It never modifies application code. Its only writes are temporary
test data, all removed again at the end: one test notice (created, then
deleted), one chat turn under user id verify_267875 (deleted afterwards), and a
consolidation run on a temporary copy of the 55-line test file.

Before running (from the repo root):
    1. MongoDB (docker compose -f docker-compose.mongo.yml up -d), MySQL and Ollama running
    2. backend running:  python main.py
    3. python scripts/verify_hw06.py

A check that cannot run (server down, Ollama down) is reported as FAIL instead
of crashing. Set HW6_COMMIT=<hash> to record the commit when the folder is not
a git checkout.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
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
VERIFY_USER = f"verify_{VERIFY_SEED}"
HW = ROOT / "reports" / "hw06"

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": str(detail)})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def guarded(name, fn):
    """Run one check; any exception becomes a FAIL with the error message."""
    try:
        fn()
    except Exception as exc:  # smoke test: report, never crash
        check(name, False, f"{type(exc).__name__}: {exc}")


def commit_hash():
    if os.getenv("HW6_COMMIT"):
        return os.environ["HW6_COMMIT"]
    try:
        # only trust git when this folder itself is the repository root; otherwise a
        # parent folder's unrelated repository would be reported
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        if top.returncode == 0 and Path(top.stdout.strip()).resolve() == ROOT.resolve():
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=5)
            if head.returncode == 0:
                return head.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "not a git checkout -- see the hw6 tag on GitHub"


# --- Part 1: MongoDB document API ------------------------------------------
def part1():
    r = requests.get(f"{BASE_URL}/docs", timeout=10)
    check("backend responds on PORT_BASE", r.status_code == 200, f"port {PORT_BASE}, HTTP {r.status_code}")
    body = {"product": "Verify Test Product", "category": "foreignMaterial",
            "recall_date": "2026-10-16T00:00:00Z", "description": f"verification {VERIFY_SEED}"}
    r = requests.post(f"{BASE_URL}/api/doc/notices", json=body, timeout=10)
    ok = r.status_code == 201 and r.json().get("status") == "announced"
    check("POST /api/doc/notices creates a notice with default status", ok, f"HTTP {r.status_code}")
    nid = r.json()["id"]
    r = requests.get(f"{BASE_URL}/api/doc/notices/{nid}", timeout=10)
    check("GET /api/doc/notices/{id} returns it", r.status_code == 200, f"HTTP {r.status_code}")
    r = requests.put(f"{BASE_URL}/api/doc/notices/{nid}", json={"status": "ongoing"}, timeout=10)
    check("PUT updates the notice", r.status_code == 200 and r.json()["status"] == "ongoing", f"HTTP {r.status_code}")
    r = requests.delete(f"{BASE_URL}/api/doc/notices/{nid}", timeout=10)
    check("DELETE removes it (204)", r.status_code == 204, f"HTTP {r.status_code}")
    r = requests.get(f"{BASE_URL}/api/doc/notices/{nid}", timeout=10)
    check("deleted notice returns 404", r.status_code == 404, f"HTTP {r.status_code}")
    r = requests.post(f"{BASE_URL}/api/doc/notices", json={**body, "category": "spoiled"}, timeout=10)
    check("invalid enum value is rejected with 422", r.status_code == 422, f"HTTP {r.status_code}")
    r = requests.post(f"{BASE_URL}/api/doc/notices", json={"category": "mislabelling"}, timeout=10)
    check("missing required fields are rejected with 422", r.status_code == 422, f"HTTP {r.status_code}")
    r = requests.get(f"{BASE_URL}/api/doc/notices/abc", timeout=10)
    check("invalid id format returns 400", r.status_code == 400, f"HTTP {r.status_code}")


# --- Part 2: chat memory ---------------------------------------------------
def part2():
    from mongo_doc.db import get_db, get_episodes_collection, get_messages_collection, get_summaries_collection
    names = set(get_db().list_collection_names())
    need = {"recall_notices", "messages", "summaries", "episodes"}
    check(f"{PREFIX}_doc has the four collections", need <= names, ", ".join(sorted(need & names)))
    for col in (get_messages_collection(), get_summaries_collection(), get_episodes_collection()):
        col.delete_many({"user_id": VERIFY_USER})
    r = requests.post(f"{BASE_URL}/api/chat", timeout=300,
                      json={"user_id": VERIFY_USER, "message": "Hi, I am allergic to peanuts. What is a Class I recall?"})
    data = r.json() if r.status_code == 200 else {}
    check("POST /api/chat returns a reply", r.status_code == 200 and bool(data.get("reply")), f"HTTP {r.status_code}")
    mu = data.get("memory_used", {})
    check("chat response shows memory used (short-term, summaries, episodic facts)",
          {"short_term", "session_summary", "lifetime_summary", "episodic_facts"} <= set(mu), ", ".join(mu))
    parts = data.get("prompt_parts_tokens", {})
    check("chat response reports tokens per prompt part",
          {"system_primer", "long_term_summary", "short_term_window", "episodic_facts"} <= set(parts), parts)
    r = requests.get(f"{BASE_URL}/api/memory/{VERIFY_USER}", timeout=10)
    check("GET /api/memory/{user_id} works", r.status_code == 200 and len(r.json()["recent_messages"]) == 2,
          f"HTTP {r.status_code}")
    r = requests.get(f"{BASE_URL}/api/aggregate/{VERIFY_USER}", timeout=10)
    check("GET /api/aggregate/{user_id} returns daily counts",
          r.status_code == 200 and r.json()["daily_message_counts"][0]["total"] == 2, f"HTTP {r.status_code}")
    ep = get_episodes_collection().find_one({"user_id": VERIFY_USER})
    check("an episodic fact was stored with an embedding",
          ep is not None and len(ep["embedding"]) == 384 and 0 <= ep["importance"] <= 1,
          ep and f"{ep['fact']!r}, {len(ep['embedding'])} dims")
    for col in (get_messages_collection(), get_summaries_collection(), get_episodes_collection()):
        col.delete_many({"user_id": VERIFY_USER})
    real = get_messages_collection().count_documents({"user_id": "pinal"})
    check("the Part 2 test conversation is still stored", real >= 20, f"{real} messages for user pinal")


# --- Part 3: memory cost ---------------------------------------------------
def part3():
    import yaml
    probes = yaml.safe_load((HW / "memory_probes.yaml").read_text())
    check("memory_probes.yaml has 5 probes and a 1-5 rubric",
          len(probes["probes"]) == 5 and sorted(probes["rubric"]) == [1, 2, 3, 4, 5])
    rows = json.loads((HW / "raw" / "p3_turns.json").read_text())
    by = {}
    for r in rows:
        by.setdefault(r["setting"], []).append(r)
    ok = sorted(by) == ["n12", "n12_compress", "n30", "n4"] and all(len(v) == 35 for v in by.values())
    check("raw per-turn data: 4 settings x (30 turns + 5 probes)", ok, {k: len(v) for k, v in by.items()})
    keys = {"prompt_tokens", "completion_tokens", "tokens_system_primer", "tokens_long_term_summary",
            "tokens_short_term_window", "tokens_episodic_facts", "request_latency_ms"}
    check("each row logs tokens per prompt part and latency", keys <= set(rows[0]))
    summ = json.loads((HW / "raw" / "p3_summary.json").read_text())
    tok = {s["setting"]: s["mean_prompt_tokens"] for s in summ["settings"]}
    check("larger window costs more prompt tokens (N=4 < N=12 < N=30)", tok["n4"] < tok["n12"] < tok["n30"], tok)
    check("compression policy saves tokens vs N=12", tok["n12_compress"] < tok["n12"], tok)
    check("manual probe review present", (HW / "raw" / "p3_probe_manual_review.json").exists())
    check("METRICS.md has the memory-cost table", "Mean prompt tokens/turn" in (HW / "METRICS.md").read_text())


# --- Part 4: file-based memory ---------------------------------------------
def part4():
    from file_memory.consolidate import consolidate
    from file_memory.memory_files import count_memory_lines, needs_consolidation
    agent = (ROOT / "AGENT.md").read_text()
    sections = [s for s in ("project description", "technology stack", "coding conventions",
                            "testing approach", "prohibited actions") if f"## {s}" in agent.lower()]
    n_instr = len(re.findall(r"^- ", agent, flags=re.M))
    check("AGENT.md has >= 5 instructions in >= 3 categories", n_instr >= 5 and len(sections) >= 3,
          f"{n_instr} instructions, {len(sections)} categories")
    check("MEMORY.md exists and loads", (ROOT / "MEMORY.md").exists())
    original = (HW / "memory_test" / "MEMORY_original.md").read_text()
    check("test MEMORY.md has 55 lines", count_memory_lines(original) == 55, count_memory_lines(original))
    check("55-line file triggers consolidation", needs_consolidation(original)[0], needs_consolidation(original)[1])
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "MEMORY.md"
        copy.write_text(original)
        new_text, report = consolidate(copy.read_text())
    check("consolidation reduces it below 40 lines", report["lines_after"] < 40,
          f"{report['lines_before']} -> {report['lines_after']}")
    check("duplicates merged and contradictions resolved explicitly",
          len(report["duplicates_merged"]) >= 3 and len(report["contradictions_resolved"]) + len(report["needs_review"]) >= 3,
          f"{len(report['duplicates_merged'])} merged, {len(report['contradictions_resolved'])} resolved, "
          f"{len(report['needs_review'])} flagged")
    check("committed consolidated file is below 40 lines",
          count_memory_lines((HW / "memory_test" / "MEMORY_consolidated.md").read_text()) < 40)
    for name, cmd in (("file-memory tests pass", ["tests/test_file_memory.py"]),
                      ("AGENT.md rule check passes", ["scripts/check_agent_rules.py"])):
        p = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
        check(name, p.returncode == 0, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:])


def part0():
    for f in ("RUN_LOG.txt", "METRICS.md", "AI_USE.md"):
        check(f"reports/hw06/{f} present", (HW / f).exists())


if __name__ == "__main__":
    print(f"HW6 self-check against {BASE_URL}\n")
    guarded("Part 1 checks", part1)
    guarded("Part 2 checks", part2)
    guarded("Part 3 checks", part3)
    guarded("Part 4 checks", part4)
    guarded("report files", part0)
    passed = sum(c["passed"] for c in checks)
    out = {
        "homework": 6, "sid4": SID4, "port_base": PORT_BASE, "prefix": PREFIX, "domain_id": DOMAIN_ID,
        "seed": SEED, "verify_seed": VERIFY_SEED, "commit_hash": commit_hash(),
        "model": "qwen3:1.7b (local, via Ollama); embeddings sentence-transformers/all-MiniLM-L6-v2",
        "config": {"SHORT_TERM_N": 12, "SUMMARIZE_EVERY_USER_MSGS": 4, "EPISODIC_TOP_K": 3,
                   "mongo_db": f"{PREFIX}_doc"},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": f"{passed}/{len(checks)} checks passed",
        "checks": checks,
    }
    (HW / "verification.json").write_text(json.dumps(out, indent=2))
    print(f"\n{out['summary']} -- wrote reports/hw06/verification.json")
