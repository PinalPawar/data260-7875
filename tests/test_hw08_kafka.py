"""
HW8: offline tests for the Kafka worker logic and the agent loop's failure handling.

    python tests/test_hw08_kafka.py

Plain asserts, no framework. No Kafka broker and no Ollama are needed: the agent loop runs
against an in-memory stand-in for the consumer and producer, and the agents use the offline
model stand-in. Same result every run.
"""

import asyncio
import json
import os
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ["HW8_FAKE_LLM"] = "1"
os.environ["HW8_STATE_DIR"] = tempfile.mkdtemp(prefix="hw08_test_")

from kafka_hw8.agent_base import Settings  # noqa: E402
from kafka_hw8.agents import (  # noqa: E402
    Planner,
    Reviewer,
    Writer,
    parse_plan,
    parse_review,
    unsafe_phrase,
)
from kafka_hw8.config import DEAD_LETTER_TOPIC, DRAFTS_TOPIC, FINAL_TOPIC, TASKS_TOPIC  # noqa
from kafka_hw8.notice_service import NoticeService, validate_notice  # noqa: E402
from kafka_hw8.worker import pick_reply_topic  # noqa: E402

GOOD = {
    "product": "Organic Baby Spinach 5oz", "notice_code": "RCL-2026-07875",
    "units_affected": 4471, "manufacturer_id": 1, "email": "recalls@greenfields-foods.com",
    "description": "Listeria found in lot L4471.", "category": "bacterialContamination",
}
passed = 0


def ok(cond, name):
    global passed
    assert cond, name
    passed += 1


def req(op, data, corr="c-1"):
    return {"correlation_id": corr, "reply_to": "s7875_notice_responses", "operation": op,
            "data": data}


# ------------------------------------------------------------------ Part 1 worker logic ---
def test_notice_service():
    s = NoticeService()
    r, dup = s.handle(req("CREATE_NOTICE", GOOD, "c-create"))
    ok(r["success"] and r["message"] == "Notice created" and not dup, "create succeeds")
    ok(r["correlation_id"] == "c-create", "create echoes correlation_id")
    nid = r["notice_id"]
    g, _ = s.handle(req("GET_NOTICE", {"notice_id": nid}, "c-get"))
    ok(g["success"] and g["notice"] == {"notice_id": nid, **GOOD}, "get returns the notice")
    ok(g["correlation_id"] == "c-get", "get echoes correlation_id")

    again, dup = s.handle(req("CREATE_NOTICE", GOOD, "c-create"))
    ok(dup and again["notice_id"] == nid and len(s.notices) == 1, "replayed create is a no-op")
    off = NoticeService(idempotent=False)
    off.handle(req("CREATE_NOTICE", GOOD, "x"))
    off.handle(req("CREATE_NOTICE", GOOD, "x"))
    ok(len(off.notices) == 2, "without idempotency a replay creates a second notice")

    for op, data, frag in [
        ("NOPE", {}, "Unknown operation"),
        ("GET_NOTICE", {"notice_id": "missing"}, "Notice not found"),
        ("GET_NOTICE", {}, "notice_id is required"),
        ("CREATE_NOTICE", {k: v for k, v in GOOD.items() if k != "email"}, "Missing"),
        ("CREATE_NOTICE", {**GOOD, "product": "   "}, "Empty"),
        ("CREATE_NOTICE", {**GOOD, "notice_code": "RCL-1"}, "notice_code"),
        ("CREATE_NOTICE", {**GOOD, "units_affected": -1}, "units_affected"),
        ("CREATE_NOTICE", {**GOOD, "units_affected": "5"}, "units_affected"),
        ("CREATE_NOTICE", {**GOOD, "manufacturer_id": 0}, "manufacturer_id"),
        ("CREATE_NOTICE", {**GOOD, "category": "aliens"}, "category"),
        ("CREATE_NOTICE", {**GOOD, "email": "nope"}, "email"),
        ("CREATE_NOTICE", {**GOOD, "colour": "red"}, "Unknown field"),
        ("CREATE_NOTICE", "not a dict", "JSON object"),
    ]:
        r, _ = s.handle(req(op, data, "c-err"))
        ok(r["success"] is False and frag in r["error"] and r["correlation_id"] == "c-err",
           f"clean error for {op} {frag}")
    r, _ = s.handle({"correlation_id": "c-bad", "operation": "GET_NOTICE"})
    ok(not r["success"] and "Malformed" in r["error"] and r["correlation_id"] == "c-bad",
       "malformed envelope rejected, id kept")
    ok(validate_notice(GOOD)[1] is None, "valid notice passes")
    ok(pick_reply_topic({"reply_to": "someone_else"}) == "s7875_notice_responses",
       "reply_to outside PREFIX is not trusted")
    ok(pick_reply_topic({"reply_to": "s7875_notice_responses"}) == "s7875_notice_responses",
       "reply_to inside PREFIX is used")


# ------------------------------------------------------------------ agent parsing ----------
def test_parsing():
    ok(parse_plan("1. Find the lot\n- Say symptoms\n\nStep 3: Return it") ==
       ["Find the lot", "Say symptoms", "Return it"], "plan lines cleaned")
    ok(len(parse_plan("\n".join(f"s{i}" for i in range(9)))) == 4, "plan capped at 4 steps")
    ok(parse_review("APPROVE: fine") == ("approved", "fine"), "approve parsed")
    ok(parse_review("**REJECT**: unsafe")[0] == "rejected", "reject parsed")
    ok(parse_review("looks good to me")[0] == "needs_human_review", "unclear review flagged")
    # the draft qwen3:1.7b wrote in the first real run, and safe/unsafe look-alikes
    for text, unsafe in [
        ("If the spinach you ate is from the same batch and within the expiration window, "
         "it may still be safe.", True),
        ("It's safe to eat if cooked.", True),
        ("Some batches are safe to consume.", True),
        ("It is not safe to eat recalled spinach.", False),
        ("Recalled food is never safe, even before its date.", False),
        ("Throw it away; it is safe to say the store will refund you.", False),
        ("Do not eat it. Watch for fever and call a doctor.", False),
    ]:
        ok(bool(unsafe_phrase(text)) == unsafe, f"unsafe-phrase check: {text[:40]}")


# ------------------------------------------------------------------ agent loop -------------
class FakeConsumer:
    def __init__(self):
        self.commits = []

    async def commit(self, offsets):
        self.commits.append({tp.partition: off for tp, off in offsets.items()})


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, value, key=None):
        self.sent.append((topic, json.loads(value)))


def record(value, topic=TASKS_TOPIC, partition=0, offset=0):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return SimpleNamespace(topic=topic, partition=partition, offset=offset, value=raw,
                           key=b"k")


def make(agent_cls, group, **settings):
    os.environ["HW8_GROUP"] = group
    a = agent_cls(Settings(**{"retry_backoff_s": 0, **settings}))
    a.consumer, a.producer = FakeConsumer(), FakeProducer()
    return a


TASK = {"correlation_id": "t-1", "stage": "plan", "question": "What now?",
        "plan": ["step one", "step two"], "trace": []}


async def test_agent_loop():
    # idempotency
    w = make(Writer, "g-dup", idempotency=True)
    await w.process_record(record(TASK, offset=0))
    await w.process_record(record(TASK, offset=1))
    ok([t for t, _ in w.producer.sent] == [DRAFTS_TOPIC], "duplicate task -> one draft")
    ok(w.consumer.commits == [{0: 1}, {0: 2}], "both copies committed after handling")
    w = make(Writer, "g-nodup", idempotency=False)
    await w.process_record(record(TASK, offset=0))
    await w.process_record(record(TASK, offset=1))
    ok(len(w.producer.sent) == 2, "without idempotency -> two drafts")
    w2 = make(Writer, "g-dup", idempotency=True)  # a restarted writer, same group
    await w2.process_record(record(TASK, offset=2))
    ok(w2.producer.sent == [], "idempotency survives a restart (SQLite store)")

    # commit modes
    w = make(Writer, "g-before", commit_mode="before", idempotency=False, max_retries=0)
    w.handle = _boom
    try:
        await w.process_record(record(TASK))
    except RuntimeError:
        pass
    ok(w.consumer.commits == [{0: 1}], "commit-before: offset already committed when it dies")
    w = make(Writer, "g-after", commit_mode="after", idempotency=False, max_retries=0)
    w.handle = _boom
    try:
        await w.process_record(record(TASK))
        crashed = False
    except RuntimeError:
        crashed = True
    ok(crashed and w.consumer.commits == [], "commit-after: crash leaves the offset uncommitted")

    # poison -> retries -> dead letter, then the next message flows
    w = make(Writer, "g-poison", max_retries=3)
    bad = {**TASK, "correlation_id": "bad", "plan": None}
    await w.process_record(record(bad, offset=5))
    await w.process_record(record(TASK, offset=6))
    topics = [t for t, _ in w.producer.sent]
    ok(topics == [DEAD_LETTER_TOPIC, DRAFTS_TOPIC], "poison dead-lettered, next one processed")
    dead = w.producer.sent[0][1]
    ok(dead["attempts"] == 3 and dead["source"]["offset"] == 5 and dead["original"] == bad,
       "dead-letter record carries attempts, source offset and the original message")
    ok(w.consumer.commits == [{0: 6}, {0: 7}], "poison offset committed after dead-lettering")
    w = make(Writer, "g-json", max_retries=2)
    await w.process_record(record(b"{not json", offset=0))
    ok(w.producer.sent[0][0] == DEAD_LETTER_TOPIC and w.producer.sent[0][1]["attempts"] == 2,
       "non-JSON message dead-lettered after 2 attempts")

    # full pipeline with the offline model: correlation_id and trace carried through
    p = make(Planner, "g-pipe-p")
    await p.process_record(record({"correlation_id": "q-1", "question": "Recall?",
                                   "trace": []}, topic="s7875_inbox"))
    t_topic, plan = p.producer.sent[0]
    w = make(Writer, "g-pipe-w")
    await w.process_record(record(plan, partition=1, offset=3))
    d_topic, draft = w.producer.sent[0]
    r = make(Reviewer, "g-pipe-r")
    await r.process_record(record(draft, topic=DRAFTS_TOPIC))
    f_topic, final = r.producer.sent[0]
    ok((t_topic, d_topic, f_topic) == (TASKS_TOPIC, DRAFTS_TOPIC, FINAL_TOPIC), "topic chain")
    ok(final["correlation_id"] == "q-1" and final["status"] == "approved" and final["answer"],
       "final has status + answer and the same correlation_id")
    ok([s["agent"] for s in final["trace"]] == ["planner", "writer", "reviewer"]
       and final["trace"][1]["partition"] == 1, "trace records each stage")

    # reviewer rule check: an over-long draft is rejected without a model call
    r = make(Reviewer, "g-long")
    await r.process_record(record({**draft, "draft": "word " * 250}, topic=DRAFTS_TOPIC))
    ok(r.producer.sent[0][1]["status"] == "rejected", "over-long draft rejected")
    r = make(Reviewer, "g-unsafe")
    await r.process_record(record({**draft, "correlation_id": "u-1",
                                   "draft": "Within the expiry date it may still be safe."},
                                  topic=DRAFTS_TOPIC))
    final = r.producer.sent[0][1]
    ok(final["status"] == "rejected" and "rule check" in final["review"],
       "draft calling recalled food safe is rejected by the rule check")


async def _boom(msg, rec):
    raise RuntimeError("model died")


# ------------------------------------------------------------------ ordering helpers ------
def test_ordering_helpers():
    import run_hw08_part3 as p3
    m1, e1 = p3.ordering_messages("x")
    m2, e2 = p3.ordering_messages("y")
    ok(len(m1) == 20 and e1 == e2 and [m["entity"] for m in m1] == [m["entity"] for m in m2],
       "VERIFY_SEED gives the same 20 messages every run")
    for e in e1:
        ok([m["seq"] for m in m1 if m["entity"] == e] == list(range(1, sum(
            m["entity"] == e for m in m1) + 1)), f"seq numbers 1..n for {e}")
    from aiokafka.partitioner import DefaultPartitioner
    parts = {DefaultPartitioner()(e.encode(), [0, 1], [0, 1]) for e in e1}
    ok(parts == {0, 1}, "keyed run uses both partitions")
    rows = [{"entity": "A", "seq": 2, "partition": 1, "writer": "w2", "processed_at": "1"},
            {"entity": "A", "seq": 1, "partition": 0, "writer": "w1", "processed_at": "2"},
            {"entity": "B", "seq": 1, "partition": 0, "writer": "w1", "processed_at": "3"}]
    a = p3.analyse(rows, ["A", "B"])
    ok(a["entities_out_of_order"] == 1 and a["entities"]["A"]["inversions"] == 1,
       "analyse spots an out-of-order entity")


if __name__ == "__main__":
    import builtins  # quiet: the agent loop logs every step

    real_print = builtins.print
    builtins.print = lambda *a, **k: None
    try:
        test_notice_service()
        test_parsing()
        asyncio.run(test_agent_loop())
        test_ordering_helpers()
    finally:
        builtins.print = real_print
    print(f"tests/test_hw08_kafka.py: all {passed} checks passed")
