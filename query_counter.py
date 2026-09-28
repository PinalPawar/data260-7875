"""
HW4 Part 3: counts SQL statements executed on the CURRENT THREAD.

Why not a FastAPI middleware with a contextvar (the first thing I tried):
list-naive/list-fixed are defined as plain `def` (sync) functions, so
FastAPI runs them in a worker thread via anyio's threadpool, using a COPY
of the async context. Anything a contextvar-based counter records inside
that copied context never becomes visible back in the middleware's own
context after the call returns -- it silently read back 0 every time.

Fix: a plain threading.local() counter, reset and read from INSIDE the
endpoint itself (same worker thread for the whole request, since SQLAlchemy
queries in a sync engine execute on that same thread), with the count
returned directly in the JSON body instead of a response header.
"""
import threading

_local = threading.local()


def reset():
    _local.count = 0


def increment():
    _local.count = getattr(_local, "count", 0) + 1


def get():
    return getattr(_local, "count", 0)
