"""
HW5 Part 2B: domain MCP server over the s7875_rel recall data.

Exactly three tools -- search, detail lookup, one aggregate -- and every
one answers with the same envelope: {ok, data, error}.

Run it in the MCP Inspector from the repo root (MySQL must be running):
    mcp dev mcp_servers/recall_server.py

All logging goes to stderr; stdout carries only the MCP JSON-RPC stream.
"""
import logging
import sys
from pathlib import Path
from typing import Optional

# Make the repo root importable (database.py, models.py, recall_tools/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from recall_tools import tools
from recall_tools.retry import ResilientStore
from recall_tools.store import DbStore

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [s7875-recalls] %(levelname)s %(message)s",
)
log = logging.getLogger("s7875-recalls")

# `dependencies` tells `mcp dev` which extra packages the server needs.
mcp = FastMCP(
    "s7875-recalls",
    dependencies=["sqlalchemy", "pymysql", "python-dotenv", "cryptography", "pydantic"],
)

_store = None


def get_store():
    """Create the database store on first use (so the server starts even if MySQL is slow)."""
    global _store
    if _store is None:
        _store = ResilientStore(DbStore())  # Part 3: timeout + retry on every DB call
    return _store


# The parameters are deliberately loosely typed here: the real checks live in
# recall_tools/tools.py, so a bad value comes back as {ok:false, error:"..."}
# in our own envelope instead of a protocol-level rejection.
@mcp.tool()
def search_notices(query: str, category: Optional[str] = None, limit: int = 5) -> dict:
    """Search recall notices by product or manufacturer name.
    query: at least 2 characters. category (optional): supplyShortage,
    bacterialContamination, foreignMaterial or mislabelling. limit: 1-20."""
    log.info("search_notices query=%r category=%r limit=%r", query, category, limit)
    # An empty category box in the Inspector arrives as "" -- treat it as "no filter".
    return tools.search_notices(get_store(), {"query": query, "category": category or None, "limit": limit})


@mcp.tool()
def get_notice_detail(notice_code: str) -> dict:
    """Look up one recall notice by its code (format RCL-2026-00001) and return all its fields."""
    log.info("get_notice_detail notice_code=%r", notice_code)
    return tools.get_notice_detail(get_store(), {"notice_code": notice_code})


@mcp.tool()
def recall_stats(group_by: str) -> dict:
    """Aggregate: notice count and total units affected per group.
    group_by must be "category" or "manufacturer"."""
    log.info("recall_stats group_by=%r", group_by)
    return tools.recall_stats(get_store(), {"group_by": group_by})


if __name__ == "__main__":
    log.info("starting s7875-recalls MCP server on STDIO")
    mcp.run(transport="stdio")
