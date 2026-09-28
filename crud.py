from sqlalchemy.orm import Session

from models import Notice
import schemas


def list_notices(db_session_basede26: Session):
    return db_session_basede26.query(Notice).order_by(Notice.id.asc()).all()


def get_notice(db_session_basede26: Session, notice_id: int):
    return db_session_basede26.query(Notice).filter(Notice.id == notice_id).first()


def create_notice(db_session_basede26: Session, payload: schemas.NoticeCreate):
    notice = Notice(**payload.dict())
    db_session_basede26.add(notice)
    db_session_basede26.commit()
    db_session_basede26.refresh(notice)
    return notice


def update_notice(db_session_basede26: Session, notice_id: int, payload: schemas.NoticeCreate):
    notice = get_notice(db_session_basede26, notice_id)
    if not notice:
        return None
    for key, value in payload.dict().items():
        setattr(notice, key, value)
    db_session_basede26.commit()
    db_session_basede26.refresh(notice)
    return notice


def delete_notice(db_session_basede26: Session, notice_id: int):
    notice = get_notice(db_session_basede26, notice_id)
    if not notice:
        return None
    db_session_basede26.delete(notice)
    db_session_basede26.commit()
    return notice
