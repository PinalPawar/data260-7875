"""
HW7 Part 2 runner: verification tasks, error recovery, and the reliability measurement.

Usage (repo root; MySQL and Ollama running):
    python scripts/run_hw07_part2.py demo          # tasks A, B, C once each (temperature 0)
    python scripts/run_hw07_part2.py error         # nonexistent notice id
    python scripts/run_hw07_part2.py reliability   # 21 attempts (7 x A, B, C), temperature 0.7
    python scripts/run_hw07_part2.py replay --task B --seed 7883   # re-run one attempt exactly

Append the console to the run log with:  ... 2>&1 | tee -a reports/hw07/RUN_LOG.txt
Raw results go to reports/hw07/raw/.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recall_tools.agent_loop import (  # noqa: E402
    LOST_CHAIN,
    MALFORMED,
    MAX_ITERATIONS,
    MAX_REPAIRS,
    MODEL_NAME,
    SEED,
    TEXT_INSTEAD,
    UNKNOWN_TOOL,
    hw1_chat,
    run_agent,
)
from recall_tools.task_checks import load_cases, verify_task  # noqa: E402

RAW_DIR = os.path.join("reports", "hw07", "raw")
FAILURE_TYPES = [MALFORMED, UNKNOWN_TOOL, TEXT_INSTEAD, LOST_CHAIN]
CHAIN_CHECKS = {
    "search_ran",
    "detail_of_first_result",
    "aggregate_ran",
    "example_from_top_group",
    "two_detail_lookups",
}


def now() -> str:
    """Current local time for log lines."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_json(name: str, data: object) -> str:
    """Write one raw JSON file under reports/hw07/raw/ and return its path."""
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def show_run(label: str, task: dict, result: dict, verdict: dict) -> None:
    """Print one run the way the screenshots need it."""
    print(f"\n----- Task {label} [Pinal Pawar, SID4 7875] -----")
    print(f"question     : {task['prompt']}")
    for t in result["trace"]:
        outcome = "ok" if t["result"]["ok"] else f"error: {t['result']['error']}"
        print(f"  tool #{t['n']}: {t['tool']}({json.dumps(t['arguments'])}) -> {outcome}")
    print(f"answer       : {result['answer']}")
    print(
        f"stop reason  : {result['stop_reason']}   total tool calls: {result['tool_calls']}   "
        f"model turns: {result['iterations']}   repairs: {result['repairs_used']}   "
        f"parallel calls not run: {result.get('parallel_calls_dropped', 0)}"
    )
    checks = ", ".join(
        f"{c['check']}={'PASS' if c['passed'] else 'FAIL'}" for c in verdict["checks"]
    )
    print(f"verifier     : {'PASS' if verdict['passed'] else 'FAIL'}  ({checks})")


def run_demo(tasks: list, file_name: str, temperature: float = 0.0, seed: int = SEED) -> None:
    """Run each task once (default temperature 0, seed SEED) and save the full traces."""
    chat = hw1_chat(temperature=temperature, seed=seed)
    print(
        f"HW7 Part 2 - Pinal Pawar (SID4 7875) - {now()} - model {MODEL_NAME}, "
        f"temperature {temperature}, seed {seed}, max_iterations {MAX_ITERATIONS}, "
        f"max_repairs {MAX_REPAIRS}"
    )
    runs = []
    for task in tasks:
        result = run_agent(task["prompt"], chat=chat)
        verdict = verify_task(task, result)
        show_run(task["id"], task, result, verdict)
        runs.append({"task": task, "result": result, "verdict": verdict})
    print(f"\nsaved {save_json(file_name, runs)}")


def classify_attempt(result: dict, verdict: dict) -> str:
    """Attempt-level outcome: success, lost chain, answer check failed, or the stop reason."""
    if verdict["passed"]:
        return "success"
    failed = {c["check"] for c in verdict["checks"] if not c["passed"]}
    if result["stop_reason"] != "final_answer":
        return result["stop_reason"]
    return LOST_CHAIN if failed & CHAIN_CHECKS else "answer_check_failed"


def attempt_row(i: int, task: dict, seed: int, result: dict, verdict: dict) -> dict:
    """One CSV row per attempt: call-level well-formedness before/after repair plus outcome."""
    events = result["call_events"]
    slots = sorted({e["slot"] for e in events})
    first = [e for e in events if not e["repair_attempt"]]
    final_ok = sum(1 for s in slots if [e for e in events if e["slot"] == s][-1]["well_formed"])
    failures = Counter(e["failure_type"] for e in first if e["failure_type"])
    outcome = classify_attempt(result, verdict)
    return {
        "attempt": i,
        "task_id": task["id"],
        "seed": seed,
        "intended_calls": len(slots),
        "well_formed_first_try": sum(e["well_formed"] for e in first),
        "well_formed_after_repair": final_ok,
        "repairs_used": result["repairs_used"],
        "parallel_calls_dropped": result.get("parallel_calls_dropped", 0),
        **{f"fail_{t}": failures.get(t, 0) for t in (MALFORMED, UNKNOWN_TOOL, TEXT_INSTEAD)},
        "lost_chain": int(outcome == LOST_CHAIN),
        "outcome": outcome,
        "verifier_passed": verdict["passed"],
        "tool_calls_executed": result["tool_calls"],
        "stop_reason": result["stop_reason"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "latency_ms": result["latency_ms"],
        "answer": result["answer"][:300].replace("\n", " "),
    }


def summarize(rows: list, temperature: float) -> dict:
    """Totals for the METRICS table."""
    slots = sum(r["intended_calls"] for r in rows)
    before = sum(r["well_formed_first_try"] for r in rows)
    after = sum(r["well_formed_after_repair"] for r in rows)
    pct = lambda n, d: round(100.0 * n / d, 1) if d else 0.0  # noqa: E731
    return {
        "model": MODEL_NAME,
        "temperature": temperature,
        "seeds": f"{SEED}+attempt",
        "attempts": len(rows),
        "intended_calls": slots,
        "well_formed_before_repair": before,
        "well_formed_before_repair_pct": pct(before, slots),
        "well_formed_after_repair": after,
        "well_formed_after_repair_pct": pct(after, slots),
        "failures": {
            MALFORMED: sum(r[f"fail_{MALFORMED}"] for r in rows),
            UNKNOWN_TOOL: sum(r[f"fail_{UNKNOWN_TOOL}"] for r in rows),
            TEXT_INSTEAD: sum(r[f"fail_{TEXT_INSTEAD}"] for r in rows),
            LOST_CHAIN: sum(r["lost_chain"] for r in rows),
        },
        "attempts_passed": sum(r["verifier_passed"] for r in rows),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "per_task_passed": {
            t: sum(r["verifier_passed"] for r in rows if r["task_id"] == t)
            for t in sorted({r["task_id"] for r in rows})
        },
    }


def print_summary(s: dict) -> None:
    """Console version of the reliability table."""
    print(f"\n===== Reliability summary [Pinal Pawar, SID4 7875] - {now()} =====")
    print(
        f"attempts {s['attempts']}  intended tool calls {s['intended_calls']}  model {s['model']} "
        f"temperature {s['temperature']}"
    )
    print(
        f"well-formed before repair : {s['well_formed_before_repair']}/{s['intended_calls']} "
        f"({s['well_formed_before_repair_pct']}%)"
    )
    print(
        f"well-formed after repair  : {s['well_formed_after_repair']}/{s['intended_calls']} "
        f"({s['well_formed_after_repair_pct']}%)"
    )
    for name, count in s["failures"].items():
        print(f"  {name:<24}: {count}")
    passed = f"{s['attempts_passed']}/{s['attempts']}"
    print(f"attempts passing verifier : {passed}  {s['per_task_passed']}")
    print(f"outcomes                  : {s['outcomes']}")


def run_reliability(tasks: list, attempts: int, temperature: float) -> None:
    """Cycle through the fixed tasks with identical settings (seed = SEED + attempt)."""
    print(
        f"HW7 Part 2 reliability - Pinal Pawar (SID4 7875) - {now()} - model {MODEL_NAME}, "
        f"temperature {temperature}, {attempts} attempts, max_repairs {MAX_REPAIRS}"
    )
    rows, events = [], []
    for i in range(1, attempts + 1):
        task, seed = tasks[(i - 1) % len(tasks)], SEED + i
        result = run_agent(task["prompt"], chat=hw1_chat(temperature=temperature, seed=seed))
        verdict = verify_task(task, result)
        rows.append(attempt_row(i, task, seed, result, verdict))
        events += [{"attempt": i, "task_id": task["id"], **e} for e in result["call_events"]]
        r = rows[-1]
        print(
            f"attempt {i:>2} task {task['id']} seed {seed}: calls {r['intended_calls']} "
            f"well-formed {r['well_formed_first_try']}->{r['well_formed_after_repair']} "
            f"repairs {r['repairs_used']} outcome {r['outcome']}"
        )
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, "part2_reliability_attempts.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save_json("part2_reliability_events.json", events)
    summary = summarize(rows, temperature)
    save_json("part2_reliability_summary.json", summary)
    print_summary(summary)


def main() -> None:
    """Parse the mode and run it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("mode", choices=["demo", "error", "reliability", "replay"])
    parser.add_argument("--attempts", type=int, default=21)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--task", choices=["A", "B", "C"], help="replay: which fixed task")
    parser.add_argument("--seed", type=int, help="replay: the attempt's seed (SEED + attempt)")
    args = parser.parse_args()
    cases = load_cases()
    if args.mode == "demo":
        run_demo(cases["tasks"], "part2_demo_runs.json")
    elif args.mode == "error":
        run_demo([cases["error_case"]], "part2_error_case.json")
    elif args.mode == "replay":
        task = next(t for t in cases["tasks"] if t["id"] == args.task)
        name = f"part2_replay_{args.task}_seed{args.seed}.json"
        run_demo([task], name, temperature=args.temperature, seed=args.seed)
    else:
        run_reliability(cases["tasks"], args.attempts, args.temperature)


if __name__ == "__main__":
    main()
