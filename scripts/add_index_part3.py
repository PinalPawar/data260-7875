"""
HW4 Part 3, step 8: show the EXPLAIN plan for the naive endpoint's per-row
lookup (SELECT ... FROM related_info WHERE notice_id = ?) before and after
adding an index on related_info.notice_id, and explain what changed.

Run this AFTER scripts/seed_hw04_part3.py (needs the 5,000/200 seeded rows
to make the "before" scan plan meaningful).

Usage:
    python3 scripts/add_index_part3.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine

SAMPLE_QUERY = "SELECT * FROM related_info WHERE notice_id = 4242"

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reports", "hw04", "raw", "explain_before_after.txt",
)


def explain(conn, label):
    result = conn.execute(text(f"EXPLAIN {SAMPLE_QUERY}"))
    rows = [dict(row._mapping) for row in result]
    lines = [f"--- EXPLAIN {label} ---", f"Query: {SAMPLE_QUERY}"]
    for row in rows:
        lines.append(str(row))
    return "\n".join(lines)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    output_sections = []

    with engine.connect() as conn:
        output_sections.append(explain(conn, "BEFORE adding index"))

        conn.execute(text("CREATE INDEX idx_related_info_notice_id ON related_info(notice_id)"))
        conn.commit()

        output_sections.append(explain(conn, "AFTER adding index idx_related_info_notice_id"))

    explanation = (
        "\nWhat changed: before the index, MySQL has no fast way to find rows where "
        "notice_id = 4242 other than scanning the related_info table row by row "
        "('type: ALL', a full table scan, rows ~= total row count). After creating "
        "idx_related_info_notice_id, MySQL can jump straight to the matching row(s) "
        "using the index ('type: ref' or 'const', with rows close to the actual number "
        "of matches -- 0 or 1 here, since only 200 of the 5,000 notices have a related "
        "row). This is exactly the query the naive list-naive endpoint runs once per "
        "notice on the page, so this index is what would make even the naive N+1 "
        "version scale better per-query -- though it still doesn't fix the real "
        "problem, which is running that query N times instead of once via a JOIN."
    )

    full_output = "\n\n".join(output_sections) + "\n" + explanation
    with open(OUT_PATH, "w") as f:
        f.write(full_output)

    print(full_output)
    print(f"\nWrote {OUT_PATH}")
