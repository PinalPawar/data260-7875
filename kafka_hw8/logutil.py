"""One log-line format for every HW8 process.

    2026-10-26T21:40:01.123-07:00 [WORKER] RECEIVE  corr=4f1c... topic=s7875_notice_requests ...

The timestamp comes first and carries its UTC offset (containers run on UTC, the Mac on Pacific
time), so lines from different processes can be merged and sorted into one sequence
(homework_demo.py does that for Part 1 step 9).
"""

import json
import sys
from datetime import datetime

# When set to a list, every line this process logs is also appended to it (homework_demo.py
# uses this to merge its own lines with the worker's and API's).
CAPTURE: list | None = None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def parse_ts(line: str):
    """The timestamp at the start of a log line, or None."""
    try:
        return datetime.fromisoformat(line.split(" ", 1)[0])
    except ValueError:
        return None


def log(tag: str, event: str, corr: str | None = None, payload=None, **fields) -> None:
    parts = [now(), f"[{tag}]", f"{event:<15}"]
    if corr:
        parts.append(f"corr={corr}")
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    if payload is not None:
        parts.append(json.dumps(payload, ensure_ascii=False, default=str))
    _emit(" ".join(parts))


def _emit(line: str) -> None:
    print(line, flush=True)
    if CAPTURE is not None:
        CAPTURE.append(line)


def say(tag: str, text: str) -> None:
    _emit(f"{now()} [{tag}] {text}")


def fail(tag: str, text: str) -> None:
    print(f"{now()} [{tag}] ERROR {text}", file=sys.stdout, flush=True)
