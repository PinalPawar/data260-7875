import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

# PREFIX = s7875 (SID4 = 7875, HW4 Section 0) -> database name s7875_rel.
# Override via .env locally; this default matches the dev MySQL used while
# building/testing this homework.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:hw4devpass@localhost:3306/s7875_rel",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db_session_basede26():
    """
    FastAPI dependency that yields one SQLAlchemy ORM session per request
    and always closes it afterwards.

    Named `db_session_basede26` (not the usual `db`) because HW4's Part 2
    instructions require the database connection/session variable to be
    named exactly that.
    """
    db_session_basede26 = SessionLocal()
    try:
        yield db_session_basede26
    finally:
        db_session_basede26.close()
