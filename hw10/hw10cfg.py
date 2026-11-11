"""HW10 shared settings: Section 0 values, file paths, judge settings, import paths.

Every HW10 script imports this first; it puts the repo root and hw9/ on sys.path so the HW8
Kafka code (kafka_hw8/) and the HW9 semantic cache (hw9/semantic_cache.py) are reused as-is.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "hw9"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

STUDENT_NAME = "Pinal Pawar"
SID4 = 7875
PREFIX = f"s{SID4}"  # s7875
PORT_BASE = 8000 + (SID4 % 900)  # 8675 (HW8 API); the dashboard uses PORT_BASE + 1
DASHBOARD_PORT = PORT_BASE + 1  # 8676
SEED = SID4  # 7875
VERIFY_SEED = 260000 + SID4  # 267875

HW10 = ROOT / "hw10"
REPORT = ROOT / "reports" / "hw10"
RAW = Path(os.getenv("HW10_RAW", REPORT / "raw"))  # tests point this at a temp folder
SPANS = Path(os.getenv("HW10_SPANS", RAW / "spans.jsonl"))  # same file as kafka_hw8/tracing.py
REQUESTS = RAW / "requests.jsonl"  # one line per request through the ingress
EVAL_RESULTS = RAW / "eval_results.jsonl"  # Part 2, one line per evaluated trace
TRACE_EXAMPLES = RAW / "trace_examples.json"  # Part 4.2 hit / miss / failed trace ids
JUDGE_RUNS = RAW / "part3_judge_runs.csv"  # Part 3 raw per-case data
JUDGE_SUMMARY = RAW / "part3_judge_summary.json"
LATENCY_SUMMARY = RAW / "part4_latency_summary.json"
EVAL_CASES = HW10 / "eval_cases.json"  # Part 3.1, frozen (commit before judging)
HUMAN_LABELS = HW10 / "human_labels.csv"  # Part 3.1, hand-assigned by Pinal
INTERPRETATION = REPORT / "interpretation.md"  # Part 1.2 text shown on the dashboard

# Judge (GEval / DeepEval with a LOCAL Ollama model; no paid API, see AGENT.md).
JUDGE_MODEL = os.getenv("HW10_JUDGE_MODEL", "qwen3:8b")
JUDGE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
JUDGE_TEMPERATURE = 0.0
JUDGE_SEED = SEED
JUDGE_TIMEOUT_S = float(os.getenv("HW10_JUDGE_TIMEOUT_S", "180"))  # per metric, hard bound
JUDGE_MAX_TOKENS = 400

CACHE_THRESHOLD = 0.80  # the HW9 shipped setting (with the same-notice filter)
CACHE_NAMESPACE = os.getenv("HW10_CACHE_NS", "hw10cache")  # s7875:hw10cache:*


def banner(part: str) -> str:
    """First line of every HW10 script, so the name shows in each screenshot."""
    return f"===== {STUDENT_NAME} | SID4 {SID4} | PREFIX {PREFIX} | HW10 {part} ====="
