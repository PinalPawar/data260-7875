"""HW9 Part 2: semantic response cache at the ingress of the HW8 agent pipeline.

    query --embed--> Redis vector index (KNN 1, cosine)
        similarity >= threshold  -> HIT : return stored final answer, is_cached=True
        otherwise                -> MISS: run HW8 pipeline, store query + embedding + answer
                                          + data_version, return is_cached=False

Redis layout (all keys start with PREFIX s7875):
    index  s7875:semcache:idx       FT index, HNSW, FLOAT32, DIM 384, COSINE
    entry  s7875:semcache:entry:<id> HASH {query, answer, embedding, notice_id, data_version,
                                           status, created_at}

Run:
    python hw9/semantic_cache.py --demo                 # Part 2: the queries in part2_queries.yaml
    python hw9/semantic_cache.py --ask "your question"  # one question
"""

import argparse
import json
import logging
import os
import sys
import time
import uuid

import numpy as np

from common import PREFIX, banner, get_redis

log = logging.getLogger("hw9.semcache")
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "reports", "hw09", "raw")

EMBED_MODEL = "all-MiniLM-L6-v2"  # SentenceTransformers, 384-dim
DIM = 384
_model = None


def embed(text: str) -> np.ndarray:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    v = _model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(v, dtype=np.float32)


class SemanticCache:
    def __init__(self, threshold: float = 0.85, check_version: bool = False,
                 namespace: str = "semcache", notice_filter: bool = False):
        self.r = get_redis()
        self.threshold = threshold
        self.check_version = check_version  # Part 3.5 invalidation switch
        # Part 3 fix: only compare against cached entries about the SAME notice (Redis TAG
        # pre-filter inside the KNN query). Embeddings ignore batch numbers, so without this
        # "batch 4624" matches "batch 4619" at 0.997.
        self.notice_filter = notice_filter
        self.index = f"{PREFIX}:{namespace}:idx"
        self.key_prefix = f"{PREFIX}:{namespace}:entry:"
        self.ensure_index()

    # ---------------- Redis vector index -------------------------------------------------
    def ensure_index(self):
        try:
            self.r.execute_command("FT.INFO", self.index)
        except Exception:
            self.r.execute_command(
                "FT.CREATE", self.index, "ON", "HASH", "PREFIX", "1", self.key_prefix,
                "SCHEMA", "query", "TEXT", "answer", "TEXT", "notice_id", "TAG",
                "data_version", "TAG", "status", "TAG",
                "embedding", "VECTOR", "HNSW", "6", "TYPE", "FLOAT32", "DIM", str(DIM),
                "DISTANCE_METRIC", "COSINE")
            log.info("created vector index %s", self.index)

    def clear(self):
        keys = list(self.r.scan_iter(f"{self.key_prefix}*"))
        if keys:
            self.r.delete(*keys)
        return len(keys)

    def nearest(self, vec: np.ndarray, notice_id=None) -> tuple[dict | None, float]:
        """Closest cached entry and its cosine similarity (1 - cosine distance).
        notice_id given -> search only entries tagged with that notice (hybrid TAG + KNN)."""
        pre = f"(@notice_id:{{{notice_id}}})" if notice_id is not None else "*"
        res = self.r.execute_command(
            "FT.SEARCH", self.index, f"{pre}=>[KNN 1 @embedding $vec AS dist]",
            "PARAMS", "2", "vec", vec.tobytes(), "SORTBY", "dist",
            "RETURN", "7", "query", "answer", "notice_id", "data_version", "status",
            "created_at", "dist", "DIALECT", "2")
        if isinstance(res, dict):  # RESP3 (redis-py 8 default): {"total_results", "results"}
            rows = res.get("results") or []
            if not rows:
                return None, 0.0
            entry = dict(rows[0].get("extra_attributes") or {})
            entry["key"] = rows[0].get("id")
        else:  # RESP2: [total, key, [field, value, ...]]
            if not res or res[0] == 0:
                return None, 0.0
            key, fields = res[1], res[2]
            entry = dict(zip(fields[::2], fields[1::2]))
            entry["key"] = key
        return entry, 1.0 - float(entry["dist"])

    def store(self, query, vec, answer, notice_id, version, status):
        key = f"{self.key_prefix}{uuid.uuid4().hex[:12]}"
        self.r.hset(key, mapping={
            "query": query, "answer": answer, "embedding": vec.tobytes(),
            "notice_id": str(notice_id or "none"), "data_version": version,
            "status": status or "", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        return key

    # ---------------- ingress ------------------------------------------------------------
    def ask(self, query: str, pipeline=None) -> dict:
        """Answer a query through the cache. `pipeline(query)` overrides the HW8 call (tests)."""
        from notice_context import context_line, data_version, find_notice, get_notice

        t0 = time.perf_counter()
        vec = embed(query)
        notice = find_notice(query) if self.notice_filter else None
        nid = (notice["id"] if notice else "none") if self.notice_filter else None
        entry, sim = self.nearest(vec, nid)
        lookup_ms = (time.perf_counter() - t0) * 1000
        stale = False

        if entry is not None and sim >= self.threshold:
            if self.check_version and entry.get("notice_id") not in (None, "", "none"):
                current = data_version(get_notice(entry["notice_id"]))
                if current != entry.get("data_version"):
                    stale = True
                    log.info("CACHE STALE sim=%.3f cached_version=%s current_version=%s -> "
                             "invalidate %s", sim, entry.get("data_version"), current,
                             entry["key"])
                    self.r.delete(entry["key"])
            if not stale:
                latency = (time.perf_counter() - t0) * 1000
                log.info("CACHE HIT  sim=%.3f latency=%.1fms matched=%r", sim, latency,
                         entry["query"])
                return {"query": query, "answer": entry["answer"], "is_cached": True,
                        "similarity": round(sim, 4), "latency_ms": round(latency, 1),
                        "lookup_ms": round(lookup_ms, 1), "matched_query": entry["query"],
                        "notice_id": (entry.get("notice_id")
                                      if entry.get("notice_id") not in ("", "none") else None),
                        "data_version": entry.get("data_version"), "status": entry.get("status")}

        # MISS (or stale): run the normal HW8 agent path
        log.info("CACHE MISS best_sim=%.3f%s -> running HW8 pipeline", sim,
                 " (stale entry invalidated)" if stale else "")
        if not self.notice_filter:
            notice = find_notice(query)
        agent_q = query + (context_line(notice) if notice else "")
        if pipeline is None:
            from pipeline import run_pipeline
            res = run_pipeline(agent_q)
        else:
            res = pipeline(agent_q)
        version = data_version(notice)
        if res.get("status") == "approved":  # never cache an answer the Reviewer rejected
            self.store(query, vec, res["answer"], notice and notice["id"], version,
                       res["status"])
        latency = (time.perf_counter() - t0) * 1000
        log.info("CACHE MISS done latency=%.1fms status=%s", latency, res.get("status"))
        return {"query": query, "answer": res["answer"], "is_cached": False,
                "similarity": round(sim, 4), "latency_ms": round(latency, 1),
                "lookup_ms": round(lookup_ms, 1), "matched_query": entry and entry["query"],
                "notice_id": notice and notice["id"], "data_version": version,
                "status": res.get("status"), "stale_invalidated": stale}


def quiet_libs():
    """Hide model-download / HTTP / Kafka chatter so the cache log lines stay readable."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    for name in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers",
                 "transformers", "urllib3", "aiokafka"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
    except Exception:
        pass


def summarize(rows):
    hits = [r for r in rows if r["is_cached"]]
    miss = [r for r in rows if not r["is_cached"]]

    def avg(xs):
        return round(sum(x["latency_ms"] for x in xs) / len(xs), 1) if xs else None

    return {"queries": len(rows), "hits": len(hits), "misses": len(miss),
            "hit_rate_pct": round(100 * len(hits) / len(rows), 1) if rows else 0,
            "avg_latency_cached_ms": avg(hits), "avg_latency_uncached_ms": avg(miss)}


def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    quiet_libs()
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--ask")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--keep", action="store_true", help="do not clear the cache first")
    ap.add_argument("--notice-filter", action="store_true",
                    help="Part 3 fix: KNN only over entries for the same notice")
    args = ap.parse_args()
    print(banner(f"Part 2 - semantic cache (threshold {args.threshold})"))
    cache = SemanticCache(threshold=args.threshold, notice_filter=args.notice_filter)

    if args.ask:
        print(json.dumps(cache.ask(args.ask), indent=2))
        return

    import yaml
    queries = yaml.safe_load(open(os.path.join(HERE, "part2_queries.yaml")))["queries"]
    if not args.keep:
        print(f"cleared {cache.clear()} old cache entries")
    rows = []
    for i, q in enumerate(queries, 1):
        print(f"\n--- Q{i} [{q['type']}] {q['text']}")
        r = cache.ask(q["text"])
        r["type"] = q["type"]
        rows.append(r)
        print(f"    is_cached={r['is_cached']}  similarity={r['similarity']:.3f}  "
              f"latency={r['latency_ms']:.1f} ms  status={r['status']}")
        print(f"    answer: {r['answer'][:160]}{'...' if len(r['answer']) > 160 else ''}")

    print("\n===== Part 2 results =====")
    print(f"{'#':>2} {'type':<10} {'cached':<6} {'sim':>6} {'latency ms':>11}  query")
    for i, r in enumerate(rows, 1):
        print(f"{i:>2} {r['type']:<10} {str(r['is_cached']):<6} {r['similarity']:>6.3f} "
              f"{r['latency_ms']:>11.1f}  {r['query'][:60]}")
    s = summarize(rows)
    print(f"\nHit rate: {s['hits']}/{s['queries']} = {s['hit_rate_pct']}%")
    print(f"Avg latency cached: {s['avg_latency_cached_ms']} ms | "
          f"not cached: {s['avg_latency_uncached_ms']} ms")
    os.makedirs(RAW, exist_ok=True)
    out = os.path.join(RAW, "part2_run.json")
    json.dump({"threshold": args.threshold, "summary": s, "rows": rows}, open(out, "w"),
              indent=2)
    print(f"saved {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
