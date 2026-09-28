"""
HW4 Part 3, step 1: seed 5,000 primary-domain-entity rows (notices) and 200
related rows, reproducibly, using SEED = SID4 = 7875.

This WIPES the notices and related_info tables first, so it produces the
same 5,000/200 rows every time it's run (that's what "reproducible" means
here) -- run your Part 1/2 Postman screenshots BEFORE running this script,
since anything you added by hand through the CRUD app will be replaced.

Usage:
    python3 scripts/seed_hw04_part3.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base, engine, SessionLocal
from models import Notice, RelatedInfo

SEED = 7875  # SID4, per HW4 Section 0 -- keeps the seeded data reproducible

PRODUCTS = [
    "Peanut Butter", "Frozen Spinach", "Canned Corn", "Ground Beef", "Whole Milk",
    "Shredded Cheese", "Baby Formula", "Bagged Lettuce", "Deli Turkey", "Ice Cream",
    "Chicken Nuggets", "Salad Kit", "Cream Cheese", "Hummus", "Orange Juice",
    "Frozen Waffles", "Granola Bars", "Trail Mix", "Yogurt", "Butter",
]
MANUFACTURERS = [
    "ACME Foods", "GreenFields Co", "Sunny Farms Co", "Valley Fresh", "Northgate Dairy",
    "Harvest Point", "Coastal Provisions", "Prairie Mills", "BlueRiver Foods", "Golden Acres",
]
CATEGORIES = ["supplyShortage", "bacterialContamination", "foreignMaterial", "mislabelling"]
DESCRIPTION_TEMPLATES = [
    "Routine testing detected {issue} in lot #{lot}.",
    "Consumer complaint led to discovery of {issue} affecting lot #{lot}.",
    "Internal audit flagged {issue} in a batch produced under lot #{lot}.",
    "Distributor reported {issue}; recall issued for lot #{lot}.",
]
ISSUES = {
    "supplyShortage": "a packaging shortage causing incorrect fill levels",
    "bacterialContamination": "Listeria contamination",
    "foreignMaterial": "small metal fragments",
    "mislabelling": "an undeclared allergen on the label",
}


def build_notices(rng: random.Random, n: int):
    rows = []
    for i in range(1, n + 1):
        category = rng.choice(CATEGORIES)
        manufacturer = rng.choice(MANUFACTURERS)
        template = rng.choice(DESCRIPTION_TEMPLATES)
        rows.append({
            "product": f"{rng.choice(PRODUCTS)} (batch {i})",
            "manufacturer": manufacturer,
            "email": f"qa{i}@{manufacturer.lower().replace(' ', '')}.com",
            "description": template.format(issue=ISSUES[category], lot=f"L{10000 + i}"),
            "category": category,
        })
    return rows


def build_related_rows(rng: random.Random, notice_ids, n: int):
    chosen = rng.sample(notice_ids, n)  # 200 distinct notices get exactly one related row
    notes = [
        "Follow-up lab result confirmed.",
        "State inspector visit logged.",
        "Retailer shelf-pull confirmed complete.",
        "Second sample retested, result unchanged.",
        "Consumer complaint case closed.",
    ]
    return [{"notice_id": nid, "note": rng.choice(notes)} for nid in chosen]


if __name__ == "__main__":
    rng = random.Random(SEED)

    # Clean slate so the seed is reproducible run-to-run.
    RelatedInfo.__table__.drop(bind=engine, checkfirst=True)
    Notice.__table__.drop(bind=engine, checkfirst=True)
    Base.metadata.create_all(bind=engine)

    db_session_basede26 = SessionLocal()
    try:
        notice_rows = build_notices(rng, 5000)
        db_session_basede26.bulk_insert_mappings(Notice, notice_rows)
        db_session_basede26.commit()

        notice_ids = [row[0] for row in db_session_basede26.query(Notice.id).all()]
        related_rows = build_related_rows(rng, notice_ids, 200)
        db_session_basede26.bulk_insert_mappings(RelatedInfo, related_rows)
        db_session_basede26.commit()

        print(f"Seeded {len(notice_rows)} notices and {len(related_rows)} related_info rows "
              f"(SEED={SEED}).")
    finally:
        db_session_basede26.close()
