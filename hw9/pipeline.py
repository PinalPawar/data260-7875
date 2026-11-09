"""HW9: the HW8 agent path the semantic cache calls on a MISS.

Two ways to reach the same Planner -> Writer -> Reviewer pipeline (same prompts, same
qwen3:1.7b model through the src/model_client.py adapter):

  HW9_PIPELINE=kafka  (default) - the real HW8 path: question -> s7875_inbox, wait for the
                                   approved answer on s7875_final. Needs Kafka + planner.py,
                                   writer.py, reviewer.py running (as in HW8 Part 2).
  HW9_PIPELINE=direct           - the same three agent prompts called in-process, no Kafka.
                                   Used for the long Part 3 sweep so it does not depend on
                                   three extra terminals; the model calls are identical.
"""

import asyncio
import os
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MODE = os.getenv("HW9_PIPELINE", "kafka")


def run_pipeline(question: str, timeout_s: float = 600) -> dict:
    """Return {"answer", "status", "review", "pipeline", "pipeline_ms"}."""
    t0 = time.perf_counter()
    out = _run_kafka(question, timeout_s) if MODE == "kafka" else _run_direct(question)
    out["pipeline"] = MODE
    out["pipeline_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def _run_kafka(question: str, timeout_s: float) -> dict:
    from kafka_hw8.config import BOOTSTRAP, FINAL_TOPIC, INBOX_TOPIC
    from kafka_hw8.kafka_util import end_offsets, read_from, send_json
    from kafka_hw8.logutil import now

    async def go():
        corr = str(uuid.uuid4())
        start = await end_offsets(BOOTSTRAP, FINAL_TOPIC)
        msg = {"correlation_id": corr, "stage": "question", "question": question,
               "asked_at": now(), "trace": [], "source": "hw9_semantic_cache"}
        await send_json(BOOTSTRAP, INBOX_TOPIC, [(corr, msg)])

        def mine(items):
            return [i for i in items if i["value"].get("correlation_id") == corr]

        got = mine(await read_from(BOOTSTRAP, FINAL_TOPIC, start, timeout_s,
                                   until=lambda items: bool(mine(items))))
        if not got:
            raise TimeoutError("no answer on s7875_final - are planner/writer/reviewer running?")
        v = got[0]["value"]
        return {"answer": v.get("answer", ""), "status": v.get("status"),
                "review": v.get("review"), "correlation_id": corr}

    return asyncio.run(go())


def _run_direct(question: str) -> dict:
    from kafka_hw8.agents import (PLANNER_SYSTEM, REVIEWER_SYSTEM, WRITER_SYSTEM, parse_plan,
                                  parse_review, unsafe_phrase)
    from kafka_hw8.llm import chat

    plan = parse_plan(chat(PLANNER_SYSTEM, question)) or ["Answer the question"]
    draft = chat(WRITER_SYSTEM, f"Question: {question}\n\nPlan:\n"
                 + "\n".join(f"- {p}" for p in plan) + "\n\nWrite the answer now.").strip()
    bad = unsafe_phrase(draft)
    if bad:
        status, reason = "rejected", f"rule check: unsafe phrase \"{bad}\""
    else:
        status, reason = parse_review(chat(
            REVIEWER_SYSTEM, f"Question: {question}\n\nPlan:\n"
            + "\n".join(f"- {p}" for p in plan) + f"\n\nDraft answer:\n{draft}"))
    return {"answer": draft, "status": status, "review": reason}
