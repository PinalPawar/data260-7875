"""HW9 Part 1: Redis-backed view counter for the primary entity (Notice).

Write-behind pattern:
  - every access -> Redis INCR on  s7875:views:notice:{id}   (atomic, in memory, sub-ms)
  - every 10th access -> persist the count to MySQL notices.view_count

Run:  python hw9/view_counter.py            (uses the first notice in s7875_rel)
      python hw9/view_counter.py --id 3     (a specific notice)
"""

import argparse
import logging
import statistics

from sqlalchemy import inspect, text

from common import PREFIX, banner, get_engine, get_redis, now_ms

import sys
logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hw9.part1")

SYNC_EVERY = 10


class NoticeDBWithCache:
    """MySQL (s7875_rel.notices) with a Redis cache in front of it."""

    def __init__(self):
        self.engine = get_engine()
        self.redis_client = get_redis()
        self._ensure_view_column()

    def _ensure_view_column(self):
        cols = {c["name"] for c in inspect(self.engine).get_columns("notices")}
        if "view_count" not in cols:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE notices "
                                  "ADD COLUMN view_count INTEGER NOT NULL DEFAULT 0"))
            log.info("Added column notices.view_count")

    @staticmethod
    def views_key(notice_id: int) -> str:
        return f"{PREFIX}:views:notice:{notice_id}"

    # ---- the ONE new method Part 1 asks for ------------------------------------------------
    def increment_notice_views(self, notice_id: int) -> int:
        count = self.redis_client.incr(self.views_key(notice_id))  # 1. INCR in Redis
        if count % SYNC_EVERY == 0:  # 2. every 10 -> persist
            with self.engine.begin() as conn:
                conn.execute(
                    text("UPDATE notices SET view_count = :c WHERE id = :id"),
                    {"c": count, "id": notice_id},
                )
            log.info("Synced views to database (notice_id=%s, view_count=%s)", notice_id, count)
            self.last_synced = True
        else:
            self.last_synced = False
        return count  # 3. return current count

    # ---- helpers for the demo only ---------------------------------------------------------
    def first_notice_id(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT MIN(id) FROM notices")).scalar()

    def db_view_count(self, notice_id: int) -> int:
        with self.engine.connect() as conn:
            return conn.execute(
                text("SELECT view_count FROM notices WHERE id = :id"), {"id": notice_id}
            ).scalar()

    def reset(self, notice_id: int):
        self.redis_client.delete(self.views_key(notice_id))
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE notices SET view_count = 0 WHERE id = :id"),
                         {"id": notice_id})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, default=None)
    ap.add_argument("--n", type=int, default=25)
    args = ap.parse_args()

    print(banner("Part 1 - Redis view counter"))
    db = NoticeDBWithCache()
    nid = args.id or db.first_notice_id()
    db.reset(nid)
    print(f"Notice id {nid} | Redis key {db.views_key(nid)} | sync every {SYNC_EVERY}\n")
    print("=== Testing Counter ===\n")

    times = []
    for i in range(1, args.n + 1):
        t0 = now_ms()
        total = db.increment_notice_views(nid)
        times.append(now_ms() - t0)
        print(f"Access #{i}: Total = {total}")
        if db.last_synced:
            print("✓ Synced views to database")

    redis_val = db.redis_client.get(db.views_key(nid))
    print(f"\nRedis {db.views_key(nid)} = {redis_val}")
    print(f"MySQL notices.view_count (id={nid}) = {db.db_view_count(nid)}  (last multiple of 10)")

    # latency evidence: plain INCR vs. a direct DB write per view
    incr_t, db_t = [], []
    tmp = f"{PREFIX}:views:latency_probe"
    for _ in range(50):
        t0 = now_ms()
        db.redis_client.incr(tmp)
        incr_t.append(now_ms() - t0)
        t0 = now_ms()
        with db.engine.begin() as conn:
            conn.execute(text("UPDATE notices SET view_count = view_count WHERE id = :id"),
                         {"id": nid})
        db_t.append(now_ms() - t0)
    db.redis_client.delete(tmp)
    print(f"\nLatency per view (50 trials, median): Redis INCR {statistics.median(incr_t):.3f} ms"
          f" | MySQL UPDATE {statistics.median(db_t):.3f} ms")


if __name__ == "__main__":
    main()
