"""Small aiokafka helpers shared by the HW8 worker, API, agents and scripts."""

import asyncio
import json
import time

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import KafkaConnectionError

from .logutil import say


async def wait_for_kafka(bootstrap: str, tag: str, timeout_s: float = 90.0) -> None:
    """Block until the broker answers (the worker container can start before Kafka is up)."""
    deadline = time.monotonic() + timeout_s
    while True:
        admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
        try:
            await admin.start()
            await admin.close()
            return
        except (KafkaConnectionError, OSError) as exc:
            if time.monotonic() > deadline:
                raise RuntimeError(f"Kafka not reachable at {bootstrap}") from exc
            say(tag, f"waiting for Kafka at {bootstrap} ...")
            await asyncio.sleep(2)


async def ensure_topics(bootstrap: str, partitions: dict[str, int]) -> list[str]:
    """Create any missing topics (replication factor 1). Returns the names it created."""
    from aiokafka.admin import NewTopic

    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        todo = [NewTopic(name, n, 1) for name, n in partitions.items() if name not in existing]
        if todo:
            await admin.create_topics(todo)
        return [t.name for t in todo]
    finally:
        await admin.close()


async def end_offsets(bootstrap: str, topic: str) -> dict[int, int]:
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap, enable_auto_commit=False)
    await consumer.start()
    try:
        parts = await partitions_of(bootstrap, topic)
        tps = [TopicPartition(topic, p) for p in parts]
        ends = await consumer.end_offsets(tps)
        return {tp.partition: off for tp, off in ends.items()}
    finally:
        await consumer.stop()


async def baseline_group(bootstrap: str, group: str, topic: str) -> dict[int, int]:
    """Commit the current end of `topic` for a brand-new consumer group, so the group starts
    from "now" and never reads messages left over from earlier runs."""
    ends = await end_offsets(bootstrap, topic)
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap, group_id=group,
                                enable_auto_commit=False)
    await consumer.start()
    try:
        tps = {TopicPartition(topic, p): off for p, off in ends.items()}
        consumer.assign(list(tps))
        await consumer.commit(tps)
    finally:
        await consumer.stop()
    return ends


async def committed_offsets(bootstrap: str, group: str, topic: str) -> dict[int, int | None]:
    """The offsets a consumer group has committed for a topic (None = nothing committed)."""
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap, group_id=group,
                                enable_auto_commit=False)
    await consumer.start()
    try:
        parts = await partitions_of(bootstrap, topic)
        out = {}
        for p in parts:
            out[p] = await consumer.committed(TopicPartition(topic, p))
        return out
    finally:
        await consumer.stop()


async def read_from(bootstrap: str, topic: str, start: dict[int, int], timeout_s: float,
                    until=None) -> list[dict]:
    """Read JSON messages from `topic` starting at the given per-partition offsets, without a
    consumer group (so nothing is committed and no real consumer is disturbed).

    Stops after timeout_s, or earlier once until(messages) returns True. Each item is
    {"partition", "offset", "key", "timestamp", "value"}.
    """
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap, enable_auto_commit=False)
    await consumer.start()
    out: list[dict] = []
    try:
        tps = [TopicPartition(topic, p) for p in start]
        consumer.assign(tps)
        for tp in tps:
            consumer.seek(tp, start[tp.partition])
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            batch = await consumer.getmany(timeout_ms=500)
            for _, records in batch.items():
                for r in records:
                    try:
                        value = json.loads(r.value.decode())
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        value = {"_raw": r.value.decode(errors="replace")}
                    out.append({"partition": r.partition, "offset": r.offset,
                                "key": r.key.decode() if r.key else None,
                                "timestamp": r.timestamp, "value": value})
            if until is not None and until(out):
                break
        return out
    finally:
        await consumer.stop()


async def send_json(bootstrap: str, topic: str, messages: list[tuple[str | None, dict]],
                    partition_for=None) -> list[tuple[int, int]]:
    """Send (key, value) pairs in order; returns [(partition, offset)].

    partition_for(i) can force a partition (used for the un-keyed ordering run).
    """
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap, acks="all")
    await producer.start()
    placed = []
    try:
        for i, (key, value) in enumerate(messages):
            kwargs = {}
            if partition_for is not None:
                kwargs["partition"] = partition_for(i)
            meta = await producer.send_and_wait(
                topic, json.dumps(value).encode(), key=key.encode() if key else None, **kwargs)
            placed.append((meta.partition, meta.offset))
        return placed
    finally:
        await producer.stop()


async def partitions_of(bootstrap: str, topic: str) -> list[int]:
    """Partition numbers of an existing topic (asks the broker through a short-lived producer,
    whose partitions_for() refreshes metadata; auto topic creation is off, so a missing topic
    is an error rather than silently created)."""
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap, request_timeout_ms=10000)
    await producer.start()
    try:
        topics = await list_topics(bootstrap)
        if topic not in topics:
            raise RuntimeError(f"topic {topic} not found - run scripts/hw08_create_topics.sh")
        return sorted(await producer.partitions_for(topic))
    finally:
        await producer.stop()


async def list_topics(bootstrap: str) -> set[str]:
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap, enable_auto_commit=False)
    await consumer.start()
    try:
        return await consumer.topics()
    finally:
        await consumer.stop()
