"""HW9 shared config: Section 0 values, Redis client, MySQL engine, banner.

Every Redis key starts with PREFIX (s7875). MySQL is the same s7875_rel database as HW4-HW8.
Override connection details with env vars DATABASE_URL / REDIS_URL if yours differ.
"""

import os
import time

import redis
from sqlalchemy import create_engine

STUDENT_NAME = "Pinal Pawar"
SID4 = 7875
PREFIX = f"s{SID4}"  # s7875
PORT_BASE = 8000 + (SID4 % 900)  # 8675
SEED = SID4
VERIFY_SEED = 260000 + SID4

# Read the repo-root .env (the same file database.py uses) so the real MySQL password is used.
_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(_ENV):
    for _line in open(_ENV):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:hw4devpass@localhost:3306/s7875_rel")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def banner(part: str) -> str:
    return f"===== {STUDENT_NAME} | SID4 {SID4} | PREFIX {PREFIX} | HW9 {part} ====="


def now_ms() -> float:
    return time.perf_counter() * 1000.0
