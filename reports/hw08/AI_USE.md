# HW8 - AI_USE.md (Pinal Pawar, SID4 7875)

## 1. What I used an AI assistant for, and what I did myself

I used Claude to read the assignment and the two class demos (`DATA236_DEMO8`, `multi-agent-demo`)
with me, and to understand worker, FastAPI wrapper, Kafka client,
shared agent loop with idempotency, commit modes, bounded retries and dead-letter,
`homework_demo.py`, the three agents and `send_question.py`, `docker-compose.kafka.yml`, the
topic-creation script, the Part 3 failure harness, `verify_hw08.py` and the offline tests. It also
drafted the report around my screenshots.

Claude could not run Kafka itself (no Docker in its workspace), so I tested the code
against an in-memory stand-in broker. Everything reported here I ran myself on a MacBook Air
(Apple M2, 16 GB) with Docker Desktop, real Kafka 3.9.2 and qwen3:1.7b in Ollama: the containers,
topic creation, both demo runs, both Part 2 runs in four terminals, the four failure tests and
the self-check. I took every screenshot and read the outputs before accepting them. The
decisions about what to keep, re-run or fix were mine (for example re-running Part 2 after the
safety fix below, keeping run 1 as evidence, and keeping `notice` in the topic names).

## 2. One AI-produced output that was wrong/unsuitable

The Planner/Writer/Reviewer prompts the assistant first wrote had no food-safety rules. In my
first real Part 2 run (`raw/part2_journey_d5f6857e.json`), qwen3:1.7b planned a step
"Determine if the spinach you ate is still safe to consume", wrote **"If the spinach you ate is
from the same batch and within the expiration window, it may still be safe"**, and the Reviewer
**approved** it. The Kafka side was perfect (same correlation_id on all four topics, every offset
committed), but the answer was wrong: a recalled product is never safe to eat, whatever its date.

A smaller one: the first topic-creation script stopped after describing one topic, because
`set -o pipefail` plus `| head -1` turned the pipe closing early into an error.

## 3. How I detected the problem

By reading the final JSON in my run-1 screenshot rather than only checking that `status` was
present. The structural checks (status, answer, correlation_id, trace) all passed, which is
exactly why they could not catch it: they test the pipeline, not whether the advice is right. The
topic-script bug showed in my screenshot: only `s7875_notice_requests` appeared under
`--describe`.

## 4. What I changed and why it works now

- All three agents now get explicit recall-safety rules (never eat a recalled product, throw it
  away or return it, clean surfaces, watch for symptoms and call a doctor, sooner for high-risk
  people).
- The Reviewer runs a **rule check before the model**: a draft with phrases like "may still be
  safe" or "safe to eat" is rejected outright, so a small model's review is no longer the only
  safeguard. Negated forms ("it is **not** safe to eat") are allowed.
- Offline tests now include the exact sentence from run 1 and check it is rejected
  (`tests/test_hw08_kafka.py`, 57/57 pass).

Re-run (run 2, `raw/part2_journey_b14cad9d.json`): "Stop using the recalled bagged organic baby
spinach and throw it away or return it to the store ... Do not eat the product, regardless of its
appearance or smell", approved, 16.2 s end to end. The topic script now describes all seven
topics and `s7875_tasks` shows `PartitionCount: 2`.
