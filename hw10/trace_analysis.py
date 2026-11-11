"""HW10 Part 4: turn spans.jsonl into per-trace journeys and stage-latency statistics.

Used by latency_experiment.py (Part 4.3 table) and dashboard.py (Summary + Trace pages).
"""

import json
from collections import defaultdict
from pathlib import Path

import hw10cfg as cfg

STAGE_ORDER = ["request", "cache_lookup", "queue_inbox", "planner", "queue_tasks", "writer",
               "queue_drafts", "reviewer", "queue_final", "dead_letter", "evaluation"]
TABLE_STAGES = [("Cache lookup", ["cache_lookup"]), ("Planner", ["planner"]),
                ("Writer", ["writer"]), ("Reviewer", ["reviewer"]),
                ("Queue wait (total)", ["queue_inbox", "queue_tasks", "queue_drafts",
                                        "queue_final"]),
                ("Evaluation", ["evaluation"])]


def load_jsonl(path: Path) -> list[dict]:
    """All JSON lines of a file (missing file = empty list, bad lines skipped)."""
    if not Path(path).exists():
        return []
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def by_trace(spans: list[dict]) -> dict[str, list[dict]]:
    """trace_id -> its spans in stage order, then start time."""
    out = defaultdict(list)
    for s in spans:
        out[s["trace_id"]].append(s)
    rank = {s: i for i, s in enumerate(STAGE_ORDER)}
    for t in out:
        out[t].sort(key=lambda s: (s["start_ms"], rank.get(s["stage"], 99)))
    return dict(out)


def journey(spans: list[dict], trace_id: str) -> list[dict]:
    """Spans of one trace in the order they happened (root 'request' span first)."""
    js = [s for s in spans if s["trace_id"] == trace_id]
    rank = {s: i for i, s in enumerate(STAGE_ORDER)}
    return sorted(js, key=lambda s: (s["stage"] != "request", s["start_ms"],
                                     rank.get(s["stage"], 99)))


def percentile(xs: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (same as numpy's default)."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def stage_durations(trace_spans: list[dict]) -> dict[str, float]:
    """stage -> total ms in that stage for one trace (retried attempts are summed)."""
    d = defaultdict(float)
    for s in trace_spans:
        d[s["stage"]] += s["duration_ms"]
    return dict(d)


def latency_table(spans: list[dict], trace_ids: list[str]) -> dict:
    """Part 4.3 rows: p50 / p95 per stage + share of total cache-miss end-to-end time."""
    groups = by_trace([s for s in spans if s["trace_id"] in set(trace_ids)])
    per = [stage_durations(groups[t]) for t in trace_ids if t in groups]
    e2e = [p.get("request", 0.0) for p in per]
    total = sum(e2e) or 1.0
    rows = []
    for label, stages in TABLE_STAGES:
        vals = [sum(p.get(s, 0.0) for s in stages) for p in per]
        rows.append({"stage": label, "p50_ms": percentile(vals, 50), "p95_ms": percentile(vals, 95),
                     "pct_of_e2e": round(100 * sum(vals) / total, 2)})
    covered = sum(r["pct_of_e2e"] for r in rows)
    return {"n_traces": len(per), "rows": rows,
            "end_to_end": {"p50_ms": percentile(e2e, 50), "p95_ms": percentile(e2e, 95),
                           "mean_ms": round(total / max(len(per), 1), 1)},
            "unattributed_pct": round(100 - covered, 2),
            "dominant": max(rows, key=lambda r: r["pct_of_e2e"])["stage"] if rows else None}


def load_all() -> tuple[list[dict], list[dict], list[dict]]:
    """(spans, request rows, evaluation rows) from reports/hw10/raw/."""
    return load_jsonl(cfg.SPANS), load_jsonl(cfg.REQUESTS), load_jsonl(cfg.EVAL_RESULTS)
