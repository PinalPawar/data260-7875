"""HW9: link a question to the s7875_rel notice it is about, and give that notice a version.

Lookup order: notice code (RCL-2026-04609) -> batch number ("batch 4609") -> product words
(newest notice for that product, e.g. "frozen spinach" -> notice 5001).

data_version = short hash of the fields the answer is built from. If the row changes, the
version changes - that is the marker Part 3.5 uses to detect stale cache entries.
"""

import hashlib
import re

from sqlalchemy import text

from common import get_engine

_engine = None
STOP = {"recall", "recalled", "notice", "organic", "fresh", "the", "and", "with", "from", "batch"}
COLS = ("SELECT n.id, n.product, n.notice_code, n.units_affected, n.category, n.description, "
        "m.name AS manufacturer FROM notices n LEFT JOIN manufacturers m "
        "ON m.id = n.manufacturer_id ")


def engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def _one(where: str, params: dict) -> dict | None:
    with engine().connect() as c:
        r = c.execute(text(COLS + where + " ORDER BY n.id DESC LIMIT 1"), params).first()
        return dict(r._mapping) if r else None


def _words(text_: str) -> set[str]:
    """Lower-case words, with a simple plural strip (cucumbers -> cucumber)."""
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w
            for w in re.findall(r"[a-z]+", text_.lower())}


def find_notice(question: str) -> dict | None:
    m = re.search(r"RCL-\d{4}-\d{5}", question, flags=re.I)
    if m:
        return _one("WHERE n.notice_code = :c", {"c": m.group(0).upper()})
    m = re.search(r"batch\s*#?\s*(\d{3,5})", question, flags=re.I)
    if m:
        return _one("WHERE n.product LIKE :p", {"p": f"%(batch {int(m.group(1))})%"})
    q = _words(question)
    with engine().connect() as c:
        products = [r[0] for r in c.execute(text("SELECT DISTINCT product FROM notices"))]
    best, score = None, 0
    for p in products:
        base = re.sub(r"\s*\(batch.*\)", "", p)
        s = len(({w for w in _words(base) if len(w) > 3} - STOP) & q)
        if s > score or (s == score and s > 0 and "(batch" not in p):
            best, score = base, s
    if not best:
        return None
    # prefer the plain-named notice (e.g. 5001 "Frozen Spinach"), else the newest batch
    return (_one("WHERE n.product = :b", {"b": best})
            or _one("WHERE n.product LIKE :p", {"p": f"{best} (batch%"}))


def get_notice(notice_id) -> dict | None:
    return _one("WHERE n.id = :i", {"i": int(notice_id)})


def data_version(row: dict | None) -> str:
    if not row:
        return "none"
    raw = "|".join(str(row.get(k)) for k in
                   ("id", "product", "notice_code", "units_affected", "category", "description"))
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def context_line(row: dict) -> str:
    return (f"\n\n[Recall notice on file - use these facts: product: {row['product']}; "
            f"manufacturer: {row.get('manufacturer')}; notice code: {row['notice_code']}; "
            f"category: {row['category']}; units affected: {row['units_affected']}; "
            f"details: {row['description']}]")
