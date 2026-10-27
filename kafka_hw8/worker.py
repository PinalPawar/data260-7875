"""HW8 Part 1: the notice worker.

Consumes s7875_notice_requests, runs CREATE_NOTICE / GET_NOTICE against an in-memory dict, and
sends the response to the topic named in the request's reply_to, echoing correlation_id.

The offset is committed only after the response has been sent, so a crash mid-request means the
request is read again on restart rather than lost. A request whose correlation_id was already
answered is not processed twice: the stored response is sent again instead (no second notice).

Run:  python -m kafka_hw8.worker          (docker compose runs exactly this)
"""

import asyncio
import json
import os

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition

from .config import BOOTSTRAP, PREFIX, REQUEST_TOPIC, RESPONSE_TOPIC, WORKER_GROUP, banner
from .kafka_util import wait_for_kafka
from .logutil import log, say
from .notice_service import NoticeService

TAG = "WORKER"


def pick_reply_topic(request) -> str:
    reply_to = request.get("reply_to") if isinstance(request, dict) else None
    if isinstance(reply_to, str) and reply_to.startswith(f"{PREFIX}_"):
        return reply_to
    return RESPONSE_TOPIC  # never write to a topic outside this student's prefix


async def main() -> None:
    print(banner("notice worker"), flush=True)
    service = NoticeService(idempotent=os.getenv("IDEMPOTENCY", "1") != "0")
    await wait_for_kafka(BOOTSTRAP, TAG)
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id=WORKER_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await consumer.start()
    await producer.start()
    say(TAG, f"bootstrap={BOOTSTRAP} group={WORKER_GROUP} idempotency={service.idempotent}")
    say(TAG, f"consuming {REQUEST_TOPIC}, default reply topic {RESPONSE_TOPIC}")
    print("Consumer is ready and listening...", flush=True)
    try:
        async for record in consumer:
            try:
                request = json.loads(record.value.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                request = None
            corr = request.get("correlation_id") if isinstance(request, dict) else None
            log(TAG, "RECEIVE", corr, request, topic=record.topic, p=record.partition,
                off=record.offset)

            response, duplicate = service.handle(request)
            if duplicate:
                log(TAG, "DUPLICATE", corr, note="correlation_id already answered; "
                    "re-sending stored response, nothing re-processed")
            else:
                log(TAG, "PROCESS", corr, operation=response.get("operation"),
                    success=response["success"], notices_in_store=len(service.notices))

            reply_topic = pick_reply_topic(request)
            log(TAG, "REPLY", corr, response, topic=reply_topic)
            await producer.send_and_wait(reply_topic, json.dumps(response).encode(),
                                         key=(corr or "").encode() or None)
            # commit only after the reply is safely written
            await consumer.commit({TopicPartition(record.topic, record.partition):
                                   record.offset + 1})
    finally:
        await consumer.stop()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
