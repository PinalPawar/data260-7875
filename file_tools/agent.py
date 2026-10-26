"""
HW7 Part 6: a small LangGraph ReAct agent over the six file tools, bound to one sandbox.

The model never gets a way to confirm a bash command: bash always runs with
auto_approve=False, so anything outside SAFE_PREFIXES or on the deny-list is refused.
"""

import json
import time
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from file_tools import tools as ft

SYSTEM = (
    "You are a file assistant working inside one sandbox folder; all paths are relative to it. "
    "Call exactly one tool per turn and wait for its result. Answer only from tool results. "
    "When you show a file, copy its content exactly as read_file returned it."
)


class ReadArgs(BaseModel):
    path: str = Field(description="File path relative to the sandbox")
    max_lines: Optional[int] = Field(default=None, description="Return at most this many lines")


class WriteArgs(BaseModel):
    path: str
    content: str


class EditArgs(BaseModel):
    path: str
    old_text: str = Field(description="Exact text to replace (must occur once)")
    new_text: str


class GlobArgs(BaseModel):
    pattern: str = Field(description="Glob pattern, e.g. '**/*.py'")


class SearchArgs(BaseModel):
    query: str = Field(description="Plain text to find")
    file_pattern: str = Field(default="**/*", description="Glob of files to search, e.g. '*.py'")


class BashArgs(BaseModel):
    command: str = Field(description="Shell command; checked by the safety gate first")


def build_tools(root: str) -> list:
    def j(env):
        return json.dumps(env)

    def read(path, max_lines=None):
        return j(ft.read_file(root, path, max_lines))

    def write(path, content):
        return j(ft.write_file(root, path, content))

    def edit(path, old_text, new_text):
        return j(ft.edit_file(root, path, old_text, new_text))

    def globf(pattern):
        return j(ft.glob_files(root, pattern))

    def search(query, file_pattern="**/*"):
        return j(ft.search_in_files(root, query, file_pattern))

    def sh(command):
        return j(ft.bash(root, command, auto_approve=False))

    spec = [
        (read, "read_file", ReadArgs, "Read a text file (optionally only max_lines lines)."),
        (write, "write_file", WriteArgs, "Create or overwrite a text file."),
        (edit, "edit_file", EditArgs, "Replace one exact text occurrence; returns a short diff."),
        (globf, "glob_files", GlobArgs, "List files matching a glob pattern."),
        (search, "search_in_files", SearchArgs, "Find lines containing text in matching files."),
        (sh, "bash", BashArgs, "Run a shell command in the sandbox (safety-gated)."),
    ]
    return [
        StructuredTool.from_function(f, name=n, args_schema=a, description=d) for f, n, a, d in spec
    ]


def run_file_agent(root: str, instruction: str, model, recursion_limit: int = 16) -> dict:
    """Run one instruction; return the timeline, the final answer, steps, time, stop reason."""
    from langgraph.errors import GraphRecursionError
    from langgraph.prebuilt import create_react_agent

    from bike_agent.agent import _record_update

    graph = create_react_agent(model, build_tools(root), prompt=SYSTEM)
    timeline, started, stop = [], time.perf_counter(), "final_answer"
    try:
        for update in graph.stream(
            {"messages": [HumanMessage(content=instruction)]},
            config={"recursion_limit": recursion_limit},
            stream_mode="updates",
        ):
            _record_update(update, timeline, started)
    except GraphRecursionError:
        stop = "step_limit"
    except Exception as exc:
        stop = f"error: {type(exc).__name__}: {exc}"[:200]
    finals = [e for e in timeline if e["type"] == "final"]
    return {
        "timeline": timeline,
        "final_text": finals[-1]["text"] if finals else "",
        "steps": sum(e["type"] == "tool_call" for e in timeline),
        "total_ms": round((time.perf_counter() - started) * 1000),
        "stop_reason": stop,
    }
