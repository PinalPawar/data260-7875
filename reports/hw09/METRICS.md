# HW9 - METRICS.md (Pinal Pawar, SID4 7875)

All numbers come from real runs on 2026-11-06 to 2026-11-07. Setup:
- MacBook Air (Apple M2, 16 GB), conda env `data260`.
- Redis Stack (`redis/redis-stack-server`, container `s7875-redis`) and MySQL `s7875_rel`.
- HW8 Kafka pipeline: Planner and Writer on qwen3:1.7b, Reviewer on qwen3:8b.
- Embeddings: `all-MiniLM-L6-v2`.

Console output: `RUN_LOG.txt`. Machine-readable data: `raw/`. Self-check: `verification.json` (37/37 checks passed).

| Config | Value |
|---|---|
| SID4 / PREFIX / PORT_BASE | 7875 / `s7875` / 8675 |
| SEED / VERIFY_SEED / DOMAIN_ID | 7875 / 267875 / 3 (Grocery supply and recall notices) |
| Primary entity | Notice (`notices` table) |
| Redis keys | `s7875:views:notice:{id}`, `s7875:semcache:*`, `s7875:sweep:*`, `s7875:stale:*` |

## Part 1 - view counter (`hw9/view_counter.py`)

| Metric | Value |
|---|---|
| Accesses | 25 |
| Synced to MySQL at | 10, 20 |
| Final Redis / MySQL | 25 / 20 |
| Median latency per view (50 trials) | Redis INCR 0.587 ms, MySQL UPDATE 1.043 ms |

## Part 2 - semantic cache, threshold 0.85 (`raw/part2_run.json`)

| Type | Queries | Hits | Similarity of hits |
|---|---|---|---|
| new | 5 | 0 | - |
| exact | 3 | 3 | 1.000 |
| paraphrase | 4 | 2 | 0.918, 0.940 (misses 0.849, 0.572) |

- Hit rate: 5/12 = 41.7%.
- Average latency: cached 599.3 ms vs not cached 39,203.2 ms.
- Q10 and Q12 were rejected by the HW8 rule check, so they were not cached.

## Part 3 - threshold sweep (`raw/part3_sweep.json`, `raw/part3_state.json`)

- Labels: `hw9/cache_cases.yaml`, sha256 `5f3213c0...`, frozen in commit `c75ddd9` (2026-11-07
  00:19:21).
- Cost model: C_miss = $0.02, C_false = $5.00. False-hit rate = false hits / hits.
- Median pipeline latency: 38.9 s.

A) Cosine threshold only

| Threshold | Hit rate | False-hit rate | Mean latency (ms) | Total cost |
|---|---|---|---|---|
| 0.75 | 75.0% | 33.3% (10) | 7,112.4 | $50.20 |
| 0.80 | 75.0% | 33.3% (10) | 7,112.4 | $50.20 |
| 0.85 | 67.5% | 37.0% (10) | 10,205.4 | $50.26 |
| 0.90 | 67.5% | 37.0% (10) | 10,205.4 | $50.26 |
| 0.95 | 57.5% | 39.1% (9) | 14,424.2 | $45.34 |

B) Threshold + same-notice filter (shipped: 0.80)

| Threshold | Hit rate | False-hit rate | Mean latency (ms) | Total cost |
|---|---|---|---|---|
| 0.75 | 50.0% | 0.0% | 17,478.9 | $0.40 |
| 0.80 | 50.0% | 0.0% | 17,478.9 | $0.40 |
| 0.85 | 42.5% | 0.0% | 20,571.9 | $0.46 |
| 0.90 | 42.5% | 0.0% | 20,571.9 | $0.46 |
| 0.95 | 35.0% | 0.0% | 23,839.1 | $0.52 |

Similarity ranges by category:

| Category | Similarity range |
|---|---|
| exact | 1.000 |
| paraphrase | 0.823-0.969 |
| similar_different | 0.910-0.997 |
| unrelated | 0.092-0.566 |

Stale-answer demo (`hw9/stale_demo.py`), notice 4609:
1. Cached 3671 units (`912788eec9`).
2. Updated the row to 5200 (`053bac3182`).
3. Without the version check: stale HIT returning 3671 (586 ms).
4. With the version check: CACHE STALE, invalidate, re-answer with 5200 (40.2 s).
5. Fresh HIT returning 5200 (636 ms).

## Part 4 - two-agent system (`hw9/part4/`, `raw/part4_*.json`)

- Training: 12 questions; first-attempt failures MISSING_ACTION x2 and MISSING_LOT x1.
  `lesson_001` was created after the 2nd MISSING_ACTION.
- Validation of `lesson_001`: first-attempt failures 7 -> 0, final failures 4 -> 0, no
  regressions, unrelated questions OK. Decision: KEEP.

Test set (12 held-out questions):

| Variant | Correct | Incorrect | Avg attempts | Avg latency (s) |
|---|---|---|---|---|
| Baseline | 3 | 9 | 1.00 | 3.41 |
| Evaluator Repair | 6 | 6 | 1.75 | 6.19 |
| Lesson Memory | 12 | 0 | 1.00 | 3.24 |
| Validated Improvement | 12 | 0 | 1.00 | 2.63 |

## Self-check

`python scripts/verify_hw09.py` writes `verification.json`: **37/37 checks passed** (2026-11-08), including the look-alike batch becoming a miss with the notice filter and the changed row being invalidated by the version check.
