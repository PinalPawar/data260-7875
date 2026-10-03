"""
Where the tools get their data from.

The tools never talk to MySQL directly. They are handed a "store" object
with three methods (search / detail / stats). That is the dependency
injection HW5 Part 4 asks for:
  - DbStore        -> the real s7875_rel MySQL database (used by the MCP
                      server and the agent)
  - InMemoryStore  -> a small fixed list of notices held in memory (used by
                      the offline tests: no database, no network, no LLM)
"""
from typing import Optional


class DbStore:
    """Reads recall notices from MySQL through the app's own SQLAlchemy models."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from database import SessionLocal  # imported lazily so tests never need MySQL
            session_factory = SessionLocal
        self._session_factory = session_factory

    def search(self, query: str, category: Optional[str], limit: int) -> list[dict]:
        from sqlalchemy import or_
        from models import Manufacturer, Notice

        with self._session_factory() as db:
            like = f"%{query}%"
            q = (
                db.query(Notice, Manufacturer)
                .join(Manufacturer, Notice.manufacturer_id == Manufacturer.id)
                .filter(or_(Notice.product.like(like), Manufacturer.name.like(like)))
            )
            if category:
                q = q.filter(Notice.category == category)
            rows = q.order_by(Notice.id.desc()).limit(limit).all()
            return [
                {
                    "notice_code": n.notice_code,
                    "product": n.product,
                    "manufacturer": m.name,
                    "category": n.category,
                    "units_affected": n.units_affected,
                }
                for n, m in rows
            ]

    def detail(self, notice_code: str) -> Optional[dict]:
        from models import Manufacturer, Notice

        with self._session_factory() as db:
            row = (
                db.query(Notice, Manufacturer)
                .join(Manufacturer, Notice.manufacturer_id == Manufacturer.id)
                .filter(Notice.notice_code == notice_code)
                .first()
            )
            if not row:
                return None
            n, m = row
            return {
                "notice_code": n.notice_code,
                "product": n.product,
                "category": n.category,
                "units_affected": n.units_affected,
                "description": n.description,
                "contact_email": n.email,
                "manufacturer": {"code": m.code, "name": m.name, "headquarters": m.headquarters},
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }

    def stats(self, group_by: str) -> list[dict]:
        from sqlalchemy import func
        from models import Manufacturer, Notice

        with self._session_factory() as db:
            if group_by == "category":
                key = Notice.category
                q = db.query(key, func.count(Notice.id), func.coalesce(func.sum(Notice.units_affected), 0))
            else:  # "manufacturer"
                key = Manufacturer.name
                q = db.query(
                    key, func.count(Notice.id), func.coalesce(func.sum(Notice.units_affected), 0)
                ).join(Manufacturer, Notice.manufacturer_id == Manufacturer.id)
            rows = q.group_by(key).order_by(func.count(Notice.id).desc()).all()
            return [
                {"group": name, "notice_count": int(count), "total_units_affected": int(units)}
                for name, count, units in rows
            ]


class InMemoryStore:
    """A tiny stand-in for the database, for offline tests."""

    def __init__(self, notices: list[dict]):
        self._notices = list(notices)

    def search(self, query: str, category: Optional[str], limit: int) -> list[dict]:
        q = query.lower()
        hits = [
            n for n in self._notices
            if (q in n["product"].lower() or q in n["manufacturer"]["name"].lower())
            and (category is None or n["category"] == category)
        ]
        return [
            {
                "notice_code": n["notice_code"],
                "product": n["product"],
                "manufacturer": n["manufacturer"]["name"],
                "category": n["category"],
                "units_affected": n["units_affected"],
            }
            for n in hits[:limit]
        ]

    def detail(self, notice_code: str) -> Optional[dict]:
        for n in self._notices:
            if n["notice_code"] == notice_code:
                return dict(n)
        return None

    def stats(self, group_by: str) -> list[dict]:
        groups: dict[str, dict] = {}
        for n in self._notices:
            name = n["category"] if group_by == "category" else n["manufacturer"]["name"]
            g = groups.setdefault(name, {"group": name, "notice_count": 0, "total_units_affected": 0})
            g["notice_count"] += 1
            g["total_units_affected"] += n["units_affected"]
        return sorted(groups.values(), key=lambda g: (-g["notice_count"], g["group"]))
