"""HW10 self-check: required files exist and contain what the report claims.

    python scripts/verify_hw10.py        # writes reports/hw10/verification.json
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hw10"))
import hw10cfg as cfg  # noqa: E402
from trace_analysis import load_jsonl  # noqa: E402

checks: list[dict] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    """Record one check."""
    checks.append({"check": name, "ok": bool(cond), "detail": detail})
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def git(*a: str) -> str:
    """git output in the repo."""
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main() -> None:
    """Run every check and save verification.json."""
    for f in ("hw10/dashboard.py", "hw10/evaluator.py", "hw10/judge.py", "hw10/ingress.py",
              "hw10/validate_judge.py", "hw10/latency_experiment.py", "kafka_hw8/tracing.py",
              "tests/test_hw10.py"):
        check(f"file {f}", (ROOT / f).exists())
    dash = (ROOT / "hw10/dashboard.py").read_text()
    check("dashboard uses st.cache_data and st.cache_resource",
          "@st.cache_data" in dash and "@st.cache_resource" in dash)
    cases = json.loads(cfg.EVAL_CASES.read_text())["cases"] if cfg.EVAL_CASES.exists() else []
    labels = list(csv.DictReader(open(cfg.HUMAN_LABELS))) if cfg.HUMAN_LABELS.exists() else []
    check("eval_cases.json has 20 drafts", len(cases) == 20, str(len(cases)))
    check("human_labels.csv has 20 labels in 1-5", len(labels) == 20 and all(
        r["human_label"] in "12345" for r in labels))
    first = git("log", "--diff-filter=A", "--format=%cI", "--", "hw10/human_labels.csv")
    judged = git("log", "--diff-filter=A", "--format=%cI", "--",
                 "reports/hw10/raw/part3_judge_summary.json")
    check("labels committed before judge results", bool(first) and (not judged or first < judged),
          f"labels {first} / judge {judged}")
    spans = load_jsonl(cfg.SPANS)
    need = {"trace_id", "stage", "start", "end", "status", "error"}
    check("spans have the required fields", bool(spans) and all(need <= set(s) for s in spans),
          f"{len(spans)} spans")
    ex = json.loads(cfg.TRACE_EXAMPLES.read_text()) if cfg.TRACE_EXAMPLES.exists() else {}
    ids = {s["trace_id"] for s in spans}
    for k in ("cache_hit", "cache_miss", "failed"):
        check(f"trace example {k} present in spans", ex.get(k) in ids, str(ex.get(k)))
    ev = load_jsonl(cfg.EVAL_RESULTS)
    check("at least one ok end-to-end evaluation", any(e["status"] == "ok" for e in ev))
    js = json.loads(cfg.JUDGE_SUMMARY.read_text()) if cfg.JUDGE_SUMMARY.exists() else {}
    check("judge summary has Spearman, MAD, repeatability",
          bool(js) and "spearman" in js["headline"] and "repeatability" in js)
    lat = json.loads(cfg.LATENCY_SUMMARY.read_text()) if cfg.LATENCY_SUMMARY.exists() else {}
    check("50 confirmed cache misses", lat.get("n_traces") == 50
          and lat.get("all_cache_lookup_results_miss") is True, str(lat.get("n_traces")))
    out = {"passed": sum(c["ok"] for c in checks), "total": len(checks), "checks": checks}
    (cfg.REPORT / "verification.json").write_text(json.dumps(out, indent=2))
    print(f"\n{out['passed']}/{out['total']} checks passed -> reports/hw10/verification.json")


if __name__ == "__main__":
    main()
