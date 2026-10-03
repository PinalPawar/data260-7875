"""
Database operations for both entities. Functions raise the small exception
classes below instead of HTTPException, so this file knows nothing about
HTTP -- the routers translate them into 404 / 409 responses.
"""
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from models import Manufacturer, Notice
import schemas


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


# --- Manufacturers ----------------------------------------------------------
def list_manufacturers(db_session_basede26: Session, page: int, page_size: int):
    total = db_session_basede26.query(func.count(Manufacturer.id)).scalar()
    items = (
        db_session_basede26.query(Manufacturer)
        .order_by(Manufacturer.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_manufacturer(db_session_basede26: Session, manufacturer_id: int):
    row = db_session_basede26.get(Manufacturer, manufacturer_id)
    if not row:
        raise NotFound(f"Manufacturer {manufacturer_id} not found")
    return row


def create_manufacturer(db_session_basede26: Session, payload: schemas.ManufacturerCreate):
    row = Manufacturer(**payload.model_dump())
    db_session_basede26.add(row)
    try:
        db_session_basede26.commit()
    except IntegrityError:
        db_session_basede26.rollback()
        raise Conflict(f"Manufacturer code {payload.code} already exists")
    db_session_basede26.refresh(row)
    return row


def update_manufacturer(db_session_basede26: Session, manufacturer_id: int,
                        payload: schemas.ManufacturerCreate):
    row = get_manufacturer(db_session_basede26, manufacturer_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    try:
        db_session_basede26.commit()
    except IntegrityError:
        db_session_basede26.rollback()
        raise Conflict(f"Manufacturer code {payload.code} already exists")
    db_session_basede26.refresh(row)
    return row


def delete_manufacturer(db_session_basede26: Session, manufacturer_id: int):
    row = get_manufacturer(db_session_basede26, manufacturer_id)
    # Friendly check first; the RESTRICT foreign key in MySQL is the real
    # guarantee (the IntegrityError branch) if two requests race.
    count = (
        db_session_basede26.query(func.count(Notice.id))
        .filter(Notice.manufacturer_id == manufacturer_id)
        .scalar()
    )
    if count:
        raise Conflict(
            f"Cannot delete manufacturer {manufacturer_id}: it still has {count} notice(s)"
        )
    db_session_basede26.delete(row)
    try:
        db_session_basede26.commit()
    except IntegrityError:
        db_session_basede26.rollback()
        raise Conflict(f"Cannot delete manufacturer {manufacturer_id}: it still has notices")
    return row


def list_notices_for_manufacturer(db_session_basede26: Session, manufacturer_id: int,
                                  skip: int, limit: int):
    get_manufacturer(db_session_basede26, manufacturer_id)  # 404 if it doesn't exist
    return (
        db_session_basede26.query(Notice)
        .options(joinedload(Notice.maker))
        .filter(Notice.manufacturer_id == manufacturer_id)
        .order_by(Notice.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# --- Notices ----------------------------------------------------------------
def list_notices(db_session_basede26: Session, q: str = None, skip: int = 0, limit: int = 50):
    query = db_session_basede26.query(Notice).options(joinedload(Notice.maker))
    if q:
        like = f"%{q}%"
        query = query.join(Notice.maker).filter(
            or_(Notice.product.like(like), Manufacturer.name.like(like))
        )
    return query.order_by(Notice.id.desc()).offset(skip).limit(limit).all()


def get_notice(db_session_basede26: Session, notice_id: int):
    row = db_session_basede26.get(Notice, notice_id)
    if not row:
        raise NotFound(f"Notice {notice_id} not found")
    return row


def _check_manufacturer_exists(db_session_basede26: Session, manufacturer_id: int):
    if not db_session_basede26.get(Manufacturer, manufacturer_id):
        raise NotFound(f"Manufacturer {manufacturer_id} not found")


def create_notice(db_session_basede26: Session, payload: schemas.NoticeCreate):
    _check_manufacturer_exists(db_session_basede26, payload.manufacturer_id)
    row = Notice(**payload.model_dump())
    db_session_basede26.add(row)
    try:
        db_session_basede26.commit()
    except IntegrityError:
        db_session_basede26.rollback()
        raise Conflict(f"Notice code {payload.notice_code} already exists")
    db_session_basede26.refresh(row)
    return row


def update_notice(db_session_basede26: Session, notice_id: int, payload: schemas.NoticeCreate):
    row = get_notice(db_session_basede26, notice_id)
    _check_manufacturer_exists(db_session_basede26, payload.manufacturer_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    try:
        db_session_basede26.commit()
    except IntegrityError:
        db_session_basede26.rollback()
        raise Conflict(f"Notice code {payload.notice_code} already exists")
    db_session_basede26.refresh(row)
    return row


def delete_notice(db_session_basede26: Session, notice_id: int):
    row = get_notice(db_session_basede26, notice_id)
    db_session_basede26.delete(row)
    db_session_basede26.commit()
