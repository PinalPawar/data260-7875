# HW9 - AI_USE.md (Pinal Pawar, SID4 7875)

## 1. What I used an AI assistant for, and what I did myself

I used Claude to read the HW9 assignment and the two class demos in `Homework_export_7.zip`
(`demo.py`, SQLite + Redis caching; `caching_agents.py`, exact and semantic caching) with me, and
to explain the concepts as we went: Redis `INCR` counters with batched database syncing, sentence
embeddings and cosine similarity, Redis HNSW vector indexes, threshold trade-offs, cache
invalidation, and evaluator-repair loops with validated lessons. It explained (view counter, semantic cache in front of my HW8 Kafka pipeline, threshold sweep,
stale-answer demo, Part 4 agents and runner), proposed the labeled cases and the Part 4
question sets from my own `s7875_rel` notices, and drafted the
report around my screenshots.

Claude could not reach my Redis, MySQL, Kafka or Ollama (they run on my Mac), so it tested the code
against in-memory and SQLite stand-ins. Everything reported here I ran
myself on a MacBook Air (Apple M2, 16 GB) in the `data260` conda env: Redis Stack in Docker,
MySQL `s7875_rel`, the HW8 Kafka agents and qwen3 in Ollama. I took every screenshot and read the
outputs before accepting them. The decisions were mine: moving the HW8 Reviewer to qwen3:8b
after reading its rejection reasons, freezing `cache_cases.yaml` with a commit before the sweep,
and shipping threshold 0.80 with the same-notice filter.

## 2. One AI-produced output that was wrong/unsuitable

The first semantic cache the assistant matched queries on cosine similarity alone. That
is what the class demo does, and it passed the Part 2 test (exact duplicates hit at 1.000 and a
paraphrase hit at 0.918). On my domain, though, it is unsafe. In the Part 3 sweep the ten "same
question, different batch" cases scored 0.910-0.997, higher than the real paraphrases. For
example, "Is the Deli Turkey batch **4624** recall because of Listeria?" matched the cached
answer for batch **4619** at 0.997 and would have told the customer "Listeria" for what is
actually an undeclared-allergen recall. Every threshold from 0.75 to 0.90 had 10 false hits, and
0.95 still had 9.

Smaller ones:
- The first `nearest()` parsed FT.SEARCH as a RESP2 list and crashed (`KeyError: 0`) with
  redis-py 8, which returns RESP3 dicts.
- `common.py` first hard-coded the MySQL password instead of reading my `.env`.
- The first Part 2 run cached almost nothing, because my HW8 qwen3:1.7b Reviewer rejected 4 of 9
  correct answers with self-contradicting reasons.

## 3. How I detected the problem

The labeled sweep caught it, not the Part 2 demo. Because `cache_cases.yaml` contains look-alike
questions with different correct answers (and was committed before the sweep, so they could not
be relabeled afterwards), the per-case similarity list showed the D-cases above the paraphrases,
and the false-hit column listed D1-D10 at every threshold. The crash and the password error
showed up in my terminal. The Reviewer problem showed when I read the `review` field of every
message on `s7875_final` rather than only the `status`.

## 4. What I changed and why it works now

- **Hybrid search.** The cache first resolves which notice a question is about (notice code,
  batch number or product), then runs the KNN only over cached entries with the same
  `notice_id` TAG (`(@notice_id:{4624})=>[KNN 1 @embedding $vec]`). Rescored on the same
  measurements: 0 false hits at every threshold. At 0.80 all 20 expected hits are served and the
  total cost falls from $50.20 to $0.40.
- **Data-version check.** On every hit the cache re-reads the notice row and compares a hash of it
  with the stored `data_version`. The stale-answer demo shows the old answer (3671 units) served
  without the check, and invalidation plus a fresh answer (5200) with it.
- **Other fixes.** The RESP3 and RESP2 result formats are both parsed. `common.py` reads the
  repo `.env`. The Reviewer runs on qwen3:8b (`HW8_MODEL=qwen3:8b`), and only approved answers
  are cached.
- **Self-check.** `scripts/verify_hw09.py` re-checks each fix (look-alike batch -> miss with the
  filter, changed row -> invalidated) and saves the results to `verification.json`.
