"""
HW7 Part 6 combined test run: (a) glob -> search -> read integration test, (b) the 10-command
safety-gate test. Everything happens inside a fresh temporary sandbox that is deleted at the end.

    python scripts/run_hw07_part6.py                    # integration with qwen3:8b (Ollama)
    python scripts/run_hw07_part6.py --model scripted   # no model (offline check of the wiring)

Append the console to the run log with:  ... 2>&1 | tee -a reports/hw07/RUN_LOG.txt
Raw results: reports/hw07/raw/part6_results.json
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from file_tools import tools as ft  # noqa: E402
from file_tools.agent import run_file_agent  # noqa: E402
from file_tools.gate import (  # noqa: E402
    SAFE_PREFIXES,
    confirm_bash,
    is_destructive,
    prefix_only_gate,
)

RAW = os.path.join(ROOT, "reports", "hw07", "raw", "part6_results.json")
FILES = {
    "app.py": (
        "from utils import load_config\n\n\n"
        "def main():\n"
        '    print("starting", load_config())\n\n\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    ),
    "utils.py": (
        "DEBUG = True  # turn off before release\n\n\n"
        "def load_config():\n"
        '    return {"debug": DEBUG, "region": "sf"}\n'
    ),
    "report.py": 'def summary(rows):\n    return f"{len(rows)} rows"\n',
}
DEBUG_FILE = "utils.py"
INSTRUCTION = (
    "Find the Python file in this folder that contains DEBUG and show me its contents. "
    "First use glob_files to list the .py files, then search_in_files for DEBUG in them, "
    "then read_file on the file that matched."
)
GATE_CASES = [  # (command, expected: "allow" or "block")
    ("ls -la", "allow"),
    ("cat utils.py", "allow"),
    ("grep -n DEBUG *.py", "allow"),
    ("wc -l *.py", "allow"),
    ("echo done > notes.txt", "allow"),
    ("rm -rf build", "block"),
    ("sudo rm app.py", "block"),
    ("ls && chmod -R 777 .", "block"),
    ("echo pwned > /etc/hosts", "block"),
    ("dd if=/dev/zero of=/dev/disk2", "block"),
]


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def scripted_model():
    from fake_llm import ScriptedToolModel

    return ScriptedToolModel(
        replies=[
            [("glob_files", {"pattern": "**/*.py"})],
            [("search_in_files", {"query": "DEBUG", "file_pattern": "*.py"})],
            [("read_file", {"path": DEBUG_FILE})],
            f"utils.py contains DEBUG:\n\n{FILES[DEBUG_FILE]}",
        ]
    )


def integration(root: str, model_name: str) -> dict:
    print("\n(a) Integration test: glob -> search -> read")
    for name, text in FILES.items():
        env = ft.write_file(root, name, text)
        print(f"    write_file {name:10} -> {env['data']['bytes']} bytes")
    print(f"    instruction: {INSTRUCTION}")
    if model_name == "scripted":
        model = scripted_model()
    else:
        from bike_agent.agent import make_model

        model = make_model(model_name)
    run = run_file_agent(root, INSTRUCTION, model)
    for e in run["timeline"]:
        if e["type"] == "tool_call":
            print(f"    call  {e['t_ms'] / 1000:5.1f}s {e['tool']}({json.dumps(e['input'])})")
        elif e["type"] == "observation":
            print(f"    obs   {e['t_ms'] / 1000:5.1f}s {e['output'][:150]}")
    print("    final answer:")
    for line in run["final_text"].strip().splitlines():
        print(f"      | {line}")
    calls = [e for e in run["timeline"] if e["type"] == "tool_call"]
    names = [c["tool"] for c in calls]
    first = {
        n: names.index(n) for n in ("glob_files", "search_in_files", "read_file") if n in names
    }
    reads = [c["input"].get("path", "").lstrip("./") for c in calls if c["tool"] == "read_file"]
    checks = {
        "order glob -> search -> read": len(first) == 3
        and first["glob_files"] < first["search_in_files"] < first["read_file"],
        f"read_file opened {DEBUG_FILE}": DEBUG_FILE in reads,
        "answer shows the file's contents": all(
            line.strip() in run["final_text"]
            for line in FILES[DEBUG_FILE].splitlines()
            if line.strip()
        ),
    }
    for k, v in checks.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")
    print(f"    steps={run['steps']} stop={run['stop_reason']} time={run['total_ms'] / 1000:.1f}s")
    return {"tool_sequence": names, "checks": checks, **run}


def gate_test(root: str) -> dict:
    print("\n(b) Safety-gate test (pure Python, no model)")
    print(f"    SAFE_PREFIXES = {SAFE_PREFIXES}")
    print(f"    {'command':32} {'expect':6} {'v1 prefix-only':16} {'final gate':10} reason")
    rows, false_v1, wrong_final = [], [], []
    for cmd, expect in GATE_CASES:
        v1 = prefix_only_gate(cmd)
        final = confirm_bash(cmd)
        got = "allow" if final["allow"] else "block"
        v1got = "allow" if v1["allow"] else "block"
        note = ""
        if v1got == "allow" and expect == "block":
            false_v1.append(cmd)
            note = "  <- v1 FALSE ALLOW, fixed"
        if got != expect:
            wrong_final.append(cmd)
            note += "  <- FINAL MISMATCH"
        print(f"    {cmd:32} {expect:6} {v1got:16} {got:10} {final['reason']}{note}")
        rows.append(
            {
                "command": cmd,
                "expected": expect,
                "v1_prefix_only": v1got,
                "final": got,
                "is_destructive": is_destructive(cmd),
                "reason": final["reason"],
            }
        )
    allowed = sum(r["final"] == "allow" for r in rows)
    print(f"    v1 false allows: {len(false_v1)} {false_v1}")
    false_final = [r["command"] for r in rows if r["final"] == "allow" and r["expected"] == "block"]
    print(
        f"    final gate: {allowed} allowed, {len(rows) - allowed} blocked, "
        f"{len(false_final)} false allows, {len(wrong_final)} mismatches"
    )
    confirmed = confirm_bash("rm -rf build", auto_approve=True)
    print(
        f"    with explicit confirmation: rm -rf build -> "
        f"{'allow' if confirmed['allow'] else 'block'} ({confirmed['reason']})"
    )
    ran = ft.bash(root, "grep -n DEBUG *.py")
    refused = ft.bash(root, "ls && chmod -R 777 .")
    shown = ran["data"]["output"].strip().replace("\n", " | ")
    print(f"    bash tool, allowed : grep -n DEBUG *.py -> {shown}")
    print(f"    bash tool, blocked : ls && chmod -R 777 . -> {refused['error']}")
    return {
        "rows": rows,
        "v1_false_allows": false_v1,
        "final_mismatches": wrong_final,
        "confirmed_example": confirmed,
        "bash_allowed": ran,
        "bash_blocked": refused,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b")
    args = ap.parse_args()
    root = tempfile.mkdtemp(prefix="data260_hw7_sandbox_")
    print(f"=== Part 6 combined test  {stamp()}  model={args.model} ===")
    print(f"    sandbox: {root}")
    try:
        a = integration(root, args.model)
        b = gate_test(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        print(f"    sandbox removed: {not os.path.exists(root)}")
    ok_a = all(a["checks"].values())
    ok_b = not b["final_mismatches"]
    print(
        f"=== RESULT: integration {'PASS' if ok_a else 'FAIL'}; "
        f"gate {'PASS' if ok_b else 'FAIL'} (5 allowed / 5 blocked) ==="
    )
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    with open(RAW, "w") as f:
        json.dump(
            {"ts": stamp(), "model": args.model, "integration": a, "gate": b},
            f,
            indent=2,
            default=str,
        )


if __name__ == "__main__":
    main()
