import json
import subprocess
import sys
import time
from pathlib import Path
from statistics import median

INPUT_FILE = Path("reports/hw01/cases/nondeterminism_input.json")
RAW_FILE = Path("reports/hw01/raw/nondeterminism_raw.json")
RUN_LOG_FILE = Path("reports/hw01/RUN_LOG.txt")
METRICS_FILE = Path("reports/hw01/METRICS.md")
RUNS_PER_TEMP = 20
TEMPS = [0.7, 0.0]


def log(msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(RUN_LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_input():
    with open(INPUT_FILE) as f:
        return json.load(f)


def load_existing_results():
    if RAW_FILE.exists():
        with open(RAW_FILE) as f:
            return json.load(f)
    return []


def save_results(results):
    with open(RAW_FILE, "w") as f:
        json.dump(results, f, indent=2)


def run_once(title: str, content: str, temperature: float, run_index: int):
    cmd = [
        sys.executable, "agents_demo.py",
        "--title", title,
        "--content", content,
        "--temperature", str(temperature),
    ]
    log(f"START run={run_index} temp={temperature} cmd={' '.join(cmd)}")
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    latency_ms = (time.perf_counter() - t0) * 1000

    stdout = proc.stdout
    marker = "Publish Package"
    idx = stdout.rfind(marker)
    tags, summary = None, None
    if idx != -1:
        json_text = stdout[idx + len(marker):].strip()
        try:
            package = json.loads(json_text)
            tags = package["agents"]["final"]["tags"]
            summary = package["agents"]["final"]["summary"]
        except Exception as e:
            log(f"WARN run={run_index} could not parse output JSON: {e}")
    else:
        log(f"WARN run={run_index} 'Publish Package' marker not found in output")

    if proc.returncode != 0:
        log(f"ERROR run={run_index} exited with code {proc.returncode}: {proc.stderr[-500:]}")

    log(f"END   run={run_index} temp={temperature} latency_ms={latency_ms:.0f} tags={tags}")

    return {
        "run_index": run_index,
        "temperature": temperature,
        "tags": tags,
        "summary": summary,
        "latency_ms": latency_ms,
        "returncode": proc.returncode,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def percentile(values, pct):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def compute_stats(results, temperature):
    subset = [r for r in results if r["temperature"] == temperature and r["tags"]]
    tag_sets = [frozenset(r["tags"]) for r in subset]
    distinct_sets = len(set(tag_sets))

    all_tags = [t for r in subset for t in r["tags"]]
    from collections import Counter
    counts = Counter(all_tags)
    n_runs = len(subset)
    in_all = sorted([t for t, c in counts.items() if c == n_runs])
    in_exactly_one = sorted([t for t, c in counts.items() if c == 1])

    latencies = [r["latency_ms"] for r in subset]
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)

    return {
        "n_runs": n_runs,
        "distinct_tag_sets": distinct_sets,
        "tags_in_all_runs": in_all,
        "tags_in_exactly_one_run": in_exactly_one,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_p99_ms": p99,
    }


def write_metrics_md(stats_07, stats_00):
    lines = []
    lines.append("# Non-Determinism Metrics (Part 3)\n")
    lines.append(f"Fixed input: `{INPUT_FILE}`\n")
    lines.append("| Metric | Temp 0.7 | Temp 0.0 |")
    lines.append("|---|---|---|")
    lines.append(f"| Distinct tag sets | {stats_07['distinct_tag_sets']} | {stats_00['distinct_tag_sets']} |")
    lines.append(f"| Tags in all {stats_07['n_runs']} runs | {', '.join(stats_07['tags_in_all_runs']) or '(none)'} | {', '.join(stats_00['tags_in_all_runs']) or '(none)'} |")
    lines.append(f"| Tags in exactly 1 run | {', '.join(stats_07['tags_in_exactly_one_run']) or '(none)'} | {', '.join(stats_00['tags_in_exactly_one_run']) or '(none)'} |")
    lines.append("\n| Metric | Temp 0.7 | Temp 0.0 |")
    lines.append("|---|---|---|")
    lines.append(f"| Latency p50 (ms) | {stats_07['latency_p50_ms']:.0f} | {stats_00['latency_p50_ms']:.0f} |")
    lines.append(f"| Latency p95 (ms) | {stats_07['latency_p95_ms']:.0f} | {stats_00['latency_p95_ms']:.0f} |")
    lines.append(f"| Latency p99 (ms) | {stats_07['latency_p99_ms']:.0f} | {stats_00['latency_p99_ms']:.0f} |")
    lines.append("")
    with open(METRICS_FILE, "w") as f:
        f.write("\n".join(lines))


def main():
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = load_input()
    title, content = data["title"], data["content"]

    results = load_existing_results()
    log(f"Resuming with {len(results)} existing results already recorded" if results else "Starting fresh")

    global_run_index = len(results)
    for temperature in TEMPS:
        done_for_temp = len([r for r in results if r["temperature"] == temperature])
        remaining = RUNS_PER_TEMP - done_for_temp
        if remaining <= 0:
            log(f"temp={temperature} already has {done_for_temp} runs, skipping")
            continue
        for i in range(remaining):
            global_run_index += 1
            record = run_once(title, content, temperature, global_run_index)
            results.append(record)
            save_results(results)  # save after every run so nothing is lost

    log("All runs complete. Computing stats...")
    stats_07 = compute_stats(results, 0.7)
    stats_00 = compute_stats(results, 0.0)
    write_metrics_md(stats_07, stats_00)
    log(f"Wrote {METRICS_FILE}")
    log(f"Wrote {RAW_FILE}")
    print("\nDone. See reports/hw01/METRICS.md and reports/hw01/raw/nondeterminism_raw.json")


if __name__ == "__main__":
    main()