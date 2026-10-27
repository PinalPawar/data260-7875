"""
HW8 Part 2: put one question on s7875_inbox and wait for its approval on s7875_final.

    python send_question.py
    python send_question.py "Is it safe to eat cantaloupe from a recalled lot if I wash it?"

Run planner.py, writer.py and reviewer.py first (one terminal each). This script only talks to
Kafka. When the final message arrives it also reads the message with the same correlation_id
from each topic in between, prints the journey stage by stage, and saves everything to
reports/hw08/raw/part2_journey_<id>.json.
"""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from kafka_hw8.config import BOOTSTRAP, DRAFTS_TOPIC, FINAL_TOPIC, INBOX_TOPIC, TASKS_TOPIC, banner
from kafka_hw8.kafka_util import end_offsets, read_from, send_json
from kafka_hw8.logutil import log, now

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "reports" / "hw08" / "raw"
DEFAULT_Q = ("A store near me posted a Listeria recall for bagged organic baby spinach. "
             "I already ate some yesterday. What should I do now?")
STAGES = [(INBOX_TOPIC, "question"), (TASKS_TOPIC, "plan"), (DRAFTS_TOPIC, "draft"),
          (FINAL_TOPIC, "final")]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default=DEFAULT_Q)
    ap.add_argument("--timeout", type=float, default=600, help="seconds to wait for the final")
    ap.add_argument("--correlation-id", default=None)
    args = ap.parse_args()
    print(banner("send_question.py"), flush=True)

    corr = args.correlation_id or str(uuid.uuid4())
    starts = {t: await end_offsets(BOOTSTRAP, t) for t, _ in STAGES}
    message = {"correlation_id": corr, "stage": "question", "question": args.question,
               "asked_at": now(), "trace": []}
    log("SENDER", "SEND", corr, message, topic=INBOX_TOPIC)
    [(p, off)] = await send_json(BOOTSTRAP, INBOX_TOPIC, [(corr, message)])
    log("SENDER", "SENT", corr, topic=INBOX_TOPIC, p=p, off=off)
    log("SENDER", "WAITING", corr, topic=FINAL_TOPIC, timeout_s=args.timeout)

    def mine(items):
        return [i for i in items if i["value"].get("correlation_id") == corr]

    finals = mine(await read_from(BOOTSTRAP, FINAL_TOPIC, starts[FINAL_TOPIC], args.timeout,
                                      until=lambda items: bool(mine(items))))
    if not finals:
        log("SENDER", "TIMEOUT", corr, note="no final message - are all three agents running?")
        raise SystemExit(1)
    final = finals[0]
    log("SENDER", "FINAL", corr, final["value"], topic=FINAL_TOPIC, p=final["partition"],
        off=final["offset"])

    print("\n===== Message journey (same correlation_id at every stage) =====")
    journey = []
    for topic, stage in STAGES:
        hits = mine(await read_from(BOOTSTRAP, topic, starts[topic], 3,
                                    until=lambda i: bool(mine(i))))
        for h in hits[:1]:
            v = h["value"]
            summary = {"question": v.get("question")} if stage == "question" else \
                {"plan": v.get("plan")} if stage == "plan" else \
                {"draft": v.get("draft")} if stage == "draft" else \
                {"status": v.get("status"), "review": v.get("review")}
            print(f"[{stage:>8}] topic={topic} p={h['partition']} off={h['offset']} "
                  f"key={h['key']} correlation_id={v.get('correlation_id')}")
            print(f"           {json.dumps(summary, ensure_ascii=False)}")
            journey.append({"stage": stage, "topic": topic, **h})

    print("\n===== Final JSON (from s7875_final) =====")
    print(json.dumps(final["value"], indent=2, ensure_ascii=False))
    same = all(j["value"].get("correlation_id") == corr for j in journey) and len(journey) == 4
    print(f"\ncorrelation_id preserved through all 4 topics: {same}")

    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"part2_journey_{corr[:8]}.json"
    path.write_text(json.dumps({"correlation_id": corr, "journey": journey,
                                "final": final["value"], "correlation_id_preserved": same},
                               indent=2, ensure_ascii=False))
    print(f"saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
