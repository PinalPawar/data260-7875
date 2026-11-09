"""HW9 Part 3.2-3.4: threshold sweep over the 40 labeled cases in cache_cases.yaml.

How it runs (real Redis index, real HW8 pipeline):
  1. Seed: a separate cache namespace (s7875:sweep:*) gets the 10 seed questions, each answered
     once by the HW8 pipeline.
  2. Measure: every one of the 40 cases is embedded and searched against the seeds (KNN-1) ->
     nearest seed, similarity, lookup latency. The cache is read-only here, so every threshold
     sees exactly the same cache contents (no order effects).
  3. Pipeline cost: every case that would MISS at some threshold (similarity < 0.95), plus every
     similar_different case, is sent through the HW8 pipeline once; its real latency is recorded.
  4. Score each threshold: hit = similarity >= t.
       correct hit = expected hit AND matched the labeled seed
       false hit   = any other hit (wrong seed, or a should-miss case)
       latency     = lookup_ms (hit)  or  lookup_ms + pipeline_ms (miss)
       total cost  = misses * C_MISS + false_hits * C_FALSE   (Part 3.4)

Progress is saved to reports/hw09/raw/part3_state.json after every pipeline call, so the run
can be resumed (just rerun). --fresh starts over.

    python hw9/threshold_sweep.py
    python hw9/threshold_sweep.py --c-miss 0.02 --c-false 5.0   # re-score only, no new runs
"""

import argparse
import hashlib
import json
import logging
import os
import statistics
import sys
import time

import yaml

from common import banner
from notice_context import context_line, find_notice
from semantic_cache import SemanticCache, embed, quiet_libs

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "reports", "hw09", "raw")
STATE = os.path.join(RAW, "part3_state.json")
THRESHOLDS = [0.75, 0.80, 0.85, 0.90, 0.95]
log = logging.getLogger("hw9.sweep")


def agent_call(q: str) -> dict:
    from pipeline import run_pipeline
    n = find_notice(q)
    return run_pipeline(q + (context_line(n) if n else ""))


def save(state):
    os.makedirs(RAW, exist_ok=True)
    json.dump(state, open(STATE, "w"), indent=2)


def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    quiet_libs()
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--c-miss", type=float, default=0.02)
    ap.add_argument("--c-false", type=float, default=5.0)
    args = ap.parse_args()
    print(banner("Part 3 - threshold sweep"))

    path = os.path.join(HERE, "cache_cases.yaml")
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    cfg = yaml.safe_load(open(path))
    seeds, cases = cfg["seeds"], cfg["cases"]
    print(f"cache_cases.yaml sha256={sha[:16]}  seeds={len(seeds)}  cases={len(cases)}")

    state = {} if args.fresh or not os.path.exists(STATE) else json.load(open(STATE))
    if state.get("sha") not in (None, sha):
        sys.exit("cache_cases.yaml changed since this sweep started - labels are frozen. "
                 "Use --fresh only if you really intend a new run.")
    state.setdefault("sha", sha)
    state.setdefault("seeds", {})
    state.setdefault("cases", {})

    cache = SemanticCache(namespace="sweep")
    if args.fresh:
        cache.clear()
    embed("warm up the embedding model")

    # 1. seed the cache --------------------------------------------------------------------
    text_to_seed = {v: k for k, v in seeds.items()}
    for sid, q in seeds.items():
        if sid in state["seeds"]:
            continue
        log.info("SEED %s -> HW8 pipeline: %s", sid, q)
        res = agent_call(q)
        if res.get("status") != "approved":  # one retry; small models are not deterministic
            log.info("SEED %s was %s (%s) - retrying once", sid, res.get("status"),
                     res.get("review"))
            res = agent_call(q)
        n = find_notice(q)
        from notice_context import data_version
        cache.store(q, embed(q), res["answer"], n and n["id"], data_version(n), res.get("status"))
        state["seeds"][sid] = {"text": q, "answer": res["answer"], "status": res.get("status"),
                               "pipeline_ms": res["pipeline_ms"]}
        save(state)
    # make sure the index holds the seeds (e.g. after a Redis restart)
    if len(list(cache.r.scan_iter(f"{cache.key_prefix}*"))) < len(seeds):
        cache.clear()
        from notice_context import data_version
        for sid, s in state["seeds"].items():
            n = find_notice(s["text"])
            cache.store(s["text"], embed(s["text"]), s["answer"], n and n["id"],
                        data_version(n), s["status"])

    # 2 + 3. measure every case ------------------------------------------------------------
    for c in cases:
        st = state["cases"].get(c["id"], {})
        if "similarity" not in st:
            t0 = time.perf_counter()
            entry, sim = cache.nearest(embed(c["text"]))
            st["lookup_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            st["similarity"] = round(sim, 4)
            st["matched_seed"] = text_to_seed.get(entry["query"]) if entry else None
            st["matched_answer"] = entry["answer"] if entry else None
        need_pipeline = st["similarity"] < max(THRESHOLDS) or c["type"] == "similar_different"
        if need_pipeline and "pipeline_ms" not in st:
            log.info("CASE %s sim=%.3f (nearest %s) -> HW8 pipeline", c["id"], st["similarity"],
                     st["matched_seed"])
            res = agent_call(c["text"])
            st.update(pipeline_ms=res["pipeline_ms"], own_answer=res["answer"],
                      own_status=res.get("status"))
        state["cases"][c["id"]] = st
        save(state)
        log.info("CASE %-3s %-17s sim=%.3f nearest=%-4s lookup=%.1fms", c["id"], c["type"],
                 st["similarity"], st["matched_seed"], st["lookup_ms"])

    # 4. score ------------------------------------------------------------------------------
    def nid(q):
        n = find_notice(q)
        return n["id"] if n else "none"

    seed_nid = {sid: nid(q) for sid, q in seeds.items()}
    case_nid = {c["id"]: nid(c["text"]) for c in cases}

    def score(notice_filter: bool):
        rows, detail = [], {}
        for t in THRESHOLDS:
            hits = falses = 0
            lat, false_ids = [], []
            for c in cases:
                st = state["cases"][c["id"]]
                hit = st["similarity"] >= t
                if notice_filter:  # KNN restricted to entries about the same notice
                    hit = hit and seed_nid.get(st["matched_seed"]) == case_nid[c["id"]]
                if hit:
                    hits += 1
                    if not (c["expect"] == "hit" and st["matched_seed"] == c.get("seed")):
                        falses += 1
                        false_ids.append(c["id"])
                    lat.append(st["lookup_ms"])
                else:
                    lat.append(st["lookup_ms"] + st.get("pipeline_ms", 0))
            misses = len(cases) - hits
            rows.append({"threshold": t, "hits": hits,
                         "hit_rate_pct": round(100 * hits / len(cases), 1),
                         "false_hits": falses,
                         "false_hit_rate_pct": round(100 * falses / hits, 1) if hits else 0.0,
                         "mean_latency_ms": round(statistics.mean(lat), 1), "misses": misses,
                         "total_cost": round(misses * args.c_miss + falses * args.c_false, 2)})
            detail[str(t)] = false_ids
        return rows, detail

    def show(title, rows, detail):
        print(f"\n{title}")
        print(f"{'Threshold':>9} | {'Hit rate':>8} | {'False-hit rate':>14} | "
              f"{'Mean latency (ms)':>17} | {'Total cost':>10} | false hits")
        for r in rows:
            print(f"{r['threshold']:>9.2f} | {r['hit_rate_pct']:>7.1f}% | "
                  f"{r['false_hit_rate_pct']:>6.1f}% ({r['false_hits']:>2}) | "
                  f"{r['mean_latency_ms']:>17.1f} | ${r['total_cost']:>9.2f} | "
                  f"{', '.join(detail[str(r['threshold'])]) or '-'}")
        best = min(rows, key=lambda r: (r["total_cost"], r["mean_latency_ms"]))
        print(f"Lowest total cost: threshold {best['threshold']:.2f} (${best['total_cost']:.2f})")
        return best

    print(f"\nCost model: C_miss = ${args.c_miss:.2f} per miss, "
          f"C_false = ${args.c_false:.2f} per false hit")
    rows, detail = score(False)
    show("A) Cosine threshold only (Part 3.2)", rows, detail)
    rows_f, detail_f = score(True)
    show("B) Threshold + same-notice filter (Part 3 fix)", rows_f, detail_f)
    print("\nPer-case similarity to nearest seed:")
    for c in cases:
        st = state["cases"][c["id"]]
        ok = c["expect"] == "miss" or st["matched_seed"] == c.get("seed")
        flag = "" if ok else "  (wrong seed!)"
        print(f"  {c['id']:<4} {c['type']:<17} expect={c['expect']:<4} sim={st['similarity']:.3f} "
              f"nearest={st['matched_seed']}{flag}")

    out = {"sha256": sha, "c_miss": args.c_miss, "c_false": args.c_false,
           "threshold_only": {"rows": rows, "false_hits": detail},
           "with_notice_filter": {"rows": rows_f, "false_hits": detail_f},
           "case_notice": case_nid, "seed_notice": seed_nid}
    json.dump(out, open(os.path.join(RAW, "part3_sweep.json"), "w"), indent=2)
    print("\nsaved reports/hw09/raw/part3_sweep.json and part3_state.json")


if __name__ == "__main__":
    main()
