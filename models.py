from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import relationship, foreign
from sqlalchemy.sql import func

from database import Base


class Notice(Base):
    """
    Primary domain entity (DOMAIN_ID = 3: grocery supply and recall notices).
    `product` is the primary field, `manufacturer` the secondary field
    required by HW4 Part 2; email/description/category carry over from the
    schema already established in HW1/HW2 (DOMAIN_SCHEMA.md).
    """
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product = Column(String(255), nullable=False, index=True)
    manufacturer = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(64), nullable=False)

    # Lets the "fixed" list endpoint fetch a notice and its related row(s)
    # in one JOIN query via joinedload(), instead of one query per notice.
    # primaryjoin is spelled out explicitly (rather than relying on a
    # ForeignKey) because related_info.notice_id has no FK constraint --
    # see RelatedInfo's docstring for why. viewonly=True since this
    # relationship isn't backed by a constraint SQLAlchemy can safely
    # cascade writes through.
    related_info = relationship(
        "RelatedInfo",
        primaryjoin="Notice.id == foreign(RelatedInfo.notice_id)",
        viewonly=True,
    )


class RelatedInfo(Base):
    """
    Part 3's "related rows" table: extra per-notice detail (e.g. an
    inspection/lab note) used purely to create the classic N+1 pattern on
    the notices list endpoint. Not a fully modeled entity yet -- HW4 says
    a proper related entity with full CRUD comes in a later homework.

    notice_id is deliberately a plain column, NOT a ForeignKey: InnoDB
    auto-creates a supporting index the instant a column is declared as a
    foreign key, which would make Part 3 step 8's "before" EXPLAIN already
    fast -- there'd be nothing left to demonstrate an index fixing. Skipping
    the FK constraint (acceptable given the PDF's own "just test data for
    now" framing) keeps the "before: full scan / after: index" story real.
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
    password_hash = Column(String(255), nullable=False)


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
