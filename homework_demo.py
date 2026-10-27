"""
HW8 Part 1 demonstration: CREATE_NOTICE -> GET_NOTICE over Kafka, with the correlation_id kept
unchanged end to end.

    docker compose -f docker-compose.kafka.yml up -d --build     # Kafka + worker + API
    python homework_demo.py                  # this script is the Kafka client
    python homework_demo.py --via api        # same flow, but through the FastAPI wrapper (8675)

Steps 1-10 from the assignment are printed as headers. The client's own SEND / RECEIVE lines are
printed live; the worker (and API) lines come from their containers, so at the end the script
pulls them with `docker logs` and prints one merged, time-sorted sequence per request (step 9).
Everything is also saved to reports/hw08/raw/part1_demo.json.
"""

import argparse
import asyncio
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import requests

from kafka_hw8.config import (
    ID_FIELD,
    OP_CREATE,
    OP_GET,
    PORT_BASE,
    REQUEST_TOPIC,
    RESPONSE_TOPIC,
    banner,
)
from kafka_hw8 import logutil
from kafka_hw8.logutil import log, now, parse_ts
from kafka_hw8.rpc_client import KafkaRPCClient, build_request, new_correlation_id

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "reports" / "hw08" / "raw"
API_URL = f"http://127.0.0.1:{PORT_BASE}/kafka/notices"
CONTAINERS = ["s7875_notice_api", "s7875_notice_worker"]

SAMPLE_NOTICE = {
    "product": "Organic Baby Spinach 5oz",
    "notice_code": "RCL-2026-07875",
    "units_affected": 4471,
    "manufacturer_id": 1,
    "email": "recalls@greenfields-foods.com",
    "description": "Routine testing found Listeria monocytogenes in lot L4471. "
                   "Bags were sold in California and Nevada stores.",
    "category": "bacterialContamination",
}


def step(n: int, text: str) -> None:
    print(f"\n----- Step {n}: {text}", flush=True)


async def send(client, via: str, operation: str, data, corr: str) -> dict:
    if via == "kafka":
        return await client.request(operation, data, correlation_id=corr)
    body = {"correlation_id": corr, "operation": operation, "data": data}
    log("CLIENT", "HTTP-POST", corr, body, url=API_URL)
    resp = await asyncio.to_thread(requests.post, API_URL, json=body, timeout=30)
    response = resp.json()
    log("CLIENT", "HTTP-200" if resp.ok else f"HTTP-{resp.status_code}", corr, response)
    return response


def container_lines(since: str, corrs: list[str]) -> list[str]:
    lines = []
    for name in CONTAINERS:
        try:
            out = subprocess.run(["docker", "logs", "--since", since, name],
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in (out.stdout + out.stderr).splitlines():
            if any(c in line for c in corrs) and parse_ts(line):
                lines.append(line)
    return lines


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--via", choices=["kafka", "api"], default="kafka",
                    help="kafka: this script is the Kafka client; api: go through FastAPI")
    ap.add_argument("--no-docker-logs", action="store_true")
    ap.add_argument("--log-file", action="append", default=[],
                    help="also merge lines from this log file (worker/API run outside Docker)")
    args = ap.parse_args()

    print(banner(f"homework_demo.py (via {args.via})"), flush=True)
    print(f"request topic = {REQUEST_TOPIC}   response topic = {RESPONSE_TOPIC}")
    started = datetime.now().astimezone()
    logutil.CAPTURE = []  # keep this script's own log lines for the merged view

    client = None
    if args.via == "kafka":
        client = KafkaRPCClient(tag="CLIENT")
        await client.start()

    try:
        # ---------------- CREATE_NOTICE ----------------
        step(1, "create one correlation_id for the CREATE_NOTICE request")
        create_corr = new_correlation_id()
        print(f"correlation_id = {create_corr}")

        step(2, f"send CREATE_NOTICE to {REQUEST_TOPIC}")
        step(3, "the request message (as written to the request topic)")
        print(json.dumps(build_request(create_corr, OP_CREATE, SAMPLE_NOTICE), indent=2))
        step(4, "worker receives and processes it   (see merged log in step 9)")
        step(5, f"worker replies on {RESPONSE_TOPIC}   (see merged log in step 9)")
        create_resp = await send(client, args.via, OP_CREATE, SAMPLE_NOTICE, create_corr)

        step(6, "response received by the client")
        print(json.dumps(create_resp, indent=2))
        if not create_resp.get("success"):
            raise SystemExit("CREATE_NOTICE failed - is the worker running? (docker ps)")

        step(7, f"extract the generated {ID_FIELD}")
        notice_id = create_resp[ID_FIELD]
        print(f"{ID_FIELD} = {notice_id}")

        # ---------------- GET_NOTICE ----------------
        step(8, f"send GET_NOTICE for that {ID_FIELD} (new correlation_id for this request)")
        get_corr = new_correlation_id()
        get_data = {ID_FIELD: notice_id}
        print(f"correlation_id = {get_corr}")
        print(json.dumps(build_request(get_corr, OP_GET, get_data), indent=2))
        get_resp = await send(client, args.via, OP_GET, get_data, get_corr)

        # ---------------- error cases (clean errors, id still echoed) ----------------
        print("\n----- Extra: error responses keep the correlation_id too")
        bad_cases = [
            ("unknown operation", "DELETE_EVERYTHING", {}),
            ("missing field", OP_CREATE, {k: v for k, v in SAMPLE_NOTICE.items()
                                          if k != "email"}),
            ("invalid notice_code", OP_CREATE, {**SAMPLE_NOTICE, "notice_code": "RCL-26-1"}),
            ("unknown notice_id", OP_GET, {ID_FIELD: "00000000-0000-0000-0000-000000000000"}),
        ]
        errors = []
        for label, op, data in bad_cases:
            corr = new_correlation_id()
            resp = await send(client, args.via, op, data, corr)
            same = resp.get("correlation_id") == corr
            print(f"  {label:<20} success={resp.get('success')} error={resp.get('error')!r} "
                  f"correlation_id preserved={same}")
            errors.append({"case": label, "sent_correlation_id": corr, "response": resp,
                           "correlation_id_preserved": same})
    finally:
        if client:
            await client.stop()

    step(9, "full sequence (client + API + worker lines, merged by timestamp)")
    merged = {}
    since = (started - timedelta(seconds=10)).isoformat()  # margin for clock skew
    container = [] if args.no_docker_logs else container_lines(since, [create_corr, get_corr])
    for path in args.log_file:
        container += [ln for ln in Path(path).read_text().splitlines()
                      if parse_ts(ln) and parse_ts(ln) >= started]
    if not container and not args.no_docker_logs:
        print("(no container lines found - are the containers named s7875_notice_*?)")
    for name, corr in (("CREATE_NOTICE", create_corr), ("GET_NOTICE", get_corr)):
        lines = [ln for ln in container + logutil.CAPTURE if corr in ln and parse_ts(ln)]
        merged[name] = sorted(lines, key=parse_ts)
        print(f"\n### {name}  correlation_id={corr}")
        for ln in merged[name]:
            print(ln)

    step(10, "retrieved notice and correlation_id check")
    print(json.dumps(get_resp, indent=2))
    checks = {
        "create_success": create_resp.get("success") is True,
        "create_correlation_id_preserved": create_resp.get("correlation_id") == create_corr,
        "get_success": get_resp.get("success") is True,
        "get_correlation_id_preserved": get_resp.get("correlation_id") == get_corr,
        "retrieved_notice_matches_created": bool(get_resp.get("notice"))
        and get_resp["notice"].get(ID_FIELD) == notice_id
        and all(get_resp["notice"].get(k) == v for k, v in SAMPLE_NOTICE.items()),
        "all_error_responses_keep_correlation_id": all(e["correlation_id_preserved"]
                                                       for e in errors),
    }
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    RAW.mkdir(parents=True, exist_ok=True)
    out = {"run_at": now(), "via": args.via, "request_topic": REQUEST_TOPIC,
           "response_topic": RESPONSE_TOPIC,
           "create": {"correlation_id": create_corr,
                      "request": build_request(create_corr, OP_CREATE, SAMPLE_NOTICE),
                      "response": create_resp},
           "get": {"correlation_id": get_corr,
                   "request": build_request(get_corr, OP_GET, {ID_FIELD: notice_id}),
                   "response": get_resp},
           "error_cases": errors, "merged_log": merged, "checks": checks}
    path = RAW / f"part1_demo_{args.via}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nsaved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
