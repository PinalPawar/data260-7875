"""HW8 Parts 2-3: the Kafka consumer loop every agent (Planner, Writer, Reviewer) runs.

One message at a time:  RECEIVE -> (duplicate?) -> PROCESS (with bounded retries) -> SEND -> COMMIT

The four Part 3 fixes live here, each behind a switch so the "before" behaviour can be shown:

    switch (env var)      after fix (default)                    before fix
    IDEMPOTENCY           1: skip a key already processed         0: process every copy again
    COMMIT_MODE           after: commit once output is sent       before: commit on receipt
    MAX_RETRIES           3: retry, then s7875_dead_letter        0: no handling, the agent
                                                                     crashes and, uncommitted,
                                                                     hits the same message again
    (partition key)       set by the producer: see scripts/run_hw08_part3.py ordering

The idempotency key is the message's message_id if it has one, else its correlation_id. Keys
are kept in a small SQLite file per agent and consumer group (.hw08_state/), so a restarted
agent still remembers what it finished before it died.

Other knobs: WORK_DELAY_S (sleep inside processing, to have time to kill the Writer mid-work),
RETRY_BACKOFF_S, HW8_GROUP (consumer group override), AGENT_ID (name shown in logs).
"""

import asyncio
import json
import os
import signal
import sqlite3
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRebalanceListener, TopicPartition

from .config import BOOTSTRAP, DEAD_LETTER_TOPIC, banner
from .kafka_util import wait_for_kafka
from .logutil import log, now, say

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Out:
    topic: str
    key: str | None
    value: dict


@dataclass
class Settings:
    idempotency: bool = True
    commit_mode: str = "after"
    max_retries: int = 3
    retry_backoff_s: float = 0.5
    work_delay_s: float = 0.0

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(
            idempotency=os.getenv("IDEMPOTENCY", "1") != "0",
            commit_mode=os.getenv("COMMIT_MODE", "after"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_backoff_s=float(os.getenv("RETRY_BACKOFF_S", "0.5")),
            work_delay_s=float(os.getenv("WORK_DELAY_S", "0")),
        )
        if s.commit_mode not in ("after", "before"):
            raise SystemExit("COMMIT_MODE must be 'after' or 'before'")
        return s


class ProcessedStore:
    """Idempotency keys this agent has finished (survives restarts)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS processed (key TEXT PRIMARY KEY, "
                        "topic TEXT, partition INTEGER, offset INTEGER, at TEXT, outcome TEXT)")
        self.db.commit()

    def seen(self, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM processed WHERE key=?", (key,)).fetchone() is not None

    def mark(self, key: str, record, outcome: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO processed VALUES (?,?,?,?,?,?)",
                        (key, record.topic, record.partition, record.offset, now(), outcome))
        self.db.commit()


class _Rebalance(ConsumerRebalanceListener):
    def __init__(self, tag):
        self.tag = tag

    async def on_partitions_revoked(self, revoked):
        if revoked:
            say(self.tag, f"REVOKED partitions {sorted(tp.partition for tp in revoked)}")

    async def on_partitions_assigned(self, assigned):
        say(self.tag, f"ASSIGNED partitions {sorted(tp.partition for tp in assigned)}")


class KafkaAgent:
    name = "agent"  # planner / writer / reviewer
    in_topic = ""
    group = ""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.group = os.getenv("HW8_GROUP", self.group)
        self.agent_id = os.getenv("AGENT_ID", f"{self.name}-{os.getpid()}")
        self.tag = self.name.upper() if "AGENT_ID" not in os.environ else self.agent_id.upper()
        state_dir = Path(os.getenv("HW8_STATE_DIR", ROOT / ".hw08_state"))
        self.store = ProcessedStore(state_dir / f"{self.name}__{self.group}.sqlite")

    # ---- to be provided by each agent ----
    async def handle(self, msg: dict, record) -> list[Out]:
        raise NotImplementedError

    # ---- the loop ----
    async def run(self) -> None:
        s = self.settings
        print(banner(f"{self.name} ({self.agent_id})"), flush=True)
        say(self.tag, f"in={self.in_topic} group={self.group} idempotency={s.idempotency} "
                      f"commit_mode={s.commit_mode} max_retries={s.max_retries} "
                      f"work_delay_s={s.work_delay_s} dead_letter={DEAD_LETTER_TOPIC}")
        await wait_for_kafka(BOOTSTRAP, self.tag)
        self.consumer = AIOKafkaConsumer(
            bootstrap_servers=BOOTSTRAP,
            group_id=self.group,
            enable_auto_commit=False,  # every commit below is explicit
            auto_offset_reset="earliest",
            max_poll_interval_ms=600_000,  # a slow model call must not get us kicked out
        )
        self.consumer.subscribe([self.in_topic], listener=_Rebalance(self.tag))
        self.producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all")
        await self.consumer.start()
        await self.producer.start()
        say(self.tag, f"{self.name} is ready and listening on {self.in_topic}")
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        try:
            consume = asyncio.create_task(self._consume())
            waiter = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait({consume, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if consume in done:
                consume.result()  # re-raise a crash (MAX_RETRIES=0)
            else:
                consume.cancel()
                say(self.tag, "stopping (signal)")
        finally:
            await self.consumer.stop()
            await self.producer.stop()

    async def _consume(self) -> None:
        async for record in self.consumer:
            await self.process_record(record)

    async def process_record(self, record) -> None:
        s = self.settings
        tp = TopicPartition(record.topic, record.partition)
        msg, decode_error = _decode(record.value)
        corr = msg.get("correlation_id") if isinstance(msg, dict) else None
        key = _idem_key(msg, record)
        log(self.tag, "RECEIVE", corr, msg if msg is not None else {"_raw": _raw(record.value)},
            topic=record.topic, p=record.partition, off=record.offset, key=key)

        if s.commit_mode == "before":
            await self.consumer.commit({tp: record.offset + 1})
            log(self.tag, "COMMIT", corr, p=record.partition, next_offset=record.offset + 1,
                note="committed BEFORE processing (COMMIT_MODE=before)")

        if s.idempotency and self.store.seen(key):
            log(self.tag, "DUPLICATE-SKIP", corr, key=key,
                note="already processed; no model call, nothing sent")
            await self._commit_after(tp, record, corr)
            return

        outputs: list[Out] = []
        outcome = "ok"
        attempt = 0
        while True:
            attempt += 1
            try:
                if decode_error:
                    raise ValueError(f"message is not valid JSON: {decode_error}")
                log(self.tag, "PROCESS-START", corr, attempt=attempt,
                    work_delay_s=s.work_delay_s)
                if s.work_delay_s:
                    await asyncio.sleep(s.work_delay_s)
                outputs = await self.handle(msg, record)
                break
            except Exception as exc:  # noqa: BLE001 - every failure is retried or dead-lettered
                err = f"{type(exc).__name__}: {exc}"
                if s.max_retries <= 0:
                    log(self.tag, "CRASH", corr, error=err, p=record.partition,
                        off=record.offset, note="no retry handling (MAX_RETRIES=0); "
                        "offset not committed")
                    raise
                log(self.tag, "RETRY", corr, attempt=f"{attempt}/{s.max_retries}", error=err)
                if attempt >= s.max_retries:
                    dead = {
                        "correlation_id": corr,
                        "failed_agent": self.name,
                        "agent_id": self.agent_id,
                        "error": err,
                        "attempts": attempt,
                        "source": {"topic": record.topic, "partition": record.partition,
                                   "offset": record.offset},
                        "original": msg if msg is not None else _raw(record.value),
                        "dead_lettered_at": now(),
                    }
                    outputs = [Out(DEAD_LETTER_TOPIC, corr, dead)]
                    outcome = "dead_letter"
                    log(self.tag, "DEAD-LETTER", corr, topic=DEAD_LETTER_TOPIC,
                        attempts=attempt, error=err)
                    break
                await asyncio.sleep(s.retry_backoff_s * attempt)

        for out in outputs:
            log(self.tag, "SEND", out.value.get("correlation_id"), out.value, topic=out.topic)
            await self.producer.send_and_wait(out.topic, json.dumps(out.value).encode(),
                                              key=out.key.encode() if out.key else None)
        if s.idempotency:
            self.store.mark(key, record, outcome)
        await self._commit_after(tp, record, corr)

    async def _commit_after(self, tp, record, corr) -> None:
        if self.settings.commit_mode == "after":
            await self.consumer.commit({tp: record.offset + 1})
            log(self.tag, "COMMIT", corr, p=record.partition, next_offset=record.offset + 1)


def trace_entry(agent: "KafkaAgent", record) -> dict:
    return {"agent": agent.name, "agent_id": agent.agent_id, "read_from": record.topic,
            "partition": record.partition, "offset": record.offset, "at": now()}


def _decode(value: bytes):
    try:
        return json.loads(value.decode()), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _raw(value: bytes) -> str:
    return value.decode(errors="replace")[:500]


def _idem_key(msg, record) -> str:
    if isinstance(msg, dict):
        for k in ("message_id", "correlation_id"):
            if msg.get(k):
                return str(msg[k])
    return f"{record.topic}:{record.partition}:{record.offset}"


def main(agent_cls) -> None:
    try:
        asyncio.run(agent_cls().run())
    except KeyboardInterrupt:
        pass
    except Exception:  # crash path: print and exit non-zero so a supervisor sees it
        traceback.print_exc()
        sys.exit(1)
