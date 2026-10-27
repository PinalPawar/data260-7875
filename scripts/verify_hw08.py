"""
HW8 self-check / smoke test. Writes reports/hw08/verification.json.

A smoke test: start the system and check that the basic things work, not every edge case.
Every check tests behaviour (success flags, ids echoed, messages arriving on the right topic,
counts), never model wording. It never modifies application code: the agents it starts use
new consumer groups (offsets set to "now") and a temporary state folder that is deleted at the
end; the only file it writes is reports/hw08/verification.json.

Before running (repo root, conda env data260):
    1. docker compose -f docker-compose.kafka.yml up -d --build
    2. bash scripts/hw08_create_topics.sh
    3. Ollama running with qwen3:1.7b   (or pass --fake-model to use the offline stand-in)
    4. python scripts/verify_hw08.py          (or: make verify-hw08)

A check that cannot run (Kafka down, container missing) is a FAIL, not a crash.
Set HW8_COMMIT=<hash> to record the commit when the folder is not a git checkout.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from kafka_hw8 import config as C  # noqa: E402
from kafka_hw8.kafka_util import (  # noqa: E402
    baseline_group,
    end_offsets,
    list_topics,
    partitions_of,
    read_from,
    send_json,
)
from kafka_hw8.rpc_client import KafkaRPCClient  # noqa: E402

HW = ROOT / "reports" / "hw08"
API = f"http://127.0.0.1:{C.PORT_BASE}"
NOTICE = {
    "product": "Frozen Wild Blueberries 16oz",
    "notice_code": "RCL-2026-26787",
    "units_affected": 1200,
    "manufacturer_id": 2,
    "email": "safety@northfarm-foods.com",
    "description": "Possible hepatitis A contamination in lots B1-B9.",
    "category": "bacterialContamination",
}
checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": str(detail)[:300]})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""),
          flush=True)


async def guarded(name, coro_fn):
    try:
        await coro_fn()
    except Exception as exc:  # smoke test: report, never crash
        check(name, False, f"{type(exc).__name__}: {exc}")


def commit_hash():
    if os.getenv("HW8_COMMIT"):
        return os.environ["HW8_COMMIT"]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


# ------------------------------------------------------------------ config + infra --------
def check_config():
    check("Section 0 values", (C.SID4, C.PORT_BASE, C.PREFIX, C.SEED, C.VERIFY_SEED, C.DOMAIN_ID)
          == (7875, 8675, "s7875", 7875, 267875, 3),
          f"PORT_BASE={C.PORT_BASE} PREFIX={C.PREFIX} VERIFY_SEED={C.VERIFY_SEED}")
    topics = list(C.TOPIC_PARTITIONS)
    check("every HW8 topic name carries PREFIX", all(t.startswith(f"{C.PREFIX}_") for t in topics),
          ", ".join(topics))


async def check_kafka():
    found = await list_topics(C.BOOTSTRAP)
    missing = [t for t in C.TOPIC_PARTITIONS if t not in found]
    check("Kafka reachable and all 7 s7875 topics exist", not missing,
          f"missing: {missing}" if missing else C.BOOTSTRAP)
    parts = await partitions_of(C.BOOTSTRAP, C.TASKS_TOPIC)
    check(f"{C.TASKS_TOPIC} has 2 partitions", len(parts) == 2, f"partitions={parts}")


def check_containers():
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        check("docker containers running", False, exc)
        return
    names = {ln.split("\t")[0] for ln in out.splitlines() if ln}
    want = ["s7875_kafka", "s7875_notice_worker", "s7875_notice_api"]
    check("docker ps: Kafka, worker and FastAPI containers up", all(w in names for w in want),
          ", ".join(w + ("" if w in names else " (MISSING)") for w in want))
    logs = subprocess.run(["docker", "logs", "s7875_notice_worker"], capture_output=True,
                          text=True, timeout=15)
    check("worker log shows 'Consumer is ready and listening...'",
          "Consumer is ready and listening..." in logs.stdout + logs.stderr)
    logs = subprocess.run(["docker", "logs", "s7875_notice_api"], capture_output=True,
                          text=True, timeout=15)
    check(f"API log shows server started at http://127.0.0.1:{C.PORT_BASE}",
          f"http://127.0.0.1:{C.PORT_BASE}" in logs.stdout + logs.stderr)


# ------------------------------------------------------------------ Part 1 ---------------
async def check_part1_kafka():
    client = KafkaRPCClient(tag="VERIFY", timeout_s=20)
    await client.start()
    try:
        corr = str(uuid.uuid4())
        created = await client.request(C.OP_CREATE, NOTICE, correlation_id=corr)
        nid = created.get(C.ID_FIELD)
        check("CREATE_NOTICE over Kafka succeeds and returns a UUID notice_id",
              created.get("success") is True and _is_uuid(nid), f"notice_id={nid}")
        check("CREATE_NOTICE response echoes the correlation_id unchanged",
              created.get("correlation_id") == corr)
        corr2 = str(uuid.uuid4())
        got = await client.request(C.OP_GET, {C.ID_FIELD: nid}, correlation_id=corr2)
        notice = got.get("notice") or {}
        check("GET_NOTICE round-trips the created notice (all fields equal)",
              got.get("success") is True and notice.get(C.ID_FIELD) == nid
              and all(notice.get(k) == v for k, v in NOTICE.items()))
        check("GET_NOTICE response echoes its correlation_id", got.get("correlation_id") == corr2)

        again = await client.request(C.OP_CREATE, NOTICE, correlation_id=corr)
        check("replayed CREATE (same correlation_id) creates no second notice",
              again.get(C.ID_FIELD) == nid, f"first={nid} replay={again.get(C.ID_FIELD)}")

        cases = [
            ("unknown operation is rejected", "FLY_TO_MOON", {}, "Unknown operation"),
            ("missing field is rejected", C.OP_CREATE,
             {k: v for k, v in NOTICE.items() if k != "product"}, "product"),
            ("empty field is rejected", C.OP_CREATE, {**NOTICE, "description": "  "},
             "description"),
            ("invalid email is rejected", C.OP_CREATE, {**NOTICE, "email": "not-an-email"},
             "email"),
            ("negative units_affected is rejected", C.OP_CREATE,
             {**NOTICE, "units_affected": -5}, "units_affected"),
            ("unknown notice_id gives 'Notice not found'", C.OP_GET,
             {C.ID_FIELD: str(uuid.uuid4())}, "Notice not found"),
        ]
        for name, op, data, expect in cases:
            c = str(uuid.uuid4())
            r = await client.request(op, data, correlation_id=c)
            check(f"{name} (success=false, clean error, correlation_id kept)",
                  r.get("success") is False and expect in (r.get("error") or "")
                  and r.get("correlation_id") == c, r.get("error"))
    finally:
        await client.stop()


async def check_part1_api():
    h = requests.get(f"{API}/health", timeout=10)
    check(f"FastAPI wrapper answers on PORT_BASE {C.PORT_BASE}", h.ok, h.status_code)
    corr = str(uuid.uuid4())
    r = (await asyncio.to_thread(requests.post, f"{API}/kafka/notices", timeout=30,
                                 json={"correlation_id": corr, "operation": C.OP_CREATE,
                                       "data": NOTICE})).json()
    nid = r.get(C.ID_FIELD)
    g = (await asyncio.to_thread(requests.get, f"{API}/kafka/notices/{nid}", timeout=30)).json()
    check("CREATE -> GET through the FastAPI wrapper (correlation_id kept)",
          r.get("success") and r.get("correlation_id") == corr and g.get("success")
          and g["notice"]["notice_code"] == NOTICE["notice_code"], f"notice_id={nid}")


# ------------------------------------------------------------------ Parts 2-3 ------------
class Agents:
    """planner.py / writer.py / reviewer.py as subprocesses on fresh consumer groups."""

    def __init__(self, fake: bool):
        self.state = Path(tempfile.mkdtemp(prefix="hw08_verify_"))
        self.fake = fake
        self.run = time.strftime("%H%M%S")
        self.procs = {}

    async def start(self):
        for name, topic in (("planner", C.INBOX_TOPIC), ("writer", C.TASKS_TOPIC),
                            ("reviewer", C.DRAFTS_TOPIC)):
            group = f"{C.PREFIX}_verify_{name}_{self.run}"
            await baseline_group(C.BOOTSTRAP, group, topic)
            env = {**os.environ, "HW8_GROUP": group, "HW8_STATE_DIR": str(self.state),
                   "HW8_FAKE_LLM": "1" if self.fake else "0", "PYTHONUNBUFFERED": "1",
                   "AGENT_ID": f"verify-{name}"}
            log = open(self.state / f"{name}.log", "w")
            self.procs[name] = (subprocess.Popen([sys.executable, f"{name}.py"], cwd=ROOT, env=env,
                                                 stdout=log, stderr=subprocess.STDOUT), log)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if all("ASSIGNED partitions [" in (self.state / f"{n}.log").read_text()
                   for n in self.procs):
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("agents did not join their consumer groups within 60 s")

    def log(self, name):
        return (self.state / f"{name}.log").read_text()

    def stop(self):
        for p, fh in self.procs.values():
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
            fh.close()
        shutil.rmtree(self.state, ignore_errors=True)


async def check_pipeline(fake: bool, timeout: float):
    agents = Agents(fake)
    try:
        await agents.start()
        check("planner, writer and reviewer start as separate processes and join Kafka", True,
              ", ".join(f"{n} pid {p.pid}" for n, (p, _) in agents.procs.items()))
        starts = {t: await end_offsets(C.BOOTSTRAP, t)
                  for t in (C.TASKS_TOPIC, C.DRAFTS_TOPIC, C.FINAL_TOPIC, C.DEAD_LETTER_TOPIC)}
        corr = f"verify-{uuid.uuid4()}"
        q = {"correlation_id": corr, "stage": "question", "trace": [],
             "question": "What should I do if I bought cucumbers that were recalled for "
                         "Salmonella?"}
        await send_json(C.BOOTSTRAP, C.INBOX_TOPIC, [(corr, q)])

        def mine(items, c=corr):
            return [i for i in items if i["value"].get("correlation_id") == c]

        finals = mine(await read_from(C.BOOTSTRAP, C.FINAL_TOPIC, starts[C.FINAL_TOPIC], timeout,
                                      until=lambda i: bool(mine(i))))
        final = finals[0]["value"] if finals else {}
        check("question on s7875_inbox reaches s7875_final", bool(finals),
              f"status={final.get('status')}")
        check("final JSON has a status and a non-empty answer",
              final.get("status") in ("approved", "rejected", "needs_human_review")
              and bool((final.get("answer") or "").strip()))
        agents_seen = [t.get("agent") for t in final.get("trace", [])]
        check("correlation_id preserved and trace shows planner -> writer -> reviewer",
              final.get("correlation_id") == corr
              and agents_seen == ["planner", "writer", "reviewer"], agents_seen)
        tasks = mine(await read_from(C.BOOTSTRAP, C.TASKS_TOPIC, starts[C.TASKS_TOPIC], 3))
        drafts = mine(await read_from(C.BOOTSTRAP, C.DRAFTS_TOPIC, starts[C.DRAFTS_TOPIC], 3))
        check("one plan on s7875_tasks and one draft on s7875_drafts for that question",
              len(tasks) == 1 and len(drafts) == 1, f"tasks={len(tasks)} drafts={len(drafts)}")

        # Part 3 smoke: replay the same task -> no second draft
        await send_json(C.BOOTSTRAP, C.TASKS_TOPIC, [(corr, tasks[0]["value"])])
        await asyncio.sleep(4)
        drafts = mine(await read_from(C.BOOTSTRAP, C.DRAFTS_TOPIC, starts[C.DRAFTS_TOPIC], 3))
        check("replayed task (same correlation_id) is skipped: still exactly one draft",
              len(drafts) == 1
              and re.search(rf"DUPLICATE-SKIP\s+corr={re.escape(corr)}", agents.log("writer")),
              f"drafts={len(drafts)}")

        # Part 3 smoke: poison -> bounded retries -> dead letter; a later message still flows
        bad, good = f"verify-poison-{uuid.uuid4()}", f"verify-after-poison-{uuid.uuid4()}"
        good_task = {**tasks[0]["value"], "correlation_id": good}
        await send_json(C.BOOTSTRAP, C.TASKS_TOPIC,
                        [(bad, {"correlation_id": bad, "stage": "plan", "question": "x",
                                "plan": None}), (good, good_task)], partition_for=lambda i: 0)
        dlq = mine(await read_from(C.BOOTSTRAP, C.DEAD_LETTER_TOPIC, starts[C.DEAD_LETTER_TOPIC],
                                   30, until=lambda i: bool(mine(i, bad))), bad)
        check("poison message is retried 3 times then lands on s7875_dead_letter",
              len(dlq) == 1 and dlq[0]["value"].get("attempts") == 3,
              dlq[0]["value"].get("error") if dlq else "not on dead-letter topic")
        later = mine(await read_from(C.BOOTSTRAP, C.DRAFTS_TOPIC, starts[C.DRAFTS_TOPIC], timeout,
                                     until=lambda i: bool(mine(i, good))), good)
        check("message behind the poison one is still processed", len(later) == 1)
    finally:
        agents.stop()


def check_saved_results():
    f = HW / "raw" / "part3_failure_table.json"
    if not f.exists():
        check("Part 3 failure-test results saved (run scripts/run_hw08_part3.py all)", False,
              "reports/hw08/raw/part3_failure_table.json missing")
        return
    res = json.loads(f.read_text())["results"]
    ok = {
        "duplicate": res.get("duplicate", {}).get("after", {}).get("drafts_on_s7875_drafts") == 1,
        "kill": res.get("kill", {}).get("after", {}).get("redelivered_to_writer_B") is True,
        "poison": res.get("poison", {}).get("after", {}).get("good_message_processed") is True,
        "ordering": res.get("ordering", {}).get("keyed", {}).get("analysis", {})
        .get("entities_out_of_order") == 0,
    }
    check("saved Part 3 runs show every fix working (dup, kill, poison, keyed ordering)",
          all(ok.values()), ok)


def check_offline_tests():
    r = subprocess.run([sys.executable, "tests/test_hw08_kafka.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
    check("offline HW8 tests pass (tests/test_hw08_kafka.py)", r.returncode == 0, tail[0])


def _is_uuid(v):
    try:
        uuid.UUID(str(v))
        return True
    except ValueError:
        return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake-model", action="store_true",
                    help="agents use the offline stand-in instead of Ollama")
    ap.add_argument("--timeout", type=float, default=300, help="seconds to wait for a final")
    args = ap.parse_args()
    print(C.banner("verify_hw08.py"), flush=True)

    check_config()
    await guarded("Kafka reachable", check_kafka)
    try:
        check_containers()
    except Exception as exc:
        check("docker containers running", False, exc)
    await guarded("Part 1 over Kafka", check_part1_kafka)
    await guarded("Part 1 through FastAPI", check_part1_api)
    await guarded("Part 2 pipeline", lambda: check_pipeline(args.fake_model, args.timeout))
    check_saved_results()
    check_offline_tests()

    passed = sum(c["passed"] for c in checks)
    out = {
        "homework": 8,
        "sid4": C.SID4,
        "port_base": C.PORT_BASE,
        "prefix": C.PREFIX,
        "domain_id": C.DOMAIN_ID,
        "seed": C.SEED,
        "verify_seed": C.VERIFY_SEED,
        "commit_hash": commit_hash(),
        "model": {
            "agents": "offline stand-in (HW8_FAKE_LLM=1)" if args.fake_model
            else f"{C.AGENT_MODEL} via Ollama, temperature 0, seed {C.SEED}, thinking off",
            "part1_worker": "no model (pure Python)",
        },
        "config": {
            "kafka": "apache/kafka:3.9.2 (KRaft), docker-compose.kafka.yml",
            "bootstrap": C.BOOTSTRAP,
            "topics": C.TOPIC_PARTITIONS,
            "max_retries": 3,
            "commit_mode": "after",
            "idempotency": "on (key = message_id or correlation_id)",
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": f"{passed}/{len(checks)} checks passed",
        "checks": checks,
    }
    HW.mkdir(parents=True, exist_ok=True)
    (HW / "verification.json").write_text(json.dumps(out, indent=2))
    print(f"\n{out['summary']}  ->  reports/hw08/verification.json")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    asyncio.run(main())
