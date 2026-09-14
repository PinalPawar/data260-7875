import json
import time
from pathlib import Path

from schema_agent import build_graph_v2

INPUT_PATH = Path("reports/hw02/cases/adversarial_input_v3.json")
RAW_PATH = Path("reports/hw02/raw/experiment3_v3_raw.json")
NUM_RUNS = 5


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

        hit_ceiling = final_state.get("validation_error") is not None

        record = {
            "run": i,
            "turn_count": final_state.get("turn_count"),
            "hit_ceiling": hit_ceiling,
            "final_validation_error": final_state.get("validation_error"),
            "final_tags": final_state.get("planner_proposal", {}).get("data", {}).get("tags"),
            "final_summary": final_state.get("planner_proposal", {}).get("data", {}).get("summary"),
            "latency_ms": latency_ms,
        }
        results.append(record)

        status = "HIT CEILING (never validated)" if hit_ceiling else "validated OK"
        print(f"Run {i}/{NUM_RUNS}: {status} (turn_count={record['turn_count']}, latency={latency_ms} ms)")
        print(f"   final tags: {record['final_tags']}")

        with open(RAW_PATH, "w") as f:
            json.dump(results, f, indent=2)

    ceiling_hits = sum(1 for r in results if r["hit_ceiling"])
    print(f"\n=== Summary: {ceiling_hits}/{NUM_RUNS} runs hit the turn ceiling ===")


if __name__ == "__main__":
    main()
