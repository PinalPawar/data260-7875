"""
HW8 Part 3: failure behaviour, before and after each fix, with logs saved for the report.

    python scripts/run_hw08_part3.py all            # all four tests (about 3-4 minutes)
    python scripts/run_hw08_part3.py duplicate      # or: kill, poison, ordering

Needs Kafka on localhost:9092 with the topics created (scripts/hw08_create_topics.sh).
Stop any writer.py you started yourself first; this script starts its own Writer processes
(python writer.py) with the Part 3 switches set (see kafka_hw8/agent_base.py):

    test        before fix                                 after fix
    duplicate   IDEMPOTENCY=0                              IDEMPOTENCY=1
    kill        COMMIT_MODE=before (commit on receipt)     COMMIT_MODE=after (commit when done)
    poison      MAX_RETRIES=0 (crash, restarted 3 times)   MAX_RETRIES=3 + s7875_dead_letter
    ordering    no key (round-robin over 2 partitions)     key = notice_code (the entity)

Each phase uses its own new consumer group whose offsets are first set to the current end of
s7875_tasks, so old messages from earlier runs never leak into a test. The Writer uses the
offline model stand-in (HW8_FAKE_LLM=1) unless --real-model is given: these tests are about
Kafka delivery, and a 1-second fixed answer keeps the timing readable.

Outputs in reports/hw08/raw/: part3_<test>_<phase>_<writer>.log (each Writer's console),
part3_<test>.json, part3_ordering_<run>.csv, part3_failure_table.json/.md.
"""

import argparse
import asyncio
import csv
import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiokafka.partitioner import DefaultPartitioner  # noqa: E402

from kafka_hw8.config import (  # noqa: E402
    BOOTSTRAP,
    DEAD_LETTER_TOPIC,
    DRAFTS_TOPIC,
    TASKS_TOPIC,
    VERIFY_SEED,
    WRITER_GROUP,
    banner,
)
from kafka_hw8.kafka_util import baseline_group as _baseline  # noqa: E402
from kafka_hw8.kafka_util import committed_offsets, end_offsets, read_from, send_json  # noqa: E402
from kafka_hw8.logutil import now, say  # noqa: E402

RAW = ROOT / "reports" / "hw08" / "raw"
STATE = ROOT / ".hw08_state" / "part3"
RUN_ID = time.strftime("%H%M%S")
TAG = "PART3"
FAKE = True


# ----------------------------------------------------------------- Writer processes --------
class WriterProc:
    def __init__(self, test, phase, agent_id, group, **env):
        self.agent_id = agent_id
        self.log_path = RAW / f"part3_{test}_{phase}_{agent_id}.log"
        self.lines: list[str] = []
        full_env = {**os.environ, "HW8_GROUP": group, "AGENT_ID": agent_id,
                    "HW8_FAKE_LLM": "1" if FAKE else "0", "HW8_STATE_DIR": str(STATE),
                    "PYTHONUNBUFFERED": "1", **{k: str(v) for k, v in env.items()}}
        self.fh = open(self.log_path, "a")
        self.proc = subprocess.Popen([sys.executable, "writer.py"], cwd=ROOT, env=full_env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._pump, daemon=True).start()
        say(TAG, f"started {agent_id} (pid {self.proc.pid}) group={group} "
                 f"{' '.join(f'{k}={v}' for k, v in env.items())}  log={self.log_path.name}")

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))
            self.fh.write(line)
            self.fh.flush()
            print(f"    | {line.rstrip()[:190]}", flush=True)

    def has(self, pattern: str) -> bool:
        rx = re.compile(pattern)
        return any(rx.search(ln) for ln in self.lines)

    def count(self, pattern: str) -> int:
        rx = re.compile(pattern)
        return sum(1 for ln in self.lines if rx.search(ln))

    async def wait_for(self, pattern: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.has(pattern):
                return True
            if self.proc.poll() is not None:
                await asyncio.sleep(0.3)  # let the pump finish
                return self.has(pattern)
            await asyncio.sleep(0.2)
        return False

    async def wait_exit(self, timeout: float) -> int | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                await asyncio.sleep(0.3)
                return self.proc.returncode
            await asyncio.sleep(0.2)
        return None

    def assignment(self) -> list[int] | None:
        found = None
        for ln in self.lines:
            m = re.search(r"ASSIGNED partitions \[([\d, ]*)\]", ln)
            if m:
                found = [int(x) for x in m.group(1).split(",") if x.strip()]
        return found

    def kill9(self):
        say(TAG, f"kill -9 {self.agent_id} (pid {self.proc.pid}) while it is mid-processing")
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.fh.close()


# ----------------------------------------------------------------- helpers -----------------
def new_group(test, phase) -> str:
    return f"{WRITER_GROUP}_p3_{test}_{phase}_{RUN_ID}"


async def baseline_group(group: str) -> dict[int, int]:
    return await _baseline(BOOTSTRAP, group, TASKS_TOPIC)


def task(corr: str, question: str, plan) -> dict:
    return {"correlation_id": corr, "stage": "plan", "question": question, "plan": plan,
            "trace": [{"agent": "part3-harness", "at": now()}]}


GOOD_PLAN = ["Say what the recall is about", "Give the steps a shopper should take"]
QUESTION = "What should I do with a recalled bag of frozen blueberries in my freezer?"


async def drafts_for(start, corr, timeout=4.0):
    items = await read_from(BOOTSTRAP, DRAFTS_TOPIC, start, timeout)
    return [i for i in items if i["value"].get("correlation_id") == corr]


def section(title):
    print(f"\n{'=' * 100}\n{now()}  {title}\n{'=' * 100}", flush=True)


async def ready(w: WriterProc, timeout=40):
    ok = await w.wait_for(r"is ready and listening", timeout)
    ok = ok and await w.wait_for(r"ASSIGNED partitions \[\d", timeout)
    if not ok:
        raise SystemExit(f"{w.agent_id} did not start/join - is Kafka up and are the topics "
                         f"created? see {w.log_path}")


# ----------------------------------------------------------------- 1. duplicate ------------
async def test_duplicate():
    results = {}
    for phase, idem in (("before", 0), ("after", 1)):
        section(f"DUPLICATE DELIVERY - {phase} fix (IDEMPOTENCY={idem})")
        group = new_group("duplicate", phase)
        await baseline_group(group)
        drafts_start = await end_offsets(BOOTSTRAP, DRAFTS_TOPIC)
        w = WriterProc("duplicate", phase, "writer-A", group, IDEMPOTENCY=idem)
        await ready(w)
        corr = f"dup-{phase}-{uuid.uuid4().hex[:8]}"
        msg = task(corr, QUESTION, GOOD_PLAN)
        say(TAG, f"send task corr={corr}, then REPLAY the identical message (same correlation_id)")
        placed = await send_json(BOOTSTRAP, TASKS_TOPIC, [(corr, msg), (corr, msg)])
        say(TAG, f"both copies written at (partition, offset) = {placed}")
        deadline = time.monotonic() + 40  # until both copies have been handled and committed
        while w.count(rf"COMMIT\s+corr={corr}") < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.3)
        await asyncio.sleep(1)
        drafts = await drafts_for(drafts_start, corr)
        r = {
            "group": group, "correlation_id": corr, "copies_sent": 2, "placed": placed,
            "received": w.count(rf"RECEIVE\s+corr={corr}"),
            "model_calls": w.count(rf"PROCESS-START\s+corr={corr}"),
            "duplicate_skips": w.count(rf"DUPLICATE-SKIP\s+corr={corr}"),
            "drafts_on_s7875_drafts": len(drafts),
            "log": w.log_path.name,
        }
        w.stop()
        say(TAG, f"RESULT {phase}: {json.dumps(r)}")
        results[phase] = r
    return results


# ----------------------------------------------------------------- 2. kill mid-work --------
async def test_kill():
    results = {}
    for phase, mode in (("before", "before"), ("after", "after")):
        section(f"CONSUMER KILLED MID-WORK - {phase} fix (COMMIT_MODE={mode})")
        group = new_group("kill", phase)
        await baseline_group(group)
        drafts_start = await end_offsets(BOOTSTRAP, DRAFTS_TOPIC)
        w1 = WriterProc("kill", phase, "writer-A", group, COMMIT_MODE=mode, WORK_DELAY_S=8)
        await ready(w1)
        corr = f"kill-{phase}-{uuid.uuid4().hex[:8]}"
        [(p, off)] = await send_json(BOOTSTRAP, TASKS_TOPIC,
                                     [(corr, task(corr, QUESTION, GOOD_PLAN))])
        say(TAG, f"sent task corr={corr} at partition={p} offset={off}")
        await w1.wait_for(rf"PROCESS-START\s+corr={corr}", 30)
        await asyncio.sleep(1.5)
        w1.kill9()
        committed_at_kill = (await committed_offsets(BOOTSTRAP, group, TASKS_TOPIC))[p]
        past = committed_at_kill is not None and committed_at_kill > off
        verdict = ("already past it -> it will NOT be read again" if past
                   else "not past it -> it will be read again")
        say(TAG, f"committed offset for partition {p} right after the kill = "
                 f"{committed_at_kill} (message offset {off}: {verdict})")
        say(TAG, "restart the Writer in the same consumer group")
        w2 = WriterProc("kill", phase, "writer-B", group, COMMIT_MODE=mode, WORK_DELAY_S=0)
        await ready(w2, timeout=60)
        redelivered = await w2.wait_for(rf"RECEIVE\s+corr={corr}", 25)
        if redelivered:
            await w2.wait_for(rf"COMMIT\s+corr={corr}", 30)
        await asyncio.sleep(1)
        drafts = await drafts_for(drafts_start, corr)
        committed_end = (await committed_offsets(BOOTSTRAP, group, TASKS_TOPIC))[p]
        r = {"group": group, "correlation_id": corr, "partition": p, "offset": off,
             "writer_A_started_processing": w1.has(rf"PROCESS-START\s+corr={corr}"),
             "writer_A_finished": w1.has(rf"SEND\s+corr={corr}"),
             "committed_offset_at_kill": committed_at_kill,
             "redelivered_to_writer_B": redelivered,
             "drafts_on_s7875_drafts": len(drafts),
             "committed_offset_at_end": committed_end,
             "outcome": "completed after restart" if drafts else "LOST (never completed)",
             "logs": [w1.log_path.name, w2.log_path.name]}
        w2.stop()
        w1.fh.close()
        say(TAG, f"RESULT {phase}: {json.dumps(r)}")
        results[phase] = r
    return results


# ----------------------------------------------------------------- 3. poison ---------------
async def test_poison():
    results = {}
    for phase in ("before", "after"):
        retries = 0 if phase == "before" else 3
        section(f"POISON MESSAGE - {phase} fix (MAX_RETRIES={retries})")
        group = new_group("poison", phase)
        await baseline_group(group)
        drafts_start = await end_offsets(BOOTSTRAP, DRAFTS_TOPIC)
        dlq_start = await end_offsets(BOOTSTRAP, DEAD_LETTER_TOPIC)
        bad = f"poison-{phase}-{uuid.uuid4().hex[:8]}"
        good = f"good-{phase}-{uuid.uuid4().hex[:8]}"
        # both on partition 0, poison first, so the good one sits behind it
        placed = await send_json(BOOTSTRAP, TASKS_TOPIC,
                                 [(bad, task(bad, QUESTION, None)),
                                  (good, task(good, QUESTION, GOOD_PLAN))],
                                 partition_for=lambda i: 0)
        say(TAG, f"sent poison corr={bad} (plan=null) then good corr={good} at {placed}")
        writers, crashes = [], 0
        if phase == "before":
            for attempt in range(1, 4):  # a supervisor restarting the crashed Writer
                w = WriterProc("poison", phase, f"writer-run{attempt}", group, MAX_RETRIES=0)
                writers.append(w)
                code = await w.wait_exit(45)
                if code is None:
                    break
                crashes += 1
                say(TAG, f"writer-run{attempt} exited with code {code} (crash #{crashes})"
                         + ("; restarting it" if attempt < 3 else "; giving up after 3 runs"))
            await asyncio.sleep(1)
        else:
            w = WriterProc("poison", phase, "writer-A", group, MAX_RETRIES=3,
                           RETRY_BACKOFF_S=0.5)
            writers.append(w)
            await w.wait_for(rf"COMMIT\s+corr={good}", 45)
            await asyncio.sleep(1)
        good_drafts = await drafts_for(drafts_start, good)
        dlq = [i for i in await read_from(BOOTSTRAP, DEAD_LETTER_TOPIC, dlq_start, 4)
               if i["value"].get("correlation_id") == bad]
        committed = (await committed_offsets(BOOTSTRAP, group, TASKS_TOPIC))[0]
        r = {"group": group, "poison_correlation_id": bad, "good_correlation_id": good,
             "placed": placed, "max_retries": retries,
             "writer_crashes": crashes,
             "poison_attempts": sum(w.count(rf"PROCESS-START\s+corr={bad}") for w in writers),
             "retry_lines": sum(w.count(rf"RETRY\s+corr={bad}") for w in writers),
             "poison_on_dead_letter": len(dlq),
             "dead_letter_record": dlq[0]["value"] if dlq else None,
             "good_message_processed": bool(good_drafts),
             "committed_offset_partition0": committed,
             "logs": [w.log_path.name for w in writers]}
        for w in writers:
            w.stop()
        brief = {k: v for k, v in r.items() if k != "dead_letter_record"}
        say(TAG, f"RESULT {phase}: {json.dumps(brief)}")
        results[phase] = r
    return results


# ----------------------------------------------------------------- 4. ordering -------------
def ordering_messages(run: str) -> tuple[list[dict], list[str]]:
    """20 related messages from VERIFY_SEED: status updates for a few notices, each notice's
    updates numbered seq 1, 2, 3, ... in the order they must be applied."""
    rng = random.Random(VERIFY_SEED)
    part = DefaultPartitioner()
    entities, seen_parts = [], set()
    while len(entities) < 4:  # 4 notices, with both partitions getting at least one under keying
        code = f"RCL-2026-{rng.randint(1, 99999):05d}"
        p = part(code.encode(), [0, 1], [0, 1])
        if code in entities or (len(entities) == 3 and seen_parts == {p}):
            continue
        entities.append(code)
        seen_parts.add(p)
    actions = ["opened", "lots_added", "stores_added", "units_updated", "class_changed",
               "press_release", "expanded", "closed"]
    seq = {e: 0 for e in entities}
    msgs = []
    for i in range(20):
        e = rng.choice(entities)
        seq[e] += 1
        mid = f"ord-{run}-{RUN_ID}-{i:02d}"
        msgs.append({"kind": "order_test", "run": run, "message_id": mid, "correlation_id": mid,
                     "entity": e, "seq": seq[e], "action": rng.choice(actions),
                     "work_ms": rng.randint(50, 600), "sent_index": i})
    return msgs, entities


def analyse(rows: list[dict], entities: list[str]) -> dict:
    rows = sorted(rows, key=lambda r: r["processed_at"])
    per = {}
    for e in entities:
        mine = [r for r in rows if r["entity"] == e]
        order = [r["seq"] for r in mine]
        inversions = sum(1 for a, b in zip(order, order[1:]) if b < a)
        per[e] = {"processed_seq_order": order, "in_order": order == sorted(order),
                  "inversions": inversions, "partitions": sorted({r["partition"] for r in mine}),
                  "writers": sorted({r["writer"] for r in mine})}
    return {"processed": len(rows), "entities": per,
            "entities_out_of_order": sum(1 for v in per.values() if not v["in_order"]),
            "total_inversions": sum(v["inversions"] for v in per.values())}


async def test_ordering():
    results = {}
    for run in ("unkeyed", "keyed"):
        section(f"ORDERING - {run} run: 20 messages (VERIFY_SEED={VERIFY_SEED}) through "
                f"{TASKS_TOPIC} (2 partitions), 2 Writers in one consumer group")
        group = new_group("ordering", run)
        await baseline_group(group)
        order_log = RAW / f"part3_ordering_{run}.jsonl"
        order_log.write_text("")
        w1 = WriterProc("ordering", run, "writer-1", group, HW8_ORDER_LOG=order_log)
        await ready(w1)
        w2 = WriterProc("ordering", run, "writer-2", group, HW8_ORDER_LOG=order_log)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            a1, a2 = w1.assignment(), w2.assignment()
            if a1 is not None and a2 is not None and len(a1) == 1 and len(a2) == 1:
                break
            await asyncio.sleep(0.3)
        say(TAG, f"assignment: writer-1 -> {w1.assignment()}  writer-2 -> {w2.assignment()}")
        msgs, entities = ordering_messages(run)
        if run == "unkeyed":
            placed = await send_json(BOOTSTRAP, TASKS_TOPIC, [(None, m) for m in msgs],
                                     partition_for=lambda i: i % 2)
        else:
            placed = await send_json(BOOTSTRAP, TASKS_TOPIC, [(m["entity"], m) for m in msgs])
        for m, (p, off) in zip(msgs, placed):
            m["partition"], m["offset"] = p, off
        how = "no key, round-robin i%2" if run == "unkeyed" else "key=entity"
        say(TAG, f"sent 20 messages ({how})")
        deadline = time.monotonic() + 60
        rows = []
        while time.monotonic() < deadline:
            rows = [json.loads(ln) for ln in order_log.read_text().splitlines() if ln.strip()]
            if len(rows) >= 20:
                break
            await asyncio.sleep(0.5)
        w1.stop()
        w2.stop()
        a = analyse(rows, entities)
        with open(RAW / f"part3_ordering_{run}.csv", "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["processed_rank", "processed_at", "writer", "partition", "offset", "key",
                         "entity", "seq", "message_id"])
            for i, r in enumerate(sorted(rows, key=lambda r: r["processed_at"]), 1):
                wr.writerow([i, r["processed_at"], r["writer"], r["partition"], r["offset"],
                             r["key"], r["entity"], r["seq"], r["message_id"]])
        print("\n  sent order (index: entity seq -> partition):")
        for m in msgs:
            print(f"    {m['sent_index']:>2}: {m['entity']} seq={m['seq']} -> p{m['partition']} "
                  f"(work {m['work_ms']} ms)")
        print("\n  processed order per entity:")
        for e, v in a["entities"].items():
            print(f"    {e}: seq {v['processed_seq_order']}  partitions={v['partitions']} "
                  f"writers={v['writers']}  {'IN ORDER' if v['in_order'] else 'OUT OF ORDER'}")
        results[run] = {"group": group, "sent": msgs, "analysis": a,
                        "assignment": {"writer-1": w1.assignment(), "writer-2": w2.assignment()},
                        "logs": [w1.log_path.name, w2.log_path.name]}
        say(TAG, f"RESULT {run}: processed={a['processed']} entities_out_of_order="
                 f"{a['entities_out_of_order']} inversions={a['total_inversions']}")
    return results


# ----------------------------------------------------------------- table -------------------
def failure_table(res: dict) -> list[dict]:
    rows = []
    if "duplicate" in res:
        b, a = res["duplicate"]["before"], res["duplicate"]["after"]
        rows.append({"scenario": "Duplicate delivery",
                     "before": f"same task sent twice -> {b['model_calls']} model calls, "
                               f"{b['drafts_on_s7875_drafts']} drafts (extra side effect)",
                     "after": f"{a['model_calls']} model call, "
                              f"{a['drafts_on_s7875_drafts']} draft, "
                              f"{a['duplicate_skips']} DUPLICATE-SKIP"})
    if "kill" in res:
        b, a = res["kill"]["before"], res["kill"]["after"]
        rows.append({"scenario": "Consumer killed mid-work",
                     "before": f"offset committed on receipt (committed="
                               f"{b['committed_offset_at_kill']} > msg offset {b['offset']}); "
                               f"after restart redelivered="
                               f"{b['redelivered_to_writer_B']} -> {b['outcome']}",
                     "after": f"commit after send (committed="
                              f"{a['committed_offset_at_kill']} at kill); "
                              f"redelivered={a['redelivered_to_writer_B']} -> {a['outcome']}"})
    if "poison" in res:
        b, a = res["poison"]["before"], res["poison"]["after"]
        rows.append({"scenario": "Poison message",
                     "before": f"Writer crashed {b['writer_crashes']}x on the same offset; good "
                               f"message processed={b['good_message_processed']} (blocked)",
                     "after": f"{a['retry_lines']} attempts -> {DEAD_LETTER_TOPIC} "
                              f"({a['poison_on_dead_letter']} record); good message processed="
                              f"{a['good_message_processed']}"})
    if "ordering" in res:
        b, a = res["ordering"]["unkeyed"]["analysis"], res["ordering"]["keyed"]["analysis"]
        rows.append({"scenario": "Two partitions/two consumers",
                     "before": f"no key: {b['entities_out_of_order']}/4 notices processed out of "
                               f"order ({b['total_inversions']} inversions)",
                     "after": f"key=notice_code: {a['entities_out_of_order']}/4 out of order; each "
                              "notice on one partition"})
    return rows


async def main():
    global FAKE
    ap = argparse.ArgumentParser()
    ap.add_argument("test", choices=["all", "duplicate", "kill", "poison", "ordering"])
    ap.add_argument("--real-model", action="store_true", help="Writer calls Ollama")
    args = ap.parse_args()
    FAKE = not args.real_model
    print(banner(f"run_hw08_part3.py {args.test} (run {RUN_ID})"), flush=True)
    RAW.mkdir(parents=True, exist_ok=True)
    tests = {"duplicate": test_duplicate, "kill": test_kill, "poison": test_poison,
             "ordering": test_ordering}
    todo = list(tests) if args.test == "all" else [args.test]
    res = {}
    for name in todo:
        res[name] = await tests[name]()
        (RAW / f"part3_{name}.json").write_text(json.dumps(
            {"run_id": RUN_ID, "run_at": now(), "writer_model": "offline stand-in" if FAKE
             else "ollama", **res[name]}, indent=2, default=str))
    table_path = RAW / "part3_failure_table.json"
    old = json.loads(table_path.read_text()) if table_path.exists() else {}
    merged = {**old.get("results", {}), **res}
    rows = failure_table(merged)
    table_path.write_text(json.dumps({"updated_at": now(), "rows": rows,
                                      "results": merged}, indent=2, default=str))
    md = ["| Failure scenario | Before fix | After fix |", "|---|---|---|"]
    md += [f"| {r['scenario']} | {r['before']} | {r['after']} |" for r in rows]
    (RAW / "part3_failure_table.md").write_text("\n".join(md) + "\n")
    section("FAILURE TABLE")
    print("\n".join(md))


if __name__ == "__main__":
    asyncio.run(main())
