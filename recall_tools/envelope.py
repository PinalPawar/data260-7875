"""
The one response envelope used by every domain tool (HW5 Part 2B), and
reused unchanged by execute_tool in Part 4:

    {"ok": true,  "data": <result>, "error": null}      on success
    {"ok": false, "data": null,     "error": "<why>"}   on any failure
"""
from typing import Any


def ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def fail(error: str) -> dict:
    return {"ok": False, "data": None, "error": str(error)}
