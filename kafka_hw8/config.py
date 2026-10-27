"""HW8 configuration: Section 0 values and every Kafka topic name in one place.

All topic names carry PREFIX (s7875). The bootstrap address depends on where the process runs:
    - on the Mac (agents, homework_demo.py, scripts): localhost:9092 (the default)
    - inside docker compose (worker, API):            kafka:19092 (set by docker-compose.kafka.yml)
"""

import os

STUDENT_NAME = "Pinal Pawar"
SID4 = 7875
PORT_BASE = 8000 + (SID4 % 900)  # 8675
PREFIX = f"s{SID4}"  # s7875
SEED = SID4  # 7875
VERIFY_SEED = 260000 + SID4  # 267875
DOMAIN_ID = SID4 % 8  # 3 -> Grocery supply and recall notices

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")

# --- Part 1: request/response service for the primary entity (Notice) -------------------
# "Replace ENTITY with the actual entity name": CREATE_ENTITY -> CREATE_NOTICE,
# entity_id -> notice_id, <PREFIX>_entity_requests -> s7875_notice_requests.
ENTITY = "notice"
REQUEST_TOPIC = f"{PREFIX}_{ENTITY}_requests"  # s7875_notice_requests
RESPONSE_TOPIC = f"{PREFIX}_{ENTITY}_responses"  # s7875_notice_responses
OP_CREATE = "CREATE_NOTICE"
OP_GET = "GET_NOTICE"
ID_FIELD = "notice_id"
WORKER_GROUP = f"{PREFIX}_notice_worker"

# --- Part 2: three-agent pipeline --------------------------------------------------------
INBOX_TOPIC = f"{PREFIX}_inbox"
TASKS_TOPIC = f"{PREFIX}_tasks"  # 2 partitions (Part 3 ordering test)
DRAFTS_TOPIC = f"{PREFIX}_drafts"
FINAL_TOPIC = f"{PREFIX}_final"
PLANNER_GROUP = f"{PREFIX}_planners"
WRITER_GROUP = f"{PREFIX}_writers"
REVIEWER_GROUP = f"{PREFIX}_reviewers"

# --- Part 3: failure handling -------------------------------------------------------------
DEAD_LETTER_TOPIC = f"{PREFIX}_dead_letter"

TOPIC_PARTITIONS = {
    REQUEST_TOPIC: 1,
    RESPONSE_TOPIC: 1,
    INBOX_TOPIC: 1,
    TASKS_TOPIC: 2,
    DRAFTS_TOPIC: 1,
    FINAL_TOPIC: 1,
    DEAD_LETTER_TOPIC: 1,
}

# Local model for the agents (same one as HW7 Parts 2-3).
AGENT_MODEL = os.getenv("HW8_MODEL", "qwen3:1.7b")


def banner(role: str) -> str:
    """First line every HW8 process prints, so the name shows in each terminal screenshot."""
    return (
        f"===== {STUDENT_NAME} | SID4 {SID4} | PREFIX {PREFIX} | PORT_BASE {PORT_BASE} "
        f"| {role} ====="
    )
