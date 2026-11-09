"""HW9 Part 4: build reference_data.json (ground truth) from s7875_rel.

The input datasets hold only questions. The Evaluator Agent needs the correct facts for every
notice those questions mention, so this script exports exactly those notices from MySQL.

    python hw9/part4/build_reference.py
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from sqlalchemy import text  # noqa: E402

from common import banner, get_engine  # noqa: E402

CATEGORY_TEXT = {
    "bacterialContamination": "Listeria (bacterial) contamination",
    "mislabelling": "an undeclared allergen on the label (mislabelling)",
    "foreignMaterial": "small metal fragments (foreign material)",
    "supplyShortage": "a packaging shortage causing incorrect fill levels",
}
REQUIRED_ACTION = ("Stop using the product; do not eat it; throw it away or return it to the "
                   "store; clean surfaces it touched.")


def main():
    print(banner("Part 4 - build reference_data.json"))
    batches = {4609, 4664}  # the two demo questions (4.1 controlled case, 4.2 lesson reuse)
    for f in ("training_data.json", "validation_data.json", "test_data.json"):
        for item in json.load(open(os.path.join(HERE, f))):
            batches.update(int(b) for b in re.findall(r"batch\s*(\d{3,5})", item["question"], re.I))
    rows = []
    with get_engine().connect() as c:
        for b in sorted(batches):
            r = c.execute(text(
                "SELECT n.id, n.product, n.notice_code, n.units_affected, n.category, "
                "n.description, m.name AS manufacturer FROM notices n LEFT JOIN manufacturers m "
                "ON m.id = n.manufacturer_id WHERE n.product LIKE :p"),
                {"p": f"%(batch {b})%"}).first()
            if not r:
                print(f"  !! no notice for batch {b}")
                continue
            r = dict(r._mapping)
            lot = re.search(r"#?(L\d{4,6})", r["description"] or "")
            rows.append({
                "notice_id": r["id"], "batch": b, "notice_code": r["notice_code"],
                "product": re.sub(r"\s*\(batch.*\)", "", r["product"]),
                "manufacturer": r["manufacturer"], "category": r["category"],
                "reason": CATEGORY_TEXT.get(r["category"], r["category"]),
                "units_affected": r["units_affected"],
                "lot": lot.group(1) if lot else f"L1{b}",
                "description": r["description"], "required_action": REQUIRED_ACTION})
    out = os.path.join(HERE, "reference_data.json")
    json.dump(rows, open(out, "w"), indent=2)
    print(f"wrote {len(rows)} reference records -> {os.path.relpath(out)}")
    for r in rows:
        print(f"  batch {r['batch']}: {r['product']:<16} units={r['units_affected']:<5} "
              f"lot={r['lot']:<7} {r['manufacturer']:<18} {r['category']}")


if __name__ == "__main__":
    main()
