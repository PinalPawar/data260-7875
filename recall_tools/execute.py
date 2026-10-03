"""
HW5 Parts 4-5: the single safe entry point for the three domain tools.

    execute_tool(name, inputs) -> JSON string of {ok, data, error}

The Part 5 agent calls every tool through this one function. It never
raises: an unknown tool, bad inputs, a safety-rule violation, a storage
failure or any unexpected exception all come back as
{"ok": false, "data": null, "error": "..."}.
"""
import json
import re

from recall_tools import tools
from recall_tools.envelope import fail

_default_store = None

# --- Part 5 safety rule -----------------------------------------------------
# Recall notices carry the contact e-mail of a named QA employee. The tools
# exist to answer questions about products and recalls, not to look people
# up, so any tool input that contains an e-mail address is refused before
# the tool runs.
SAFETY_PREFIX = "safety rule:"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def safety_violation(name, inputs):
    """Return a reason string if this call breaks the safety rule, else None."""
    for value in inputs.values():
        if isinstance(value, str) and _EMAIL.search(value):
            return (f"{SAFETY_PREFIX} looking up notices by a person's e-mail address is not "
                    f"allowed (contact details are private); search by product or manufacturer instead")
    return None


def _get_default_store():
    """The real database, behind the Part 3 timeout + retry wrapper (built on first use)."""
    global _default_store
    if _default_store is None:
        from recall_tools.retry import ResilientStore
        from recall_tools.store import DbStore
        _default_store = ResilientStore(DbStore())
    return _default_store


def execute_tool(name, inputs, store=None) -> str:
    """
    Run one domain tool and return its envelope as a JSON string.

    `store` is optional dependency injection: tests pass an InMemoryStore so
    they run offline; when it is omitted the real MySQL store is used.
    """
    try:
        if name not in tools.TOOLS:
            result = fail(f"unknown tool '{name}' -- available tools: {', '.join(tools.TOOLS)}")
        elif not isinstance(inputs, dict):
            result = fail("invalid input -- inputs must be a JSON object")
        elif (reason := safety_violation(name, inputs)) is not None:
            result = fail(reason)  # blocked: the tool is never called
        else:
            result = tools.TOOLS[name](store if store is not None else _get_default_store(), inputs)
    except Exception as exc:  # last line of defence: never crash the caller
        result = fail(f"unexpected error: {type(exc).__name__}")
    return json.dumps(result)
