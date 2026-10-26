"""
HW7 Part 4: the three MRKL tools as pure functions with JSON schemas.

Every tool returns the common envelope
    {"success": bool, "data"?: any, "error"?: str, "source"?: str, "ts"?: str}
and never raises: bad input, a failed fetch or a rejected query all come back as
success = False with a short error.

  csv_sql(sql)                       read-only SELECT over the uploaded trips (SQLite in memory)
  policy_retriever(url, query, k=4)  quotable snippets from the pricing page (snapshotted)
  calculator(expression, units)      safe arithmetic over a strict whitelist (no eval)

The uploaded CSV is loaded into one table, trips, holding every original column plus four
helper columns computed at load time: duration_min, bike ('classic' or 'ebike'),
ride_month ('YYYY-MM') and ride_week ('YYYY-Www', ISO week).
"""

import ast
import csv
import io
import operator
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from bike_agent.pricing_page import PricingSnapshotCache, rank

CSV_SOURCE = "uploaded.csv"
MAX_ROWS_RETURNED = 5000  # app-side callers (the reference check) get every row
MODEL_MAX_ROWS = 24  # rows shown to the model, so long tables cannot overflow its context
CALC_PATTERN = re.compile(r"^[0-9+\-*/().\s]+$")

# --------------------------------------------------------------------------- JSON schemas
CSV_SQL_SCHEMA = {
    "name": "csv_sql",
    "description": "Run ONE read-only SELECT over table `trips` (the uploaded trip CSV). Columns: "
    "the original CSV columns plus duration_min, bike ('classic'|'ebike'), ride_month "
    "('YYYY-MM'), ride_week ('YYYY-Www').",
    "input": {
        "type": "object",
        "required": ["sql"],
        "additionalProperties": False,
        "properties": {"sql": {"type": "string", "description": "A single SELECT statement"}},
    },
    "output": {
        "type": "object",
        "properties": {
            "rows": {"type": "array", "items": {"type": "object"}},
            "row_count": {"type": "number"},
            "source": {"const": CSV_SOURCE},
        },
    },
}
POLICY_RETRIEVER_SCHEMA = {
    "name": "policy_retriever",
    "description": "Fetch the pricing page at `url` and return the k snippets that best match "
    "`query` (membership price, included minutes, per-minute rates, unlock fees, overage).",
    "input": {
        "type": "object",
        "required": ["url", "query"],
        "additionalProperties": False,
        "properties": {
            "url": {"type": "string"},
            "query": {"type": "string"},
            "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4},
        },
    },
    "output": {
        "type": "object",
        "properties": {
            "passages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source": {"type": "string"},
                        "score": {"type": "number"},
                    },
                },
            }
        },
    },
}
CALCULATOR_SCHEMA = {
    "name": "calculator",
    "description": "Evaluate arithmetic with numbers, + - * / and parentheses only.",
    "input": {
        "type": "object",
        "required": ["expression"],
        "additionalProperties": False,
        "properties": {
            "expression": {"type": "string", "pattern": CALC_PATTERN.pattern},
            "units": {"type": "string"},
        },
    },
    "output": {
        "type": "object",
        "properties": {"value": {"type": "number"}, "units": {"type": "string"}},
    },
}
SCHEMAS = [CSV_SQL_SCHEMA, POLICY_RETRIEVER_SCHEMA, CALCULATOR_SCHEMA]


def _now() -> str:
    """UTC timestamp for the envelope."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ok(data: Any, source: Optional[str] = None) -> dict:
    """Success envelope."""
    return {"success": True, "data": data, "source": source, "ts": _now()}


def fail(error: str, source: Optional[str] = None) -> dict:
    """Failure envelope."""
    return {"success": False, "error": str(error), "source": source, "ts": _now()}


# --------------------------------------------------------------------------- trips database
def _parse_time(value: str) -> Optional[datetime]:
    """Parse the timestamp formats seen in Bay Wheels files; None if blank or unknown."""
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime((value or "").strip()[:26], fmt)
        except ValueError:
            continue
    return None


def _helper_values(row: dict) -> list:
    """duration_min, bike, ride_month, ride_week for one CSV row (None where unknown)."""
    start, end = _parse_time(row.get("started_at", "")), _parse_time(row.get("ended_at", ""))
    minutes = round((end - start).total_seconds() / 60.0, 3) if start and end else None
    kind = (row.get("rideable_type") or "").strip().lower()
    bike = "ebike" if kind == "electric_bike" else ("classic" if kind else None)
    if start is None:
        return [minutes, bike, None, None]
    year, week, _ = start.isocalendar()
    return [minutes, bike, start.strftime("%Y-%m"), f"{year}-W{week:02d}"]


def load_trips(csv_text: str) -> sqlite3.Connection:
    """Load the uploaded CSV into an in-memory SQLite table `trips` (all columns as text)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    columns = [c.strip() for c in reader.fieldnames or []]
    if not columns:
        raise ValueError("the uploaded CSV has no header row")
    helpers = ["duration_min", "bike", "ride_month", "ride_week"]
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    names = ", ".join(f'"{c}"' for c in columns + helpers)
    conn.execute(f"CREATE TABLE trips ({names})")
    marks = ", ".join("?" for _ in columns + helpers)
    rows = ([r.get(c) for c in columns] + _helper_values(r) for r in reader)
    conn.executemany(f"INSERT INTO trips VALUES ({marks})", rows)
    conn.commit()
    return conn


# --------------------------------------------------------------------------- csv_sql
_READ_ONLY_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}


def _read_only_authorizer(action: int, *args) -> int:
    """SQLite authorizer: allow reads only; every write, schema change or PRAGMA is denied."""
    return sqlite3.SQLITE_OK if action in _READ_ONLY_ACTIONS else sqlite3.SQLITE_DENY


def check_select(sql: str) -> Optional[str]:
    """None if sql is a single SELECT (or WITH ... SELECT), else the reason it is refused."""
    stripped = (sql or "").strip().rstrip(";").strip()
    if not stripped:
        return "empty query"
    if ";" in stripped:
        return "only one statement is allowed"
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        return "only SELECT queries are allowed"
    return None


def csv_sql(
    conn: sqlite3.Connection, sql: str, guard: str = "strict", max_rows: int = MAX_ROWS_RETURNED
) -> dict:
    """Run one read-only SELECT. guard='strict' (default) enforces the contract at the tool
    boundary twice: a single-SELECT check plus a SQLite authorizer that denies any write.
    guard='off' exists only for the Part 5 'before defenses' baseline."""
    if guard == "strict":
        problem = check_select(sql)
        if problem:
            return fail(f"query refused: {problem}", CSV_SOURCE)
        conn.set_authorizer(_read_only_authorizer)
    try:
        if guard == "strict":
            cursor = conn.execute(sql.strip().rstrip(";"))
        else:  # Part 5 baseline: runs whatever the model sends, including writes
            cursor = _run_unguarded(conn, sql)
        names = [d[0] for d in cursor.description or []]
        rows = [dict(zip(names, r)) for r in cursor.fetchall()]
    except sqlite3.Error as exc:
        return fail(f"SQL error: {exc}{_placeholder_hint(str(exc))}", CSV_SOURCE)
    finally:
        conn.set_authorizer(None)
    data = {"rows": rows[:max_rows], "row_count": len(rows), "source": CSV_SOURCE}
    if len(rows) > max_rows:
        data["truncated_to"] = max_rows
        data["note"] = (
            f"Only the first {max_rows} of {len(rows)} rows are shown; the app builds the "
            "full table. Do not re-run this query - continue with the next step."
        )
    return ok(data, CSV_SOURCE)


def _placeholder_hint(error: str) -> str:
    """Repair hint when the model left a CAPITALISED placeholder (e.g. FREE_MIN) in its SQL."""
    m = re.search(r"no such column: ([A-Z][A-Z_]+)\b", error)
    if m:
        return (
            f" -- {m.group(1)} is a placeholder: replace it with the number from the "
            "pricing passages and run the query again"
        )
    return ""


def _run_unguarded(conn: sqlite3.Connection, sql: str) -> sqlite3.Cursor:
    """Execute every statement in sql and return the last cursor (no read-only contract)."""
    cursor = conn.cursor()
    statements = [s for s in sql.split(";") if s.strip()]
    for statement in statements:
        cursor = conn.execute(statement)
    conn.commit()
    return cursor


# --------------------------------------------------------------------------- policy_retriever
def policy_retriever(cache: PricingSnapshotCache, url: str, query: str, k: int = 4) -> dict:
    """Top-k quotable snippets from the pricing page for query, from this run's snapshot."""
    if not url or not query:
        return fail("both url and query are required")
    try:
        k = max(1, min(int(k), 10))
        page = cache.get(url)
    except Exception as exc:  # network error, bad URL, unreadable page: clean failure
        return fail(f"could not fetch pricing page: {type(exc).__name__}: {exc}", url)
    meta = page["meta"]
    source = f"{meta['final_url']} (captured {meta['accessed_utc']})"
    passages = [
        {"text": p["text"], "source": source, "score": p["score"]}
        for p in rank(page["snippets"], query, k)
    ]
    return ok({"passages": passages, "snapshot_sha256": meta["sha256_text"]}, source)


# --------------------------------------------------------------------------- calculator
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _evaluate(node: ast.AST) -> float:
    """Walk the parsed expression, allowing only numbers and + - * / (no names, calls, **)."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.operand))
    raise ValueError(f"unsupported element {type(node).__name__}")


def calculator(expression: str, units: Optional[str] = None) -> dict:
    """Safe arithmetic: whitelist regex first, then an AST walk; never calls eval()."""
    if not expression or not CALC_PATTERN.match(expression):
        return fail("expression may contain only digits, + - * / ( ) . and spaces")
    try:
        value = _evaluate(ast.parse(expression, mode="eval"))
    except ZeroDivisionError:
        return fail("division by zero")
    except (SyntaxError, ValueError) as exc:
        return fail(f"invalid expression: {exc}")
    data = {"value": round(value, 4)}
    if units:
        data["units"] = units
    return ok(data, "calculator")
