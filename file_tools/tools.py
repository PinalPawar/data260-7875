"""
HW7 Part 6: six file tools confined to one sandbox directory.

    read_file(root, path, max_lines=None)
    write_file(root, path, content)
    edit_file(root, path, old_text, new_text)        -> includes a short unified diff
    glob_files(root, pattern)
    search_in_files(root, query, file_pattern="**/*")
    bash(root, command, auto_approve=False)          -> runs only if confirm_bash allows it

Every tool returns the HW7 envelope {success, data, error, source, ts}. Paths are resolved
against root and refused if they point outside it (absolute paths, '..', symlinks).
"""

import difflib
import glob as globlib
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Optional

from file_tools.gate import confirm_bash

MAX_READ_LINES = 400
MAX_DIFF_LINES = 20
MAX_MATCHES = 50
MAX_OUTPUT_CHARS = 4000
BASH_TIMEOUT_S = 10


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ok(data, source: Optional[str] = None) -> dict:
    return {"success": True, "data": data, "source": source, "ts": _ts()}


def fail(error: str, source: Optional[str] = None) -> dict:
    return {"success": False, "error": error, "source": source, "ts": _ts()}


def _inside(root: str, path: str) -> str:
    """Absolute real path of path under root, or ValueError if it escapes the sandbox."""
    base = os.path.realpath(root)
    full = os.path.realpath(os.path.join(base, path))
    if full != base and not full.startswith(base + os.sep):
        raise ValueError(f"path is outside the sandbox: {path}")
    return full


def _rel(root: str, full: str) -> str:
    return os.path.relpath(full, os.path.realpath(root))


def read_file(root: str, path: str, max_lines: Optional[int] = None) -> dict:
    """Text of a file, at most max_lines lines (default and cap: MAX_READ_LINES)."""
    try:
        full = _inside(root, path)
        with open(full, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        return fail(str(exc), path)
    limit = min(max_lines or MAX_READ_LINES, MAX_READ_LINES)
    shown = lines[:limit]
    return ok(
        {
            "path": _rel(root, full),
            "content": "\n".join(shown),
            "lines_returned": len(shown),
            "total_lines": len(lines),
            "truncated": len(lines) > limit,
        },
        _rel(root, full),
    )


def write_file(root: str, path: str, content: str) -> dict:
    """Create or overwrite a text file (parent folders are created)."""
    try:
        full = _inside(root, path)
        existed = os.path.exists(full)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
    except (ValueError, OSError) as exc:
        return fail(str(exc), path)
    return ok(
        {"path": _rel(root, full), "bytes": len(content.encode("utf-8")), "created": not existed},
        _rel(root, full),
    )


def edit_file(root: str, path: str, old_text: str, new_text: str) -> dict:
    """Replace exactly one occurrence of old_text and return a short unified diff."""
    try:
        full = _inside(root, path)
        with open(full, encoding="utf-8") as f:
            before = f.read()
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        return fail(str(exc), path)
    count = before.count(old_text) if old_text else 0
    if count != 1:
        return fail(f"old_text must occur exactly once (found {count})", path)
    after = before.replace(old_text, new_text, 1)
    with open(full, "w", encoding="utf-8") as f:
        f.write(after)
    rel = _rel(root, full)
    diff = list(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), f"a/{rel}", f"b/{rel}", n=1, lineterm=""
        )
    )
    short = diff[:MAX_DIFF_LINES] + (["..."] if len(diff) > MAX_DIFF_LINES else [])
    return ok({"path": rel, "diff": "\n".join(short)}, rel)


def glob_files(root: str, pattern: str) -> dict:
    """Files under root matching a glob pattern such as '**/*.py' (sorted, relative)."""
    try:
        _inside(root, pattern.split("*")[0] or ".")
    except ValueError as exc:
        return fail(str(exc), pattern)
    base = os.path.realpath(root)
    hits = sorted(
        _rel(root, p)
        for p in globlib.glob(os.path.join(base, pattern), recursive=True)
        if os.path.isfile(p) and os.path.realpath(p).startswith(base + os.sep)
    )
    return ok({"pattern": pattern, "matches": hits[:MAX_MATCHES], "count": len(hits)}, "sandbox")


def search_in_files(root: str, query: str, file_pattern: str = "**/*") -> dict:
    """Lines containing query (plain text, case-sensitive) in files matching file_pattern."""
    if not query:
        return fail("query is required")
    files = glob_files(root, file_pattern)
    if not files["success"]:
        return files
    matches = []
    for rel in files["data"]["matches"]:
        try:
            with open(_inside(root, rel), encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if query in line:
                        matches.append({"path": rel, "line": n, "text": line.rstrip()[:200]})
        except (OSError, UnicodeDecodeError):
            continue
    files_hit = sorted({m["path"] for m in matches})
    return ok(
        {
            "query": query,
            "file_pattern": file_pattern,
            "matches": matches[:MAX_MATCHES],
            "files": files_hit,
        },
        root,
    )


def bash(root: str, command: str, auto_approve: bool = False) -> dict:
    """Run a shell command in the sandbox, only after the safety gate allows it."""
    verdict = confirm_bash(command, auto_approve)
    if not verdict["allow"]:
        return fail(f"blocked by safety gate: {verdict['reason']}", "bash")
    try:
        proc = subprocess.run(
            ["bash", "-c", command],
            cwd=os.path.realpath(root),
            capture_output=True,
            text=True,
            timeout=BASH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return fail(f"timed out after {BASH_TIMEOUT_S}s", "bash")
    out = re.sub(re.escape(os.path.realpath(root)), ".", proc.stdout + proc.stderr)
    return ok(
        {"exit_code": proc.returncode, "output": out[:MAX_OUTPUT_CHARS], "gate": verdict["reason"]},
        "bash",
    )
