from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, foreign
from sqlalchemy.sql import func

from database import Base


class Manufacturer(Base):
    """
    HW5 Part 1: the related entity (plays the "author" role). One
    manufacturer has many recall notices.

    name = primary text field, headquarters = secondary text field,
    code = unique field (format MFR-0001, validated in schemas.py).
    """
    __tablename__ = "manufacturers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    headquarters = Column(String(255), nullable=False)
    code = Column(String(16), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    notices = relationship("Notice", back_populates="maker")


class Notice(Base):
    """
    Primary domain entity (DOMAIN_ID = 3: grocery supply and recall notices).

    HW5 Part 1 changes: the old free-text `manufacturer` column is replaced
    by `manufacturer_id`, a real foreign key to manufacturers.id, plus a
    unique `notice_code`, a numeric `units_affected` (default 0) and
    timestamps. ondelete="RESTRICT" means MySQL itself refuses to delete a
    manufacturer that still has notices.
    """
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product = Column(String(255), nullable=False, index=True)
    notice_code = Column(String(20), nullable=False, unique=True, index=True)
    units_affected = Column(Integer, nullable=False, default=0, server_default="0")
    manufacturer_id = Column(
        Integer, ForeignKey("manufacturers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    maker = relationship("Manufacturer", back_populates="notices")

    @property
    def manufacturer_name(self):
        return self.maker.name if self.maker else None

    # HW4 Part 3 (N+1 demo): see RelatedInfo's docstring for why this is a
    # viewonly relationship without a ForeignKey.
    related_info = relationship(
        "RelatedInfo",
        primaryjoin="Notice.id == foreign(RelatedInfo.notice_id)",
        viewonly=True,
    )


class RelatedInfo(Base):
    """
    HW4 Part 3's "related rows" table, used only for the N+1 demo.
    notice_id is deliberately a plain column, NOT a ForeignKey, so the
    HW4 "before index / after index" EXPLAIN comparison stays real.
    """
    __tablename__ = "related_info"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    notice_id = Column(Integer, nullable=False)
    note = Column(String(255), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash, never plain text


class SessionToken(Base):
    """
    Server-side session row. The browser only ever holds `id` (an opaque
    random token) inside an HttpOnly cookie -- no user data is stored in
    the cookie itself, per HW4 Part 2.
    """
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
