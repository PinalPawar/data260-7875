"""HW8 Part 1: request/response over Kafka, client side (used by the API and homework_demo.py).

The caller creates correlation_id once. The client puts it in the request envelope unchanged,
waits on s7875_notice_responses for a response carrying that same id, and returns it.

The response consumer has no consumer group: it is assigned the response partitions directly and
starts at the end, so the API and homework_demo.py can both listen at the same time without
taking each other's responses (each one simply ignores ids it is not waiting for).
"""

import asyncio
import json
import uuid

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition

from .config import BOOTSTRAP, REQUEST_TOPIC, RESPONSE_TOPIC
from .kafka_util import partitions_of
from .logutil import log, say


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def build_request(correlation_id: str, operation: str, data) -> dict:
    return {
        "correlation_id": correlation_id,
        "reply_to": RESPONSE_TOPIC,
        "operation": operation,
        "data": data,
    }


class KafkaRPCClient:
    def __init__(self, tag: str = "CLIENT", bootstrap: str = BOOTSTRAP, timeout_s: float = 15.0):
        self.tag = tag
        self.bootstrap = bootstrap
        self.timeout_s = timeout_s
        self.pending: dict[str, asyncio.Future] = {}
        self._task = None

    async def start(self) -> None:
        self.producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap, acks="all")
        self.consumer = AIOKafkaConsumer(bootstrap_servers=self.bootstrap,
                                         enable_auto_commit=False)
        await self.producer.start()
        await self.consumer.start()
        tps = [TopicPartition(RESPONSE_TOPIC, p)
               for p in await partitions_of(self.bootstrap, RESPONSE_TOPIC)]
        self.consumer.assign(tps)
        await self.consumer.seek_to_end(*tps)
        for tp in tps:  # resolve the position now, before any request goes out
            await self.consumer.position(tp)
        self._task = asyncio.create_task(self._listen())
        say(self.tag, f"listening for responses on {RESPONSE_TOPIC}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.consumer.stop()
        await self.producer.stop()

    async def _listen(self) -> None:
        async for record in self.consumer:
            try:
                response = json.loads(record.value.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            corr = response.get("correlation_id")
            future = self.pending.pop(corr, None)
            if future is None:
                continue  # someone else's response
            log(self.tag, "CLIENT-RESPONSE", corr, response, topic=record.topic,
                p=record.partition, off=record.offset)
            if not future.done():
                future.set_result(response)

    async def request(self, operation: str, data, correlation_id: str | None = None) -> dict:
        corr = correlation_id or new_correlation_id()
        message = build_request(corr, operation, data)
        future = asyncio.get_running_loop().create_future()
        self.pending[corr] = future
        # logged before the write, so a merged log never shows the worker's RECEIVE first
        log(self.tag, "SEND", corr, message, topic=REQUEST_TOPIC)
        await self.producer.send_and_wait(REQUEST_TOPIC, json.dumps(message).encode(),
                                          key=corr.encode())
        try:
            response = await asyncio.wait_for(future, timeout=self.timeout_s)
        except asyncio.TimeoutError:
            self.pending.pop(corr, None)
            response = {"correlation_id": corr, "operation": operation, "success": False,
                        "error": f"Timed out after {self.timeout_s:.0f}s waiting for the worker"}
            log(self.tag, "TIMEOUT", corr)
        if response.get("correlation_id") != corr:  # cannot happen by construction; be loud
            raise RuntimeError("correlation_id changed in transit")
        return response
