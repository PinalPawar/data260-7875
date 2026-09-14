import json
import time
from pathlib import Path

from schema_agent import build_graph_v2

INPUT_PATH = Path("reports/hw02/cases/schema_input.json")
RAW_PATH = Path("reports/hw02/raw/experiment1_raw.json")
NUM_RUNS = 30


def classify(final_state):
    if final_state.get("validation_error") is None:
        turn_count = final_state.get("turn_count", 0)
        if turn_count <= 1:
            return "valid_first_attempt"
        elif turn_count == 2:
            return "valid_after_1_retry"
        else:
            return "valid_after_2plus_retries"
    else:
        return "hit_turn_ceiling"


def main():
    with open(INPUT_PATH) as f:
        fixed_input = json.load(f)

    graph = build_graph_v2()

    results = []
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)

    for i in range(1, NUM_RUNS + 1):
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
            "turn_ceiling": fixed_input["turn_ceiling"],
        }

        t0 = time.time()
        final_state = graph.invoke(initial_state)
        t1 = time.time()
        latency_ms = int((t1 - t0) * 1000)

        outcome = classify(final_state)

        record = {
            "run": i,
            "turn_count": final_state.get("turn_count"),
            "validation_error": final_state.get("validation_error"),
            "outcome": outcome,
            "latency_ms": latency_ms,
        }
        results.append(record)

        print(f"Run {i}/{NUM_RUNS}: {outcome} (turn_count={record['turn_count']}, latency={latency_ms} ms)")

        with open(RAW_PATH, "w") as f:
            json.dump(results, f, indent=2)

    categories = ["valid_first_attempt", "valid_after_1_retry", "valid_after_2plus_retries", "hit_turn_ceiling"]
    print(f"\n=== Summary over {NUM_RUNS} runs ===")
    print(f"{'Outcome':30} {'Count':>6} {'Mean latency (ms)':>20}")
    for cat in categories:
        subset = [r["latency_ms"] for r in results if r["outcome"] == cat]
        count = len(subset)
        mean_latency = int(sum(subset) / count) if count else 0
        print(f"{cat:30} {count:>6} {mean_latency:>20}")


if __name__ == "__main__":
    main()
