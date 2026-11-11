"""HW10 Part 4.3: 50 confirmed cache-miss requests, then p50/p95 per stage.

Every request goes through the traced ingress with store=False (so none of these answers is
ever cached) and with the Part 2 evaluator on. A request counts only if its cache_lookup span
says result=miss; any hit is excluded and the next question is used. Resumable: finished
trace ids are kept in reports/hw10/raw/part4_latency_traces.json.

    python hw10/latency_experiment.py            # needs Kafka + planner/writer/reviewer + Ollama
    python hw10/latency_experiment.py --report   # only recompute the table from spans.jsonl
"""

import argparse
import json

import yaml

import hw10cfg as cfg
from trace_analysis import latency_table, load_jsonl

TRACES = cfg.RAW / "part4_latency_traces.json"
TARGET = 50


def confirmed_miss(trace_id: str) -> bool:
    """True if this trace's cache_lookup span recorded a miss."""
    for s in load_jsonl(cfg.SPANS):
        if s["trace_id"] == trace_id and s["stage"] == "cache_lookup":
            return s["attrs"].get("result") == "miss"
    return False


def run(target: int) -> dict:
    """Send questions until `target` confirmed misses are recorded."""
    from ingress import ask
    state = json.loads(TRACES.read_text()) if TRACES.exists() else {"misses": [], "excluded": []}
    done_q = {m["question"] for m in state["misses"]} | {e["question"] for e in state["excluded"]}
    qs = [q for q in yaml.safe_load(open(cfg.HW10 / "latency_questions.yaml"))["questions"]
          if q not in done_q]
    for q in qs:
        if len(state["misses"]) >= target:
            break
        row = ask(q, store=False, evaluate=True, kind="latency")
        ok = (not row["is_cached"]) and confirmed_miss(row["trace_id"]) and row["status"] == "ok"
        rec = {"trace_id": row["trace_id"], "question": q, "e2e_ms": row["e2e_ms"],
               "status": row["status"], "is_cached": row["is_cached"]}
        (state["misses"] if ok else state["excluded"]).append(rec)
        print(f"[{len(state['misses']):>2}/{target}] {'MISS' if ok else 'EXCLUDED'} "
              f"e2e={row['e2e_ms']:>9.1f} ms  status={row['status']}  {q[:55]}")
        TRACES.write_text(json.dumps(state, indent=2))
    return state


def report(state: dict) -> dict:
    """Compute, print and save the Part 4.3 table (+ cache-hit latency kept separate)."""
    spans = load_jsonl(cfg.SPANS)
    ids = [m["trace_id"] for m in state["misses"]]
    tab = latency_table(spans, ids)
    hits = [s["duration_ms"] for s in spans if s["stage"] == "request"
            and s["attrs"].get("is_cached")]
    from trace_analysis import percentile
    tab["cache_hit_e2e"] = {"n": len(hits), "p50_ms": percentile(hits, 50),
                            "p95_ms": percentile(hits, 95)}
    tab["all_cache_lookup_results_miss"] = all(confirmed_miss(t) for t in ids)
    tab["excluded"] = state["excluded"]
    print(f"\n{'Stage':<20}{'p50 (ms)':>12}{'p95 (ms)':>12}{'% of e2e':>10}")
    for r in tab["rows"]:
        print(f"{r['stage']:<20}{r['p50_ms']:>12}{r['p95_ms']:>12}{r['pct_of_e2e']:>9}%")
    e = tab["end_to_end"]
    print(f"{'End-to-end (miss)':<20}{e['p50_ms']:>12}{e['p95_ms']:>12}{'100':>9}%")
    print(f"unattributed (embedding/ingress overhead): {tab['unattributed_pct']}%")
    print(f"dominant contributor: {tab['dominant']}   n={tab['n_traces']}   "
          f"all confirmed misses: {tab['all_cache_lookup_results_miss']}")
    print(f"cache-hit e2e (separate): {tab['cache_hit_e2e']}")
    cfg.LATENCY_SUMMARY.write_text(json.dumps(tab, indent=2))
    print(f"saved {cfg.LATENCY_SUMMARY.relative_to(cfg.ROOT)}")
    return tab


def main() -> None:
    """CLI."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--n", type=int, default=TARGET)
    args = ap.parse_args()
    print(cfg.banner("Part 4.3 stage-latency experiment"))
    state = json.loads(TRACES.read_text()) if args.report else run(args.n)
    report(state)


if __name__ == "__main__":
    main()
