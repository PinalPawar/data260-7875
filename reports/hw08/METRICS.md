# HW8 - METRICS.md (Pinal Pawar, SID4 7875)

All numbers below come from real runs on 2026-10-27 (MacBook Air, Apple M2, 16 GB RAM;
Docker Desktop; `apache/kafka:3.9.2` in KRaft mode; agents on `qwen3:1.7b` via Ollama, temperature 0,
seed 7875, thinking off). Console output with timestamps: `RUN_LOG.txt`. Machine-readable data:
`raw/`. Self-check: `verification.json` (30/30 checks passed).

| Config | Value |
|---|---|
| SID4 / PREFIX / PORT_BASE | 7875 / `s7875` / 8675 |
| SEED / VERIFY_SEED / DOMAIN_ID | 7875 / 267875 / 3 (Grocery supply and recall notices) |
| Primary entity | Notice (`CREATE_NOTICE`, `GET_NOTICE`, `notice_id`) |

## Topics

| Topic | Partitions | Role |
|---|---|---|
| `s7875_notice_requests` | 1 | client / FastAPI -> worker |
| `s7875_notice_responses` | 1 | worker -> client / FastAPI |
| `s7875_inbox` | 1 | you -> Planner |
| `s7875_tasks` | 2 | Planner -> Writer |
| `s7875_drafts` | 1 | Writer -> Reviewer |
| `s7875_final` | 1 | Reviewer -> you |
| `s7875_dead_letter` | 1 | any agent, after 3 failed attempts |

## Part 1 - request/response over Kafka

Source: `raw/part1_demo_kafka.json` (11:46:53), `raw/part1_demo_api.json` (11:50:07).

| Run | Operation | Lines in merged sequence | First line -> last line | Result | correlation_id kept |
|---|---|---|---|---|---|
| Kafka client | CREATE_NOTICE | 5 (SEND, RECEIVE, PROCESS, REPLY, CLIENT-RESPONSE) | 33 ms | success, new `notice_id` | yes |
| Kafka client | GET_NOTICE | 5 | 7 ms | success, notice equals the one created | yes |
| via FastAPI | CREATE_NOTICE | 9 (adds HTTP-POST, HTTP-REQUEST, HTTP-RESPONSE, HTTP-200) | 32 ms | success | yes |
| via FastAPI | GET_NOTICE | 9 | 28 ms | success | yes |

Error cases (each run): unknown operation -> `Unknown operation`; missing `email` ->
`Missing required field(s): email`; bad `notice_code` -> pattern error; unknown `notice_id` ->
`Notice not found`. All four returned `success: false` with the original correlation_id.
The demo's 6 checks passed in both runs.

## Part 2 - three-agent pipeline (qwen3:1.7b)

Source: `raw/part2_journey_*.json`, `raw/part2_*planner/writer/reviewer.log`.

Model time = PROCESS-START to PROCESS-DONE in each agent's log; total = question sent to final
received by `send_question.py`.

| Run | Question sent | Planner | Writer | Reviewer | Total | Tasks partition | Status | correlation_id kept on all 4 topics |
|---|---|---|---|---|---|---|---|---|
| 1 (`d5f6857e`) | 11:57:43.58 | 8.5 s (4 steps) | 5.7 s (60 words) | 3.1 s | 17.4 s | 0 | approved, **but the answer was unsafe** (see AI_USE.md) | yes |
| 2 (`b14cad9d`), after the safety fix | 12:07:41.73 | 5.9 s (1 step) | 5.9 s (59 words) | 4.1 s | 16.2 s | 1 | approved, correct advice | yes |

Each agent logged RECEIVE -> PROCESS-START -> PROCESS-DONE -> SEND -> COMMIT for the same id.

## Part 3 - failure table

Source: `raw/part3_failure_table.json` / `.md`, `raw/part3_<test>.json`, per-Writer logs
`raw/part3_<test>_<phase>_<writer>.log`. The failure tests use the offline model stand-in
(`HW8_FAKE_LLM=1`) for the Writer, because they measure Kafka delivery, not model output.

| Failure scenario | Before fix | After fix |
|---|---|---|
| Duplicate delivery (same task replayed, same correlation_id) | `IDEMPOTENCY=0`: 2 receives, **2 model calls, 2 drafts** (extra side effect) | `IDEMPOTENCY=1`: 2 receives, **1 model call, 1 draft**, 1 `DUPLICATE-SKIP` |
| Consumer killed mid-work (`kill -9` during an 8 s task) | `COMMIT_MODE=before`: offset committed on receipt (committed 6 > message offset 5); restarted Writer never saw it -> **message lost**, 0 drafts | `COMMIT_MODE=after`: committed offset stayed 1 = message offset; restarted Writer got it again -> **completed**, 1 draft, committed 2 |
| Poison message (task with `plan: null`, a good task behind it on p0) | `MAX_RETRIES=0`: Writer **crashed 3 times on offset 6**; committed offset stuck at 6; good message **never processed** | `MAX_RETRIES=3`: 3 attempts (0.5 s, 1 s backoff) -> 1 record on `s7875_dead_letter` (error, attempts, source offset, original); offset committed; good message **processed** |
| Two partitions / two consumers (20 messages, VERIFY_SEED 267875) | no key (round-robin over p0/p1): **2 of 4 notices out of order**, 2 inversions | key = `notice_code`: **0 of 4 out of order**; every notice on one partition and one Writer |

### Ordering detail (`raw/part3_ordering_unkeyed.csv`, `raw/part3_ordering_keyed.csv`)

20 status updates for 4 notices, generated from `random.Random(267875)`; each notice's updates
numbered seq 1..n. Writer-1 owned p0, Writer-2 owned p1 in both runs.

| Notice | Updates | No key: processed seq order | Partitions | Key = notice_code: processed seq order | Partition |
|---|---|---|---|---|---|
| RCL-2026-59801 | 8 | **2, 1**, 3, 4, 5, 6, 7, 8 (out of order) | 0, 1 | 1, 2, 3, 4, 5, 6, 7, 8 | 1 |
| RCL-2026-66434 | 5 | 1, 2, 3, 4, 5 (in order by luck) | 0, 1 | 1, 2, 3, 4, 5 | 1 |
| RCL-2026-74265 | 1 | 1 | 0 | 1 | 1 |
| RCL-2026-61335 | 6 | 1, 2, **4, 3**, 5, 6 (out of order) | 0, 1 | 1, 2, 3, 4, 5, 6 | 0 |

## Self-check

`verification.json`: 30/30 checks passed (config, topics, containers, Part 1 over Kafka and via
FastAPI, 6 error cases, duplicate CREATE, Part 2 journey with qwen3:1.7b, duplicate skip,
poison -> dead letter, saved Part 3 results, 57 offline tests).
