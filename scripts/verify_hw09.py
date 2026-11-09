"""
HW9 self-check / smoke test. Writes reports/hw09/verification.json.

Checks behaviour, not model wording, and never calls the LLM: the cache checks use a stand-in
pipeline function, and Part 4 checks run the Evaluator Agent on hand-written answers. Every row
or Redis key it touches is restored or deleted at the end (cache checks use the s7875:verify:*
namespace). The only file it writes is reports/hw09/verification.json.

Before running (repo root, conda env data260):
    1. docker start s7875-redis          (Redis Stack, port 6379)
    2. MySQL s7875_rel running (.env DATABASE_URL)
    3. python scripts/verify_hw09.py     (or: make verify-hw09)

Set HW9_COMMIT=<hash> to record the commit when the folder is not a git checkout.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW9 = ROOT / "hw9"
P4 = HW9 / "part4"
OUT = ROOT / "reports" / "hw09"
RAW = OUT / "raw"
for p in (str(ROOT), str(HW9), str(P4)):
    sys.path.insert(0, p)
os.chdir(ROOT)

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": bool(passed), "detail": str(detail)[:300]})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""),
          flush=True)


def guarded(name, fn):
    try:
        fn()
    except Exception as exc:  # smoke test: report, never crash
        check(name, False, f"{type(exc).__name__}: {exc}")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def commit_hash():
    return os.getenv("HW9_COMMIT") or git("rev-parse", "--short", "HEAD") or "unknown"


def fake_pipeline(q):
    return {"answer": f"stand-in answer for: {q[:60]}", "status": "approved"}


# ------------------------------------------------------------------------------------------
def check_config():
    import common as C
    check("Section 0 values", (C.SID4, C.PREFIX, C.PORT_BASE, C.SEED, C.VERIFY_SEED)
          == (7875, "s7875", 8675, 7875, 267875),
          f"SID4={C.SID4} PREFIX={C.PREFIX} PORT_BASE={C.PORT_BASE}")


def check_redis():
    from common import PREFIX, get_redis
    r = get_redis()
    check("Redis reachable", r.ping())
    mods = str(r.execute_command("MODULE", "LIST")).lower()
    check("Redis has the search module (vector index support)", "search" in mods)
    keys = [k for k in r.scan_iter("*", count=1000)]
    bad = [k for k in keys if not k.startswith(PREFIX)]
    check("every Redis key starts with PREFIX s7875", not bad,
          f"{len(keys)} keys, non-prefixed: {bad[:5]}")
    idx = r.execute_command("FT._LIST")
    idx = [i.decode() if isinstance(i, bytes) else i for i in idx]
    check("every vector index name starts with PREFIX", all(i.startswith(PREFIX) for i in idx), idx)


def check_part1():
    from sqlalchemy import text
    from view_counter import NoticeDBWithCache
    db = NoticeDBWithCache()
    nid = db.first_notice_id()
    key = db.views_key(nid)
    old_r, old_db = db.redis_client.get(key), db.db_view_count(nid)
    try:
        db.reset(nid)
        counts, synced = [], []
        for _ in range(12):
            counts.append(db.increment_notice_views(nid))
            synced.append(db.last_synced)
        check("Part 1: INCR returns 1..12 in order", counts == list(range(1, 13)), counts)
        check("Part 1: synced to MySQL exactly at view 10",
              [i + 1 for i, s in enumerate(synced) if s] == [10])
        check("Part 1: Redis 12 vs MySQL 10 (write-behind)",
              (db.redis_client.get(key), db.db_view_count(nid)) == ("12", 10),
              f"redis={db.redis_client.get(key)} mysql={db.db_view_count(nid)}")
        check("Part 1: key format s7875:views:notice:{id}", key == f"s7875:views:notice:{nid}", key)
    finally:
        if old_r is None:
            db.redis_client.delete(key)
        else:
            db.redis_client.set(key, old_r)
        with db.engine.begin() as c:
            c.execute(text("UPDATE notices SET view_count=:v WHERE id=:i"),
                      {"v": old_db or 0, "i": nid})


def check_cache():
    from sqlalchemy import text
    from common import get_engine
    from notice_context import get_notice
    from semantic_cache import SemanticCache
    q = "How many units of Butter batch 4609 were recalled?"
    c = SemanticCache(threshold=0.85, namespace="verify")
    c.clear()
    try:
        r1, r2 = c.ask(q, pipeline=fake_pipeline), c.ask(q, pipeline=fake_pipeline)
        check("Part 2: first ask is a miss (is_cached=false)", r1["is_cached"] is False)
        check("Part 2: repeat ask is a hit with similarity ~1.0",
              r2["is_cached"] is True and r2["similarity"] > 0.99, r2["similarity"])
        check("Part 2: response carries is_cached, similarity, latency_ms, data_version",
              all(k in r2 for k in ("is_cached", "similarity", "latency_ms", "data_version")))
        r3 = c.ask("How many units of Butter batch 4656 were recalled?", pipeline=fake_pipeline)
        check("Part 3: plain cosine cache false-hits a different batch (the problem)",
              r3["is_cached"] is True and r3["similarity"] > 0.9, f"sim={r3['similarity']}")
        c.clear()
        f = SemanticCache(threshold=0.80, namespace="verify", notice_filter=True)
        f.ask(q, pipeline=fake_pipeline)
        r4 = f.ask("How many units of Butter batch 4656 were recalled?", pipeline=fake_pipeline)
        r5 = f.ask("For Butter batch 4609, what is the number of recalled units?",
                   pipeline=fake_pipeline)
        check("Part 3 fix: same-notice filter turns the other batch into a miss",
              r4["is_cached"] is False)
        check("Part 3 fix: a paraphrase about the same batch still hits", r5["is_cached"] is True,
              f"sim={r5['similarity']}")
        # 3.5 data-version invalidation
        old = get_notice(4609)["units_affected"]
        eng = get_engine()
        try:
            with eng.begin() as cn:
                cn.execute(text("UPDATE notices SET units_affected=:u WHERE id=4609"),
                           {"u": old + 1})
            stale = f.ask(q, pipeline=fake_pipeline)
            check("Part 3.5: without version check the changed row still gives a stale hit",
                  stale["is_cached"] is True)
            f.check_version = True
            fresh = f.ask(q, pipeline=fake_pipeline)
            again = f.ask(q, pipeline=fake_pipeline)
            check("Part 3.5: version check invalidates the stale entry and re-answers",
                  fresh["is_cached"] is False and fresh.get("stale_invalidated") is True)
            check("Part 3.5: next ask hits the re-cached entry with the new data_version",
                  again["is_cached"] is True and again["data_version"] == fresh["data_version"]
                  != stale["data_version"])
        finally:
            with eng.begin() as cn:
                cn.execute(text("UPDATE notices SET units_affected=:u WHERE id=4609"), {"u": old})
    finally:
        c.clear()


def check_saved_part2_3():
    import yaml
    p2 = json.loads((RAW / "part2_run.json").read_text())
    types = {r["type"] for r in p2["rows"]}
    check("Part 2 run saved: >=10 queries with exact, paraphrase and new",
          len(p2["rows"]) >= 10 and {"exact", "paraphrase", "new"} <= types,
          f"{len(p2['rows'])} queries, hit rate {p2['summary']['hit_rate_pct']}%")
    path = HW9 / "cache_cases.yaml"
    cfg = yaml.safe_load(path.read_text())
    counts = {}
    for c in cfg["cases"]:
        counts[(c["type"], c["expect"])] = counts.get((c["type"], c["expect"]), 0) + 1
    want = {("exact", "hit"): 10, ("paraphrase", "hit"): 10,
            ("similar_different", "miss"): 10, ("unrelated", "miss"): 10}
    check("cache_cases.yaml: 40 cases, 10 per required category", counts == want, counts)
    first = git("log", "--diff-filter=A", "--format=%h %ci", "--", "hw9/cache_cases.yaml")
    check("cache_cases.yaml is committed", bool(first), first)
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "hw9/cache_cases.yaml"]).returncode == 0
    check("cache_cases.yaml unchanged since its commit (no relabeling)", unchanged)
    sweep = json.loads((RAW / "part3_sweep.json").read_text())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    check("sweep ran on the committed labels (sha256 match)", sweep["sha256"] == sha, sha[:16])
    th = [r["threshold"] for r in sweep["threshold_only"]["rows"]]
    check("sweep covers thresholds 0.75-0.95 for both scoring modes",
          th == [0.75, 0.8, 0.85, 0.9, 0.95] and len(sweep["with_notice_filter"]["rows"]) == 5, th)
    check("with the same-notice filter no threshold has a false hit",
          all(r["false_hits"] == 0 for r in sweep["with_notice_filter"]["rows"]))


def check_part4():
    from agents import EvaluatorAgent
    ref = json.loads((P4 / "reference_data.json").read_text())
    sets = {n: json.loads((P4 / f"{n}_data.json").read_text())
            for n in ("training", "validation", "test")}
    check("Part 4 datasets contain only id + question (no expected answers)",
          all(set(i) == {"id", "question"} for s in sets.values() for i in s),
          {k: len(v) for k, v in sets.items()})
    qs = {n: {i["question"] for i in s} for n, s in sets.items()}
    check("training / validation / test do not overlap",
          not (qs["training"] & qs["validation"] or qs["training"] & qs["test"]
               or qs["validation"] & qs["test"]))
    lessons = json.loads((P4 / "lessons.json").read_text())
    req = {"lesson_id", "failure_pattern", "correction", "created_at", "use_count"}
    check("lessons.json has the required fields",
          lessons and all(req <= set(les) for les in lessons),
          [les["lesson_id"] for les in lessons])
    check("lessons were created from training questions only (never test)",
          all(set(les["evidence"]) <= qs["training"] for les in lessons))
    check("every lesson has a validation decision",
          all(les.get("validation", {}).get("decision") in ("KEEP", "REMOVE") for les in lessons))
    ev = EvaluatorAgent(ref)
    r = ref[0]
    q = f"How many units of {r['product']} batch {r['batch']} were recalled?"
    good = f"{r['units_affected']} units were recalled. Stop using it and throw it away."
    check("Evaluator: correct answer -> PASS", ev.evaluate(q, good)["result"] == "PASS")
    bad = ev.evaluate(q, f"{r['units_affected']} units were recalled.")
    check("Evaluator: missing consumer action -> REVISE with feedback",
          bad["result"] == "REVISE" and "MISSING_ACTION" in bad["failure_codes"]
          and bad["feedback"])
    wrong = ev.evaluate(q, "1 unit was recalled. Throw it away.")
    check("Evaluator: wrong unit count -> REVISE MISSING_UNITS",
          "MISSING_UNITS" in wrong["failure_codes"])
    inv = ev.evaluate("What is a good recipe for pancakes?",
                      "See notice RCL-2026-04609, lot L14609.")
    check("Evaluator: invented recall details on an unrelated question -> UNSUPPORTED_CLAIM",
          "UNSUPPORTED_CLAIM" in inv["failure_codes"])
    res = json.loads((RAW / "part4_test_results.json").read_text())
    names = [t["variant"] for t in res["table"]]
    check("test results saved for all four variants",
          names == ["Baseline", "Evaluator Repair", "Lesson Memory", "Validated Improvement"],
          {t["variant"]: f"{t['correct']}/{t['correct'] + t['incorrect']}" for t in res["table"]})
    check("no run used more than 2 attempts",
          all(r["attempts"] <= 2 for v in res["detail"].values() for r in v))
    demo = json.loads((RAW / "part4_demo_revision.json").read_text())
    check("controlled revision demo: REVISE then PASS in 2 attempts",
          [t["result"] for t in demo["trace"]] == ["REVISE", "PASS"])


def main():
    import common as C
    print(f"===== {C.STUDENT_NAME} | SID4 {C.SID4} | PREFIX {C.PREFIX} | verify_hw09 =====")
    from semantic_cache import quiet_libs
    import logging
    logging.basicConfig(level=logging.WARNING)
    quiet_libs()
    guarded("config", check_config)
    guarded("redis", check_redis)
    guarded("Part 1", check_part1)
    guarded("Parts 2-3 live cache", check_cache)
    guarded("Parts 2-3 saved results", check_saved_part2_3)
    guarded("Part 4", check_part4)
    passed = sum(c["passed"] for c in checks)
    out = {
        "homework": 9, "sid4": C.SID4, "port_base": C.PORT_BASE, "prefix": C.PREFIX,
        "domain_id": 3, "seed": C.SEED, "verify_seed": C.VERIFY_SEED,
        "commit_hash": commit_hash(),
        "model": {"answering_agent":
                  "qwen3:1.7b via Ollama (HW8 adapter, temperature 0, seed 7875)",
                  "hw8_pipeline": "planner/writer qwen3:1.7b, reviewer qwen3:8b",
                  "embeddings": "sentence-transformers all-MiniLM-L6-v2 (384-dim)"},
        "config": {"redis": "redis/redis-stack-server (container s7875-redis)",
                   "cache_threshold_shipped": 0.80, "notice_filter": True,
                   "version_check": True},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": f"{passed}/{len(checks)} checks passed",
        "checks": checks,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verification.json").write_text(json.dumps(out, indent=2))
    print(f"\n{out['summary']}  ->  reports/hw09/verification.json")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
