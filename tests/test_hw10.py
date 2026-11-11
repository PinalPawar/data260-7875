"""HW10: offline tests for tracing, the instrumented agent loop, the evaluator and the stats.

    python tests/test_hw10.py

No Kafka, Redis, MySQL or Ollama: the agent loop runs on the HW8 in-memory fakes with the
offline model stand-in, and the judge is a fake DeepEval model that returns fixed scores.
"""

import asyncio
import json
import os
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hw10"))
TMP = tempfile.mkdtemp(prefix="hw10_test_")
os.environ.update(HW8_FAKE_LLM="1", HW8_STATE_DIR=TMP, HW10_RAW=TMP)

from kafka_hw8.agent_base import Settings  # noqa: E402
from kafka_hw8.agents import Planner, Reviewer, Writer  # noqa: E402
from kafka_hw8.config import DEAD_LETTER_TOPIC, DRAFTS_TOPIC, INBOX_TOPIC, TASKS_TOPIC  # noqa
from kafka_hw8.tracing import load_spans, now_ms, span  # noqa: E402

import evaluator  # noqa: E402
import judge  # noqa: E402
from trace_analysis import journey, latency_table, percentile  # noqa: E402
from validate_judge import repeatability, spearman  # noqa: E402

passed = 0


def ok(cond: bool, name: str) -> None:
    """Assert and count."""
    global passed
    assert cond, name
    passed += 1


class FakeConsumer:
    """Records commits."""

    async def commit(self, offsets) -> None:
        """No-op commit."""


class FakeProducer:
    """Collects what an agent sends."""

    def __init__(self) -> None:
        self.sent: list = []

    async def send_and_wait(self, topic, value, key=None) -> None:
        """Keep (topic, decoded value)."""
        self.sent.append((topic, json.loads(value)))


def rec(value: dict, topic: str, offset: int = 0) -> SimpleNamespace:
    """A Kafka record stand-in."""
    return SimpleNamespace(topic=topic, partition=0, offset=offset,
                           value=json.dumps(value).encode(), key=b"k")


def agent(cls, group: str):
    """Agent wired to fakes."""
    os.environ["HW8_GROUP"] = group
    a = cls(Settings(retry_backoff_s=0))
    a.consumer, a.producer = FakeConsumer(), FakeProducer()
    return a


def test_tracing() -> None:
    """span() writes ok and error spans with trace_id, times and error text."""
    with span("t-span", "cache_lookup", "test") as sp:
        sp.set(result="miss")
    try:
        with span("t-span", "planner", "test"):
            raise ValueError("boom")
    except ValueError:
        pass
    s = [x for x in load_spans() if x["trace_id"] == "t-span"]
    ok(len(s) == 2 and s[0]["attrs"]["result"] == "miss", "span written with attrs")
    ok(s[1]["status"] == "error" and "boom" in s[1]["error"], "error span has error text")
    ok(all(k in s[0] for k in ("start", "end", "duration_ms", "stage")), "span fields")


async def test_pipeline_trace() -> None:
    """One trace_id flows Planner -> Writer -> Reviewer and every stage writes its spans."""
    tid = "trace-ok-1"
    q = {"correlation_id": tid, "trace_id": tid, "question": "Recalled spinach, what now?",
         "trace": [], "sent_at_ms": now_ms()}
    p, w, r = agent(Planner, "g1"), agent(Writer, "g1"), agent(Reviewer, "g1")
    await p.process_record(rec(q, INBOX_TOPIC))
    plan = p.producer.sent[0][1]
    await w.process_record(rec(plan, TASKS_TOPIC))
    draft = w.producer.sent[0][1]
    await r.process_record(rec(draft, DRAFTS_TOPIC))
    final = r.producer.sent[0][1]
    ok(plan["trace_id"] == draft["trace_id"] == final["trace_id"] == tid, "trace_id carried")
    ok(final["correlation_id"] == tid, "trace_id == correlation_id")
    stages = [s["stage"] for s in journey(load_spans(), tid)]
    for st in ("queue_inbox", "planner", "queue_tasks", "writer", "queue_drafts", "reviewer"):
        ok(st in stages, f"span for {st}")
    ok(isinstance(final.get("sent_at_ms"), float), "final stamped with sent_at_ms")


async def test_failed_trace() -> None:
    """inject_fault=writer -> 3 failed writer spans + dead_letter span, failing stage named."""
    tid = "trace-fail-1"
    task = {"correlation_id": tid, "trace_id": tid, "question": "q", "plan": ["a"],
            "trace": [], "sent_at_ms": now_ms(), "inject_fault": "writer"}
    w = agent(Writer, "g2")
    await w.process_record(rec(task, TASKS_TOPIC))
    ok(w.producer.sent[0][0] == DEAD_LETTER_TOPIC, "dead-lettered")
    sp = [s for s in load_spans() if s["trace_id"] == tid]
    errs = [s for s in sp if s["stage"] == "writer" and s["status"] == "error"]
    ok(len(errs) == 3 and "injected fault" in errs[0]["error"], "3 failed writer attempts")
    ok(any(s["stage"] == "dead_letter" and s["attrs"]["failed_stage"] == "writer" for s in sp),
       "dead_letter span names failing stage")


class FakeJudge(judge.OllamaJudge):
    """Judge stand-in: score 4 for everything, or a fixed failure."""

    def __init__(self, score: int = 4, fail: bool = False) -> None:
        self.score, self.fail = score, fail
        super().__init__("fake-judge")

    def load_model(self):
        """No client."""
        return None

    def generate(self, prompt: str, schema=None):
        """Fixed reply."""
        if self.fail:
            raise ConnectionError("judge down")
        return schema(score=self.score, reason="fixed")


def _msgs(answer: str = "Throw it away.", draft: str = "Throw it away.") -> dict:
    """plan/draft/final messages as the evaluator reads them from Kafka."""
    v = {"correlation_id": "e-1", "question": "Recalled spinach?", "plan": ["Discard it"]}
    return {"plan": {"value": v}, "draft": {"value": {**v, "draft": draft}},
            "final": {"value": {**v, "answer": answer, "status": "approved", "review": "ok"}}}


def test_evaluator() -> None:
    """Scores saved for all four criteria; malformed input and a dead judge do not hang."""
    row = evaluator.evaluate_trace("e-1", judge=FakeJudge(4), msgs=_msgs())
    sc = row["scores"]
    ok(row["status"] == "ok" and sc["plan_quality"]["score_1_5"] == 4.0, "plan scored 1-5")
    ok(sc["improvement"]["difference"] == 0 and sc["improvement"]["final_text_identical_to_draft"],
       "identical text -> no improvement reported")
    ok("no improvement" in sc["improvement"]["interpretation"], "honest interpretation")
    bad = _msgs()
    bad["plan"]["value"] = {"plan": "not a list"}
    ok(evaluator.evaluate_trace("e-2", judge=FakeJudge(), msgs=bad)["status"] == "incomplete",
       "malformed plan -> incomplete, no judge call")
    ok(evaluator.evaluate_trace("e-3", judge=FakeJudge(fail=True), msgs=_msgs())["status"]
       == "judge_error", "unavailable judge -> judge_error")
    ok(any(s["stage"] == "evaluation" and s["trace_id"] == "e-1" for s in load_spans()),
       "evaluation span written")


def test_stats() -> None:
    """Spearman with ties, repeatability, percentiles, latency table."""
    ok(spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == 1.0, "perfect rank agreement")
    ok(spearman([1, 2, 3], [3, 2, 1]) == -1.0, "perfect disagreement")
    ok(abs(spearman([1, 2, 2, 3], [1, 3, 2, 4]) - 0.9487) < 1e-3, "ties use average ranks")
    rep = repeatability([[4, 3, 5], [4, 4, 5], [4, 3, 2]])
    ok(rep["cases_changed"] == 2 and rep["max_abs_change"] == 3, "repeatability counts")
    ok(percentile([1, 2, 3, 4], 50) == 2.5, "p50 interpolates")
    spans = [{"trace_id": "x", "stage": st, "start_ms": a, "end_ms": b, "duration_ms": b - a,
              "status": "ok", "attrs": {}} for st, a, b in
             [("request", 0, 100), ("cache_lookup", 0, 10), ("planner", 10, 40),
              ("writer", 40, 70), ("reviewer", 70, 90), ("queue_inbox", 9, 10),
              ("evaluation", 90, 100)]]
    t = latency_table(spans, ["x"])
    ok(t["dominant"] in ("Planner", "Writer") and t["end_to_end"]["p50_ms"] == 100,
       "latency table")


def main() -> None:
    """Run all."""
    test_tracing()
    asyncio.run(test_pipeline_trace())
    asyncio.run(test_failed_trace())
    test_evaluator()
    test_stats()
    print(f"tests/test_hw10.py: all {passed} checks passed")


if __name__ == "__main__":
    main()
