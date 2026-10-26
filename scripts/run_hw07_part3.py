"""
HW7 Part 3 runner: original loop vs bounded Reflexion on the same fixed tasks.

Usage (repo root; MySQL and Ollama running):
    python scripts/run_hw07_part3.py compare       # 21 paired runs, same seeds as Part 2
    python scripts/run_hw07_part3.py reflections   # print the stored reflections + evidence
    python scripts/run_hw07_part3.py review        # apply manual labels -> false rejections
    python scripts/run_hw07_part3.py compare --reflector grounded   # verifier-grounded reflections
    python scripts/run_hw07_part3.py table         # original vs both reflection writers

Each run uses Part 2's settings (temperature 0.7, seed SEED + attempt). Attempt 0 of the
Reflexion run IS the original Part 2 loop on that seed, so "original" is measured on
exactly the same run, and Reflexion adds only what its retries cost.
Append the console to the log with:  ... 2>&1 | tee -a reports/hw07/RUN_LOG.txt
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recall_tools import reflexion  # noqa: E402
from recall_tools.agent_loop import MODEL_NAME, SEED, hw1_chat  # noqa: E402
from recall_tools.task_checks import load_cases  # noqa: E402

RAW = os.path.join("reports", "hw07", "raw")
USER_ID = "pinal-7875"
TEMPERATURE = 0.7
# --reflector model    : the model writes the reflection (files part3_*)
# --reflector grounded : built from the verifier's evidence (files part3_grounded_*)
REFLECTOR = "model"
PREFIX = "part3"


def now() -> str:
    """Local time for log lines."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def raw_path(name: str) -> str:
    """Path under reports/hw07/raw/, creating the folder."""
    os.makedirs(RAW, exist_ok=True)
    return os.path.join(RAW, name)


def paired_row(i: int, seed: int, run: dict, wall_ms: float) -> dict:
    """Original (attempt 0 only) vs Reflexion (all attempts) for one task run."""
    first, last = run["attempts"][0], run["attempts"][-1]
    return {
        "run": i,
        "task_id": run["task_id"],
        "seed": seed,
        "orig_success": first["passed"],
        "orig_unsupported": len(first["unsupported_claims"]),
        "orig_tool_calls": first["tool_calls"],
        "orig_tokens": first["input_tokens"] + first["output_tokens"],
        "orig_latency_ms": first["latency_ms"],
        "refl_status": run["status"],
        "refl_success": run["status"] == "success",
        "refl_unsupported": len(last["unsupported_claims"]),
        "refl_retries": run["retries"],
        "refl_tool_calls": run["tool_calls"],
        "refl_tokens": run["tokens"],
        "refl_latency_ms": round(wall_ms, 1),
    }


def print_run(row: dict, run: dict) -> None:
    """One console line per run, plus any reflection written during it."""
    print(
        f"run {row['run']:>2} task {row['task_id']} seed {row['seed']}: original "
        f"{'PASS' if row['orig_success'] else 'FAIL'} -> reflexion {run['status']} "
        f"(retries {run['retries']}, tool calls {run['tool_calls']}, tokens {run['tokens']})"
    )
    for rec in run["reflections"]:
        failed = [c["check"] for c in rec["evidence"]["failed_checks"]]
        print(
            f"     reflection after attempt {rec['failed_attempt']} [{rec['source']}] "
            f"failed={failed}: {rec['reflection']}"
        )


def mean(rows: list, key: str) -> float:
    """Average of one column."""
    return round(sum(float(r[key]) for r in rows) / len(rows), 1) if rows else 0.0


def summarize(rows: list, false_rejections: dict) -> dict:
    """The Part 3 comparison table."""
    n = len(rows)
    return {
        "model": MODEL_NAME,
        "temperature": TEMPERATURE,
        "runs": n,
        "budgets": {
            "max_retries": reflexion.MAX_RETRIES,
            "tool_calls": reflexion.TOOL_CALL_BUDGET,
            "tokens": reflexion.TOKEN_BUDGET,
        },
        "original": {
            "task_success": sum(r["orig_success"] for r in rows),
            "unsupported_claims": sum(r["orig_unsupported"] for r in rows),
            "retry_rate": 0.0,
            "tool_calls_mean": mean(rows, "orig_tool_calls"),
            "tokens_mean": mean(rows, "orig_tokens"),
            "latency_ms_mean": mean(rows, "orig_latency_ms"),
            "verifier_false_rejections": false_rejections.get("original", "pending"),
        },
        "reflexion": {
            "task_success": sum(r["refl_success"] for r in rows),
            "unsupported_claims": sum(r["refl_unsupported"] for r in rows),
            "retry_rate": round(sum(r["refl_retries"] > 0 for r in rows) / n, 3),
            "total_retries": sum(int(r["refl_retries"]) for r in rows),
            "tool_calls_mean": mean(rows, "refl_tool_calls"),
            "tokens_mean": mean(rows, "refl_tokens"),
            "latency_ms_mean": mean(rows, "refl_latency_ms"),
            "statuses": {
                s: sum(r["refl_status"] == s for r in rows)
                for s in ("success", "budget_exhausted", "human_review")
            },
            "verifier_false_rejections": false_rejections.get("reflexion", "pending"),
        },
    }


def review_rows(runs: list) -> list:
    """Every attempt the verifier rejected, for a manual correct/incorrect check."""
    out = []
    for run in runs:
        for a in run["attempts"]:
            if not a["passed"]:
                failed = [c["check"] for c in a["checks"] if not c["passed"]]
                out.append(
                    {
                        "key": f"{run['index']}-{a['attempt']}",
                        "task_id": run["task_id"],
                        "attempt": a["attempt"],
                        "failed_checks": ";".join(failed),
                        "answer": a["answer"].replace("\n", " ")[:600],
                        "manual_label": "",
                    }
                )
    return out


def write_outputs(rows: list, runs: list) -> dict:
    """Raw CSV/JSON files plus the summary."""
    with open(raw_path(f"{PREFIX}_comparison_rows.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with open(raw_path(f"{PREFIX}_comparison_runs.json"), "w") as f:
        json.dump(runs, f, indent=2, default=str)
    rejected = review_rows(runs)
    with open(raw_path(f"{PREFIX}_rejections_for_review.csv"), "w", newline="") as f:
        fields = ["key", "task_id", "attempt", "failed_checks", "answer", "manual_label"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rejected)
    summary = summarize(rows, {})
    with open(raw_path(f"{PREFIX}_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return summary


def compare(attempts: int) -> None:
    """21 paired runs over tasks A, B, C with the Part 2 seeds."""
    tasks = load_cases()["tasks"]
    store = reflexion.ReflectionStore(raw_path(f"{PREFIX}_reflections.jsonl"))
    open(store.path, "w").close()  # fresh store for this comparison run
    if REFLECTOR == "grounded":
        reflect = reflexion.grounded_reflection
    else:
        reflect = reflexion.model_reflector(temperature=0.0, seed=SEED)
    print(
        f"HW7 Part 3 compare - Pinal Pawar (SID4 7875) - {now()} - model {MODEL_NAME}, "
        f"temperature {TEMPERATURE}, reflector {REFLECTOR}, "
        f"max_retries {reflexion.MAX_RETRIES}, budgets "
        f"{reflexion.TOOL_CALL_BUDGET} tool calls / {reflexion.TOKEN_BUDGET} tokens"
    )
    rows, runs = [], []
    for i in range(1, attempts + 1):
        task, seed = tasks[(i - 1) % len(tasks)], SEED + i
        started = time.perf_counter()
        run = reflexion.run_reflexion(
            task,
            USER_ID,
            reflect=reflect,
            store=store,
            chat_for=lambda n, s=seed: hw1_chat(temperature=TEMPERATURE, seed=s + 1000 * n),
        )
        rows.append(paired_row(i, seed, run, (time.perf_counter() - started) * 1000))
        runs.append({"index": i, "seed": seed, **run})
        print_run(rows[-1], run)
    print_summary(write_outputs(rows, runs))


def print_summary(s: dict) -> None:
    """Console version of the comparison table."""
    print(f"\n===== Original vs Reflexion [Pinal Pawar, SID4 7875] - {now()} =====")
    print(f"{'metric':<28}{'original':>14}{'reflexion':>14}")
    for key in (
        "task_success",
        "unsupported_claims",
        "retry_rate",
        "tool_calls_mean",
        "tokens_mean",
        "latency_ms_mean",
        "verifier_false_rejections",
    ):
        print(f"{key:<28}{str(s['original'][key]):>14}{str(s['reflexion'][key]):>14}")
    print(f"reflexion statuses: {s['reflexion']['statuses']}  (runs: {s['runs']})")


def show_reflections() -> None:
    """Print stored reflections with the evidence that triggered them (for the screenshot)."""
    store = reflexion.ReflectionStore(raw_path(f"{PREFIX}_reflections.jsonl"))
    rows = [json.loads(line) for line in open(store.path) if line.strip()]
    print(f"Stored reflections [Pinal Pawar, SID4 7875] - {len(rows)} record(s) - {store.path}")
    for r in rows:
        ev = r["evidence"]
        print(
            f"\nuser {r['user_id']} | run {r['run_id']} | task {r['task_id']} | "
            f"after attempt {r['failed_attempt']} | source {r['source']}"
        )
        print(f"  failed checks : {[(c['check'], c['detail']) for c in ev['failed_checks']]}")
        print(f"  tool sequence : {ev['tool_sequence']}")
        print(f"  last call     : {ev['last_tool_call']}")
        print(f"  observation   : {ev['last_observation']}")
        print(f"  unsupported   : {ev['unsupported_claims']}")
        print(f"  reflection    : {r['reflection']}")


def review() -> None:
    """Recompute false rejections from reports/hw07/raw/part3_manual_review.json labels."""
    labels = json.load(open(raw_path(f"{PREFIX}_manual_review.json")))
    runs = json.load(open(raw_path(f"{PREFIX}_comparison_runs.json")))
    false = {"original": 0, "reflexion": 0}
    for run in runs:
        for a in run["attempts"]:
            if not a["passed"] and labels.get(f"{run['index']}-{a['attempt']}") == "correct":
                false["reflexion"] += 1
                false["original"] += a["attempt"] == 0
    rows = list(csv.DictReader(open(raw_path(f"{PREFIX}_comparison_rows.csv"))))
    for r in rows:
        for k in ("orig_success", "refl_success"):
            r[k] = r[k] == "True"
        r["refl_retries"] = int(r["refl_retries"])
        for k in ("orig_unsupported", "refl_unsupported"):
            r[k] = int(r[k])
    summary = summarize(rows, false)
    with open(raw_path(f"{PREFIX}_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print_summary(summary)


def three_way() -> None:
    """Original vs model-written vs verifier-grounded reflections, from the two summaries."""
    model = json.load(open(raw_path("part3_summary.json")))
    grounded = json.load(open(raw_path("part3_grounded_summary.json")))
    print(
        f"\n===== Original vs Reflexion (two reflection writers) [Pinal Pawar, SID4 7875] - {now()}"
    )
    print(f"{'metric':<28}{'original':>12}{'refl-model':>13}{'refl-grounded':>15}")
    keys = (
        "task_success",
        "unsupported_claims",
        "retry_rate",
        "tool_calls_mean",
        "tokens_mean",
        "latency_ms_mean",
        "verifier_false_rejections",
    )
    for key in keys:
        cols = (model["original"][key], model["reflexion"][key], grounded["reflexion"][key])
        print(f"{key:<28}{str(cols[0]):>12}{str(cols[1]):>13}{str(cols[2]):>15}")
    print(f"statuses  model: {model['reflexion']['statuses']}")
    print(f"statuses  grounded: {grounded['reflexion']['statuses']}")
    with open(raw_path("part3_three_way.json"), "w") as f:
        json.dump(
            {
                "original": model["original"],
                "reflexion_model": model["reflexion"],
                "reflexion_grounded": grounded["reflexion"],
            },
            f,
            indent=2,
        )


def main() -> None:
    """Parse the mode and run it."""
    global REFLECTOR, PREFIX
    parser = argparse.ArgumentParser(description="HW7 Part 3 original vs Reflexion")
    parser.add_argument("mode", choices=["compare", "reflections", "review", "table"])
    parser.add_argument("--reflector", choices=["model", "grounded"], default="model")
    parser.add_argument("--attempts", type=int, default=21)
    args = parser.parse_args()
    REFLECTOR = args.reflector
    PREFIX = "part3" if REFLECTOR == "model" else "part3_grounded"
    if args.mode == "compare":
        compare(args.attempts)
    elif args.mode == "table":
        three_way()
    elif args.mode == "reflections":
        show_reflections()
    else:
        review()


if __name__ == "__main__":
    main()
