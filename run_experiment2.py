import json
import time
from pathlib import Path

from schema_agent import build_graph_v2

INPUT_PATH = Path("reports/hw02/cases/schema_input.json")
RAW_PATH = Path("reports/hw02/raw/experiment2_raw.json")
NUM_RUNS_PER_CEILING = 20
CEILINGS = [2, 10]


def main():
    with open(INPUT_PATH) as f:
        fixed_input = json.load(f)

    graph = build_graph_v2()

    results = []
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)

    for ceiling in CEILINGS:
        for i in range(1, NUM_RUNS_PER_CEILING + 1):
            initial_state = {
                "title": fixed_input["title"],
                "content": fixed_input["content"],
                "email": fixed_input["email"],
                "strict": fixed_input["strict"],
                "task": "",
                "llm": fixed_input["llm"],
                "planner_proposal": None,
                "validation_error": None,
                "turn_count": 0,
                "turn_ceiling": ceiling,
            }

            t0 = time.time()
            final_state = graph.invoke(initial_state)
            t1 = time.time()
            latency_ms = int((t1 - t0) * 1000)

            completed = final_state.get("validation_error") is None

            record = {
                "ceiling": ceiling,
                "run": i,
                "turn_count": final_state.get("turn_count"),
                "completed": completed,
                "latency_ms": latency_ms,
            }
            results.append(record)

            status = "OK" if completed else "FAILED (ceiling hit)"
            print(f"[ceiling={ceiling}] Run {i}/{NUM_RUNS_PER_CEILING}: {status} (turn_count={record['turn_count']}, latency={latency_ms} ms)")

            with open(RAW_PATH, "w") as f:
                json.dump(results, f, indent=2)

    print("\n=== Summary: turn ceiling comparison ===")
    print(f"{'Ceiling':>10} {'Completion Rate':>18} {'Mean Latency (ms)':>20}")
    for ceiling in CEILINGS:
        subset = [r for r in results if r["ceiling"] == ceiling]
        completed = [r for r in subset if r["completed"]]
        rate = len(completed) / len(subset) * 100
        mean_latency = int(sum(r["latency_ms"] for r in subset) / len(subset))
        print(f"{ceiling:>10} {rate:>17.1f}% {mean_latency:>20}")


if __name__ == "__main__":
    main()
