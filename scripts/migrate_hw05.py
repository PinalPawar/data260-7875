"""
HW5 Part 1: one-time upgrade of the HW4 database to the HW5 two-table design.

What it does (only the steps that are still needed -- safe to re-run):
  1. Creates the new `manufacturers` table.
  2. Copies every distinct name from the old free-text notices.manufacturer
     column into `manufacturers` (codes MFR-0001, MFR-0002, ...).
  3. Adds notice_code, units_affected, manufacturer_id, created_at,
     updated_at to `notices` and fills them in for the existing rows.
  4. Adds the UNIQUE constraint on notice_code and the FOREIGN KEY
     notices.manufacturer_id -> manufacturers.id (ON DELETE RESTRICT).
  5. Drops the old free-text notices.manufacturer column.

No notice rows are deleted, so the HW4 seeded data is kept.

Usage (from the repo root, with MySQL running):
    python3 scripts/migrate_hw05.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from database import Base, engine
import models  # noqa: F401  (registers the tables on Base)

SEED = 7875  # SID4 -- keeps the generated headquarters/units reproducible
CITIES = [
    "Fresno, CA", "Salinas, CA", "Yuma, AZ", "Boise, ID", "Madison, WI",
    "Omaha, NE", "Portland, OR", "Wichita, KS", "Memphis, TN", "Des Moines, IA",
]


def columns(table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def main():
    Base.metadata.create_all(bind=engine)  # creates `manufacturers` (and anything else missing)
    print("[1/5] manufacturers table present")

    cols = columns("notices")
    if "manufacturer" not in cols:
        print("notices is already in the HW5 shape -- nothing to migrate.")
        return summary()

    rng = random.Random(SEED)
    with engine.begin() as conn:
        names = [r[0] for r in conn.execute(
            text("SELECT DISTINCT manufacturer FROM notices ORDER BY manufacturer"))]
        existing = {r[0] for r in conn.execute(text("SELECT name FROM manufacturers"))}
        next_num = conn.execute(text("SELECT COUNT(*) FROM manufacturers")).scalar() + 1
        for name in names:
            if name in existing:
                continue
            conn.execute(
                text("INSERT INTO manufacturers (name, headquarters, code) VALUES (:n, :h, :c)"),
                {"n": name, "h": rng.choice(CITIES), "c": f"MFR-{next_num:04d}"},
            )
            next_num += 1
        print(f"[2/5] {len(names)} manufacturer name(s) copied into manufacturers")

        if "notice_code" not in cols:
            conn.execute(text("ALTER TABLE notices ADD COLUMN notice_code VARCHAR(20) NULL"))
        if "units_affected" not in cols:
            conn.execute(text("ALTER TABLE notices ADD COLUMN units_affected INT NOT NULL DEFAULT 0"))
        if "manufacturer_id" not in cols:
            conn.execute(text("ALTER TABLE notices ADD COLUMN manufacturer_id INT NULL"))
        if "created_at" not in cols:
            conn.execute(text(
                "ALTER TABLE notices ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"))
        if "updated_at" not in cols:
            conn.execute(text(
                "ALTER TABLE notices ADD COLUMN updated_at DATETIME NOT NULL "
                "DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"))

        # Fill the new columns for the rows that already exist.
        conn.execute(text(
            "UPDATE notices n JOIN manufacturers m ON m.name = n.manufacturer "
            "SET n.manufacturer_id = m.id, "
            "    n.notice_code = CONCAT('RCL-2026-', LPAD(n.id, 5, '0')), "
            "    n.units_affected = (n.id * 7919) % 5000"
        ))
        print("[3/5] new notices columns added and filled")

        conn.execute(text("ALTER TABLE notices MODIFY notice_code VARCHAR(20) NOT NULL"))
        conn.execute(text("ALTER TABLE notices MODIFY manufacturer_id INT NOT NULL"))
        conn.execute(text("ALTER TABLE notices ADD CONSTRAINT uq_notices_notice_code UNIQUE (notice_code)"))
        conn.execute(text(
            "ALTER TABLE notices ADD CONSTRAINT fk_notices_manufacturer "
            "FOREIGN KEY (manufacturer_id) REFERENCES manufacturers(id) ON DELETE RESTRICT"))
        print("[4/5] UNIQUE(notice_code) and FOREIGN KEY(manufacturer_id) added")

        conn.execute(text("ALTER TABLE notices DROP COLUMN manufacturer"))
        print("[5/5] old free-text notices.manufacturer column dropped")

    summary()


def summary():
    with engine.connect() as conn:
        m = conn.execute(text("SELECT COUNT(*) FROM manufacturers")).scalar()
        n = conn.execute(text("SELECT COUNT(*) FROM notices")).scalar()
    print(f"Done: {m} manufacturers, {n} notices.")


if __name__ == "__main__":
    main()
