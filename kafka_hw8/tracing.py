"""HW10 Part 4: structured JSON spans, one line per stage, keyed by trace_id.

trace_id IS the HW8 correlation_id. No second request identifier is created anywhere: the
ingress makes one uuid, uses it as the cache-lookup trace_id, and sends the same value as
correlation_id into s7875_inbox. Every agent reads it back from the message.

Every process (ingress, planner.py, writer.py, reviewer.py, evaluator) appends to the same
JSONL file on the Mac, so one file holds the whole journey:

    {"trace_id": "...", "stage": "planner", "start": "2026-11-10T19:01:02.123-08:00",
     "end": "...", "start_ms": 1762..., "end_ms": 1762..., "duration_ms": 4123.4,
     "status": "ok" | "error", "error": null | "ValueError: ...", "process": "planner-4242",
     "attrs": {...}}

Stages: request (root, end to end), cache_lookup, queue_inbox, planner, queue_tasks, writer,
queue_drafts, reviewer, queue_final, evaluation, dead_letter. File: HW10_SPANS env var, default
reports/hw10/raw/spans.jsonl. HW10_TRACING=0 switches span writing off (HW8 tests).
"""

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
_RAW = Path(os.getenv("HW10_RAW", ROOT / "reports" / "hw10" / "raw"))
SPANS_PATH = Path(os.getenv("HW10_SPANS", _RAW / "spans.jsonl"))
ENABLED = os.getenv("HW10_TRACING", "1") != "0"
_LOCK = threading.Lock()


def now_ms() -> float:
    """Wall-clock time in epoch milliseconds (all processes run on the same Mac)."""
    return time.time() * 1000.0


def iso(ms: float) -> str:
    """Epoch milliseconds as a local ISO-8601 timestamp with UTC offset."""
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="milliseconds")


def write_span(trace_id: str | None, stage: str, start_ms: float, end_ms: float,
               status: str = "ok", error: str | None = None, process: str = "",
               **attrs: object) -> dict:
    """Append one span line to the shared JSONL file and return it."""
    span = {"trace_id": trace_id, "stage": stage, "start": iso(start_ms), "end": iso(end_ms),
            "start_ms": round(start_ms, 3), "end_ms": round(end_ms, 3),
            "duration_ms": round(end_ms - start_ms, 3), "status": status, "error": error,
            "process": process or f"pid-{os.getpid()}", "attrs": attrs}
    if ENABLED and trace_id:
        SPANS_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(span, ensure_ascii=False, default=str)
        with _LOCK, open(SPANS_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return span


class SpanHandle:
    """Mutable holder used inside `with span(...)` so the body can add attributes."""

    def __init__(self) -> None:
        self.attrs: dict = {}
        self.status = "ok"
        self.error: str | None = None

    def set(self, **attrs: object) -> None:
        """Add attributes to the span."""
        self.attrs.update(attrs)

    def fail(self, error: str) -> None:
        """Mark the span failed without raising."""
        self.status, self.error = "error", error


@contextmanager
def span(trace_id: str | None, stage: str, process: str = "", **attrs: object
         ) -> Iterator[SpanHandle]:
    """Time the body; an exception marks the span 'error' (and is re-raised)."""
    handle = SpanHandle()
    handle.attrs.update(attrs)
    start = now_ms()
    try:
        yield handle
    except Exception as exc:
        handle.fail(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write_span(trace_id, stage, start, now_ms(), handle.status, handle.error, process,
                   **handle.attrs)


def load_spans(path: Path | str | None = None) -> list[dict]:
    """Every span in the file (bad lines are skipped)."""
    p = Path(path or SPANS_PATH)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
