"""HW10 Part 4: traced ingress = HW9 semantic cache -> HW8 Kafka agents -> HW10 evaluator.

One uuid per request. It is the trace_id of the cache_lookup span AND the correlation_id sent
into s7875_inbox, so the cache, the four topics and the evaluator all share one id.

    cache_lookup --hit--> response (request span ends; no agents, no evaluation)
                 --miss-> s7875_inbox -> Planner -> s7875_tasks -> Writer -> s7875_drafts
                          -> Reviewer -> s7875_final -> (evaluation) -> response
                          (any agent that fails 3 times -> s7875_dead_letter)

Spans written here: request (root, end to end), cache_lookup, queue_final, evaluation (via
evaluator.py). The agents write queue_inbox/planner/queue_tasks/writer/queue_drafts/reviewer.

    python hw10/ingress.py --ask "question"              # one request
    python hw10/ingress.py --ask "question" --evaluate   # + Part 2 evaluation
    python hw10/ingress.py --examples                    # Part 4.2: hit, miss, failed traces
"""

import argparse
import asyncio
import json
import logging
import time
import uuid

import hw10cfg as cfg
from kafka_hw8.config import BOOTSTRAP, DEAD_LETTER_TOPIC, DRAFTS_TOPIC, FINAL_TOPIC, \
    INBOX_TOPIC, TASKS_TOPIC
from kafka_hw8.tracing import now_ms, span, write_span

_CACHE = None


def get_cache():
    """The HW9 SemanticCache (threshold 0.80 + same-notice filter), own HW10 namespace."""
    global _CACHE
    if _CACHE is None:
        from semantic_cache import SemanticCache, quiet_libs
        quiet_libs()
        _CACHE = SemanticCache(threshold=cfg.CACHE_THRESHOLD, notice_filter=True,
                               namespace=cfg.CACHE_NAMESPACE)
    return _CACHE


def cache_lookup(trace_id: str, question: str) -> dict:
    """Embed + KNN inside a cache_lookup span. Returns hit/miss and what is needed later."""
    from notice_context import find_notice
    from semantic_cache import embed
    cache = get_cache()
    with span(trace_id, "cache_lookup", "ingress") as sp:
        vec = embed(question)
        notice = find_notice(question)
        entry, sim = cache.nearest(vec, notice["id"] if notice else "none")
        hit = entry is not None and sim >= cache.threshold
        sp.set(result="hit" if hit else "miss", similarity=round(float(sim), 4),
               threshold=cache.threshold, matched_query=entry and entry.get("query"),
               notice_id=notice and notice["id"], namespace=cfg.CACHE_NAMESPACE)
    return {"hit": hit, "entry": entry, "similarity": float(sim), "vec": vec, "notice": notice}


async def _wait_for(corr: str, starts: dict, timeout_s: float) -> tuple[str, dict] | None:
    """Wait for this correlation_id on s7875_final OR s7875_dead_letter (whichever first)."""
    from aiokafka import AIOKafkaConsumer, TopicPartition
    c = AIOKafkaConsumer(bootstrap_servers=BOOTSTRAP, enable_auto_commit=False)
    await c.start()
    try:
        tps = [TopicPartition(t, p) for t in (FINAL_TOPIC, DEAD_LETTER_TOPIC) for p in starts[t]]
        c.assign(tps)
        for tp in tps:
            c.seek(tp, starts[tp.topic][tp.partition])
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for tp, recs in (await c.getmany(timeout_ms=200)).items():
                for r in recs:
                    v = _json(r.value)
                    if isinstance(v, dict) and v.get("correlation_id") == corr:
                        return tp.topic, v
        return None
    finally:
        await c.stop()


def _json(raw: bytes):
    """Decode a Kafka value; None if it is not JSON."""
    try:
        return json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


async def run_agents(trace_id: str, agent_q: str, inject_fault: str | None,
                     timeout_s: float) -> tuple[dict, dict]:
    """Send to s7875_inbox with correlation_id == trace_id; return (outcome, topic starts)."""
    from kafka_hw8.kafka_util import end_offsets, send_json
    from kafka_hw8.logutil import now
    topics = (INBOX_TOPIC, TASKS_TOPIC, DRAFTS_TOPIC, FINAL_TOPIC, DEAD_LETTER_TOPIC)
    starts = {t: await end_offsets(BOOTSTRAP, t) for t in topics}
    msg = {"correlation_id": trace_id, "trace_id": trace_id, "stage": "question",
           "question": agent_q, "asked_at": now(), "trace": [], "source": "hw10_ingress",
           "sent_at_ms": now_ms()}
    if inject_fault:
        msg["inject_fault"] = inject_fault
    await send_json(BOOTSTRAP, INBOX_TOPIC, [(trace_id, msg)])
    got = await _wait_for(trace_id, starts, timeout_s)
    if got is None:
        return {"status": "error", "failed_stage": "timeout",
                "error": f"no final/dead-letter within {timeout_s:.0f}s"}, starts
    topic, v = got
    if isinstance(v.get("sent_at_ms"), (int, float)):
        write_span(trace_id, "queue_final", float(v["sent_at_ms"]), now_ms(), "ok", None,
                   "ingress", topic=topic)
    if topic == DEAD_LETTER_TOPIC:
        return {"status": "error", "failed_stage": v.get("failed_agent"),
                "error": v.get("error"), "dead_letter": v}, starts
    return {"status": "ok", "final": v}, starts


def _log_request(row: dict) -> None:
    """Append one request row (the dashboard's Summary page reads this file)."""
    cfg.RAW.mkdir(parents=True, exist_ok=True)
    with open(cfg.REQUESTS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def ask(question: str, *, store: bool = True, evaluate: bool = False,
        inject_fault: str | None = None, kind: str = "demo", timeout_s: float = 900) -> dict:
    """One request end to end. Returns the request row (also appended to requests.jsonl)."""
    from notice_context import context_line, data_version
    trace_id, t0 = str(uuid.uuid4()), now_ms()
    look = cache_lookup(trace_id, question)
    row = {"trace_id": trace_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind,
           "question": question, "is_cached": look["hit"],
           "similarity": round(look["similarity"], 4), "status": "ok"}
    if look["hit"]:
        row.update(answer=look["entry"]["answer"], final_status=look["entry"].get("status"),
                   matched_query=look["entry"]["query"], path="cache_hit")
    else:
        notice = look["notice"]
        agent_q = question + (context_line(notice) if notice else "")
        outcome, starts = asyncio.run(run_agents(trace_id, agent_q, inject_fault, timeout_s))
        row.update(path="cache_miss", status=outcome["status"],
                   failed_stage=outcome.get("failed_stage"), error=outcome.get("error"))
        fin = outcome.get("final") or {}
        row.update(answer=fin.get("answer"), final_status=fin.get("status"),
                   review=fin.get("review"))
        if store and fin.get("status") == "approved":
            get_cache().store(question, look["vec"], fin["answer"], notice and notice["id"],
                              data_version(notice), fin["status"])
        if evaluate and outcome["status"] == "ok":
            from evaluator import evaluate_trace
            ev = evaluate_trace(trace_id, starts)
            row["evaluation_status"] = ev["status"]
    t_end = now_ms()
    write_span(trace_id, "request", t0, t_end, row["status"], row.get("error"), "ingress",
               path=row["path"], is_cached=row["is_cached"], kind=kind,
               failed_stage=row.get("failed_stage"))
    row["e2e_ms"] = round(t_end - t0, 1)
    _log_request(row)
    return row


EXAMPLE_QUESTIONS = [
    "What should I do if I bought the recalled Frozen Spinach from GreenFields Co?",
    "My child ate some of a recalled peanut butter. What symptoms should I watch for?",
    "How should I clean my fridge after storing a recalled cantaloupe?",
]
FAIL_QUESTION = "Is it okay to cook recalled ground beef well done instead of returning it?"


def show(row: dict) -> None:
    """One readable block per request (for the screenshots)."""
    print(f"  trace_id   = {row['trace_id']}")
    print(f"  path       = {row['path']}  is_cached={row['is_cached']}  "
          f"similarity={row['similarity']}  status={row['status']}  e2e_ms={row['e2e_ms']}")
    if row.get("failed_stage"):
        print(f"  FAILED at  = {row['failed_stage']}  error={row.get('error')}")
    if row.get("final_status"):
        print(f"  reviewer   = {row['final_status']}  {row.get('review') or ''}")
    if row.get("answer"):
        print(f"  answer     = {row['answer'][:200]}")


def run_examples(keep: bool) -> dict:
    """Part 4.2: one cache-miss (evaluated, = Part 2 test question), one cache-hit, one failed."""
    if not keep:
        print(f"cleared {get_cache().clear()} entries from s7875:{cfg.CACHE_NAMESPACE}")
    ex = {}
    for q in EXAMPLE_QUESTIONS:  # need an APPROVED miss so the repeat can hit
        print(f"\n--- cache-miss request (evaluated): {q}")
        miss = ask(q, evaluate=True, kind="example_miss")
        show(miss)
        if miss["final_status"] == "approved":
            ex["cache_miss"] = miss["trace_id"]
            print(f"\n--- same question again (expect cache hit): {q}")
            hit = ask(q, kind="example_hit")
            show(hit)
            if hit["is_cached"]:
                ex["cache_hit"] = hit["trace_id"]
                break
        print("  (Reviewer did not approve, so nothing was cached - trying the next question)")
    print(f"\n--- failed request (inject_fault=writer): {FAIL_QUESTION}")
    fail = ask(FAIL_QUESTION, inject_fault="writer", kind="example_failed")
    show(fail)
    ex["failed"] = fail["trace_id"]
    ex["failed_stage"], ex["failed_error"] = fail.get("failed_stage"), fail.get("error")
    cfg.TRACE_EXAMPLES.write_text(json.dumps(ex, indent=2))
    print(f"\nsaved {cfg.TRACE_EXAMPLES.relative_to(cfg.ROOT)}:\n{json.dumps(ex, indent=2)}")
    return ex


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask")
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--inject-fault", choices=["planner", "writer", "reviewer"])
    ap.add_argument("--examples", action="store_true")
    ap.add_argument("--keep", action="store_true", help="--examples: do not clear the cache")
    args = ap.parse_args()
    print(cfg.banner("Part 4 traced ingress"))
    if args.examples:
        run_examples(args.keep)
    elif args.ask:
        row = ask(args.ask, evaluate=args.evaluate, inject_fault=args.inject_fault)
        show(row)
        if args.evaluate and row.get("evaluation_status"):
            from evaluator import print_row
            print_row(json.loads(cfg.EVAL_RESULTS.read_text().splitlines()[-1]))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
