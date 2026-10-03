"""
HW4 Part 3: N+1 measurement and query tuning.

Two versions of the same "list notices with their related info" endpoint:

- list-naive: fetches the page of notices with one query, then loops over
  each row and runs a SEPARATE query to fetch its related_info. For a page
  of size N this is N+1 total queries -- the classic bug.
- list-fixed: fetches notices and their related_info in a single query
  using SQLAlchemy's joinedload() (a SQL LEFT JOIN under the hood), so the
  total stays at 1 query no matter how big the page is.

Both are protected by require_session, same as the regular /api/notices
CRUD, since this is still "your CRUD app" being measured, not a separate
public endpoint.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

import query_counter
from database import get_db_session_basede26
from models import Notice, User
from routers.session_auth import require_session

router = APIRouter(prefix="/api/notices", tags=["n1-demo"])


def _serialize(notice: Notice, related_rows):
    return {
        "id": notice.id,
        "product": notice.product,
        "manufacturer_id": notice.manufacturer_id,
        "related": [{"id": r.id, "note": r.note} for r in related_rows],
    }


@router.get("/list-naive")
def list_naive(
    page: int = 1,
    page_size: int = 10,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    from models import RelatedInfo  # local import avoids a circular import with models.py

    query_counter.reset()

    offset = (page - 1) * page_size
    notices = (
        db_session_basede26.query(Notice)
        .order_by(Notice.id.asc())
        .offset(offset)
        .limit(page_size)
        .all()
    )  # query #1

    results = []
    for notice in notices:
        # Intentionally naive: one extra round trip per notice.
        related = (
            db_session_basede26.query(RelatedInfo)
            .filter(RelatedInfo.notice_id == notice.id)
            .all()
        )  # query #2, #3, ... #(page_size+1)
        results.append(_serialize(notice, related))

    return {"version": "naive", "page": page, "page_size": page_size,
            "sql_query_count": query_counter.get(), "results": results}


@router.get("/list-fixed")
def list_fixed(
    page: int = 1,
    page_size: int = 10,
    db_session_basede26: Session = Depends(get_db_session_basede26),
    _user: User = Depends(require_session),
):
    query_counter.reset()

    offset = (page - 1) * page_size
    notices = (
        db_session_basede26.query(Notice)
        .options(joinedload(Notice.related_info))  # single LEFT JOIN, fetched eagerly
        .order_by(Notice.id.asc())
        .offset(offset)
        .limit(page_size)
        .all()
    )  # query #1 only (SQLAlchemy may wrap in a subquery for LIMIT correctness --
       # still one round trip; query_counter reports what actually ran)

    results = [_serialize(notice, notice.related_info) for notice in notices]
    return {"version": "fixed", "page": page, "page_size": page_size,
            "sql_query_count": query_counter.get(), "results": results}
