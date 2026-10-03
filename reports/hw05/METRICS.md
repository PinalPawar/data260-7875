# METRICS.md - HW5

Pinal Pawar, SID4 7875. All numbers below come from runs on my own machine
(MacBook Air, Apple M2, 16 GB RAM); the console output is in `RUN_LOG.txt` and
the raw records are in `raw/`.

## Part 3 - fault injection (VERIFY_SEED = 267875)

Retry policy: 3 attempts, 2.0 s timeout per attempt, exponential backoff
starting at 0.1 s and doubling, capped at 1.0 s. 50 calls per failure rate,
150 calls in total (`raw/fault_injection_calls.csv`).

| Injected failure rate | Success rate | Mean latency (ms) | p99 latency (ms) |
|---|---|---|---|
| 0% | 100% | 2.7 | 7.6 |
| 20% | 96% | 21.3 | 308.5 |
| 50% | 90% | 94.9 | 317.9 |

Attempts used: 50, 57 and 84 for the three rates. Re-seeding with the same
VERIFY_SEED reproduced the same fail/succeed sequence at every rate.

## Part 4 / Part 5 - offline tests

`python3 tests/test_hw05_tools.py` -> 10/10 tests passed (8 from Part 4, plus
the safety-rule test and the MockModel max_steps test added in Part 5).

## Part 5 - agent scenarios (local model qwen3:1.7b via Ollama)

Source: `raw/agent_runs.jsonl` and `raw/agent_metrics.json`.
Model settings: thinking disabled, temperature 0, seed 7875.

| Scenario | max_steps | Steps | Tool calls | Stop reason |
|---|---|---|---|---|
| S1 search (frozen spinach) | 5 | 2 | 1 | completed |
| S2 detail (RCL-2026-00003) | 5 | 2 | 1 | completed |
| S3 aggregate (largest category) | 5 | 2 | 1 | completed |
| S4 question containing an e-mail | 5 | 1 | 0 | completed |
| S5 two-step task with a 1-step limit | 1 | 1 | 1 | max_steps |
| S6 explicit tool call with an e-mail | 5 | 1 | 1 | safety_block |

No hosted-model comparison was run.

## Self-check

`python3 scripts/verify_hw05.py` -> 17/17 checks passed (`verification.json`).
