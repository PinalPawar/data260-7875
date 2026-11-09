"""HW9 Part 3.5: a stale cached answer, then the data-version fix.

  1. Ask about Butter batch 4609 -> MISS -> HW8 pipeline answer (units_affected = 3671) -> cached
     with data_version = hash(notice row).
  2. UPDATE the notice in s7875_rel (units_affected 3671 -> 5200).
  3. Ask again with version checking OFF -> HIT -> the OLD answer (3671) is served: STALE.
  4. Ask again with version checking ON  -> cached data_version != current data_version ->
     entry invalidated -> MISS -> pipeline answers with 5200 -> re-cached with the new version.
  5. Ask once more -> HIT with the fresh answer.
  6. Restore the original row (skip with --keep-change).

    python hw9/stale_demo.py
"""

import argparse
import logging
import sys

from sqlalchemy import text

from common import banner, get_engine
from notice_context import data_version, get_notice
from semantic_cache import SemanticCache, quiet_libs

NOTICE_ID = 4609
QUESTION = "How many units of Butter batch 4609 were recalled?"
NEW_UNITS = 5200


def show(step, r, old, new):
    says = ("OLD value %s" % old if str(old) in r["answer"] else
            "NEW value %s" % new if str(new) in r["answer"] else "neither number")
    print(f"  -> is_cached={r['is_cached']} similarity={r['similarity']:.3f} "
          f"latency={r['latency_ms']:.1f} ms data_version={r['data_version']} | answer has {says}")
    print(f"     answer: {r['answer'][:220]}")


def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    quiet_libs()
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-change", action="store_true")
    args = ap.parse_args()
    print(banner("Part 3.5 - stale answer and data-version invalidation"))

    eng = get_engine()
    row = get_notice(NOTICE_ID)
    old_units = row["units_affected"]
    print(f"notice {NOTICE_ID}: {row['product']} units_affected={old_units} "
          f"data_version={data_version(row)}")

    cache = SemanticCache(threshold=0.80, notice_filter=True, namespace="stale",
                          check_version=False)
    print(f"cleared {cache.clear()} old entries in {cache.key_prefix}*")

    print(f"\n[1] first ask (empty cache): {QUESTION}")
    show(1, cache.ask(QUESTION), old_units, NEW_UNITS)

    print(f"\n[2] UPDATE notices SET units_affected = {NEW_UNITS} WHERE id = {NOTICE_ID}")
    with eng.begin() as c:
        c.execute(text("UPDATE notices SET units_affected = :u WHERE id = :i"),
                  {"u": NEW_UNITS, "i": NOTICE_ID})
    print(f"    current data_version={data_version(get_notice(NOTICE_ID))}")

    print("\n[3] ask again, version check OFF (plain semantic cache)")
    r = cache.ask(QUESTION)
    show(3, r, old_units, NEW_UNITS)
    if r["is_cached"]:
        print("    !! STALE: the cache served an answer built from the old row "
              f"(cached version {r['data_version']} != current "
              f"{data_version(get_notice(NOTICE_ID))})")

    print("\n[4] ask again, version check ON (fix)")
    cache.check_version = True
    show(4, cache.ask(QUESTION), old_units, NEW_UNITS)

    print("\n[5] ask once more, version check ON")
    show(5, cache.ask(QUESTION), old_units, NEW_UNITS)

    if not args.keep_change:
        with eng.begin() as c:
            c.execute(text("UPDATE notices SET units_affected = :u WHERE id = :i"),
                      {"u": old_units, "i": NOTICE_ID})
        print(f"\nrestored notice {NOTICE_ID} units_affected={old_units}")


if __name__ == "__main__":
    main()
