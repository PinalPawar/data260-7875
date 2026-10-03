"""
The three domain tools (HW5 Part 2B): search, detail lookup, aggregate.

Each tool:
  1. validates its input against a Pydantic model (the tool's "contract"),
  2. asks the store for the data,
  3. always returns the same envelope {ok, data, error} -- it never raises.
"""
import logging
import sys
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recall_tools.envelope import fail, ok

# STDIO rule: logs go to stderr only.
log = logging.getLogger("recall_tools")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s [recall_tools] %(levelname)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)

NOTICE_CODE_PATTERN = r"^RCL-\d{4}-\d{5}$"
Category = Literal["supplyShortage", "bacterialContamination", "foreignMaterial", "mislabelling"]
MAX_SEARCH_LIMIT = 20


# --- Input contracts (their JSON Schemas are what Part 3 documents) --------
class SearchNoticesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=100, description="Text to find in product or manufacturer name")
    category: Optional[Category] = Field(default=None, description="Optional category filter")
    limit: int = Field(default=5, ge=1, le=MAX_SEARCH_LIMIT, description="How many notices to return (1-20)")


class NoticeDetailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notice_code: str = Field(pattern=NOTICE_CODE_PATTERN, description="Notice code, format RCL-2026-00001")


class RecallStatsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_by: Literal["category", "manufacturer"] = Field(description="What to group the counts by")


INPUT_MODELS = {
    "search_notices": SearchNoticesInput,
    "get_notice_detail": NoticeDetailInput,
    "recall_stats": RecallStatsInput,
}


def _validation_message(exc: ValidationError) -> str:
    """Turn Pydantic's error list into one short sentence."""
    parts = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "input"
        parts.append(f"{field}: {err['msg']}")
    return "invalid input -- " + "; ".join(parts)


# --- The tools --------------------------------------------------------------
def search_notices(store, inputs: dict) -> dict:
    """Search recall notices by product or manufacturer name."""
    try:
        args = SearchNoticesInput.model_validate(inputs)
    except ValidationError as exc:
        return fail(_validation_message(exc))
    try:
        results = store.search(args.query, args.category, args.limit)
    except Exception as exc:  # storage problem -> clean error, never a crash
        log.error("search_notices storage error: %s", exc)
        return fail(f"storage error: {type(exc).__name__}")
    return ok({"count": len(results), "notices": results})


def get_notice_detail(store, inputs: dict) -> dict:
    """Return every field of one recall notice, looked up by its notice code."""
    try:
        args = NoticeDetailInput.model_validate(inputs)
    except ValidationError as exc:
        return fail(_validation_message(exc))
    try:
        notice = store.detail(args.notice_code)
    except Exception as exc:
        log.error("get_notice_detail storage error: %s", exc)
        return fail(f"storage error: {type(exc).__name__}")
    if notice is None:
        return fail(f"notice {args.notice_code} not found")
    return ok(notice)


def recall_stats(store, inputs: dict) -> dict:
    """Aggregate: number of notices and total units affected per category or manufacturer."""
    try:
        args = RecallStatsInput.model_validate(inputs)
    except ValidationError as exc:
        return fail(_validation_message(exc))
    try:
        groups = store.stats(args.group_by)
    except Exception as exc:
        log.error("recall_stats storage error: %s", exc)
        return fail(f"storage error: {type(exc).__name__}")
    return ok({
        "group_by": args.group_by,
        "groups": groups,
        "total_notices": sum(g["notice_count"] for g in groups),
        "total_units_affected": sum(g["total_units_affected"] for g in groups),
    })


TOOLS = {
    "search_notices": search_notices,
    "get_notice_detail": get_notice_detail,
    "recall_stats": recall_stats,
}
