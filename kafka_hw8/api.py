"""HW8 Part 1: FastAPI wrapper. HTTP in, Kafka request/response out, on PORT_BASE (8675).

    POST /kafka/notices   body: {"operation": "CREATE_NOTICE" | "GET_NOTICE", "data": {...},
                                 "correlation_id": "<optional, kept unchanged if given>"}
    GET  /kafka/notices/{notice_id}   shortcut for GET_NOTICE
    GET  /health

The API never touches the notice dict itself: it only publishes to s7875_notice_requests and
returns whatever the worker answers on s7875_notice_responses.

Run:  uvicorn kafka_hw8.api:app --host 0.0.0.0 --port 8675   (docker compose runs this)
"""

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI

from .config import BOOTSTRAP, OP_GET, PORT_BASE, REQUEST_TOPIC, RESPONSE_TOPIC, banner
from .kafka_util import wait_for_kafka
from .logutil import log, say
from .rpc_client import KafkaRPCClient, new_correlation_id

TAG = "API"
rpc = KafkaRPCClient(tag=TAG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(banner("FastAPI Kafka wrapper"), flush=True)
    await wait_for_kafka(BOOTSTRAP, TAG)
    await rpc.start()
    say(TAG, f"requests -> {REQUEST_TOPIC}, responses <- {RESPONSE_TOPIC}")
    say(TAG, f"FastAPI server started at http://127.0.0.1:{PORT_BASE}")
    yield
    await rpc.stop()


app = FastAPI(title="s7875 notice service over Kafka (HW8)", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "request_topic": REQUEST_TOPIC, "response_topic": RESPONSE_TOPIC}


@app.post("/kafka/notices")
async def notice_request(body: dict = Body(...)):
    corr = body.get("correlation_id") or new_correlation_id()
    log(TAG, "HTTP-REQUEST", corr, body)
    response = await rpc.request(body.get("operation"), body.get("data"), correlation_id=corr)
    log(TAG, "HTTP-RESPONSE", corr, response)
    return response


@app.get("/kafka/notices/{notice_id}")
async def get_notice(notice_id: str):
    corr = new_correlation_id()
    log(TAG, "HTTP-REQUEST", corr, {"operation": OP_GET, "notice_id": notice_id})
    response = await rpc.request(OP_GET, {"notice_id": notice_id}, correlation_id=corr)
    log(TAG, "HTTP-RESPONSE", corr, response)
    return response
