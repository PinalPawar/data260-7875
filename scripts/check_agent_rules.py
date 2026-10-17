"""HW6 Part 4.4 - verify that code follows the instructions in AGENT.md.

    python scripts/check_agent_rules.py

Checks the Part 4 code (file_memory/, file_memory_chat.py,
scripts/consolidate_memory.py) against the AGENT.md rules that can be tested
automatically, and writes reports/hw06/raw/agent_rules_check.json.
The function singled out for the report is needs_consolidation().
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = sorted((ROOT / "file_memory").glob("*.py"))
ENTRY_POINTS = [ROOT / "file_memory_chat.py", ROOT / "scripts" / "consolidate_memory.py"]
TEST_FILE = ROOT / "tests" / "test_file_memory.py"
FOCUS = "needs_consolidation"
SNAKE = re.compile(r"^_?[a-z][a-z0-9_]*$")
SECRET = re.compile(r"(password|api_key|secret|token)\s*=\s*['\"][^'\"]+['\"]", re.I)
PAID_SDKS = {"openai", "anthropic", "google.generativeai"}


def function_checks(fn: ast.FunctionDef, is_library: bool) -> dict:
    """Check one function against the AGENT.md coding conventions."""
    args = [a for a in fn.args.args + fn.args.kwonlyargs if a.arg not in ("self", "cls")]
    prints = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "print"]
    bare = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler) and n.type is None]
    return {
        "type hints on all parameters": all(a.annotation is not None for a in args),
        "return type hint": fn.returns is not None,
        "docstring": ast.get_docstring(fn) is not None,
        "snake_case name": bool(SNAKE.match(fn.name)),
        "at most 40 lines": (fn.end_lineno - fn.lineno + 1) <= 40,
        "no print() in library code": not (is_library and prints),
        "no bare except": not bare,
    }


def file_checks(path: Path) -> dict:
    """Prohibited-actions checks for a whole file."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    return {"no hardcoded secrets": not SECRET.search(text),
            "no paid model SDK imported": not (imports & PAID_SDKS)}


def check_all() -> dict:
    """Run every check and return the results."""
    results = {"functions": [], "files": [], "tests": {}}
    for path in LIBRARY + ENTRY_POINTS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(ROOT))
        results["files"].append({"file": rel, "checks": file_checks(path)})
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            checks = function_checks(fn, path in LIBRARY)
            results["functions"].append({"file": rel, "function": fn.name,
                                         "lines": fn.end_lineno - fn.lineno + 1, "checks": checks})
    test_text = TEST_FILE.read_text(encoding="utf-8") if TEST_FILE.exists() else ""
    results["tests"] = {"offline test script in tests/": TEST_FILE.exists(),
                        f"{FOCUS} is tested": FOCUS in test_text}
    return results


def main() -> None:
    """Command-line entry point: print a summary and save JSON."""
    res = check_all()
    failures = [(f["file"], f["function"], k) for f in res["functions"] for k, ok in f["checks"].items() if not ok]
    failures += [(f["file"], "-", k) for f in res["files"] for k, ok in f["checks"].items() if not ok]
    failures += [("tests", "-", k) for k, ok in res["tests"].items() if not ok]
    focus = next(f for f in res["functions"] if f["function"] == FOCUS)
    print(f"AGENT.md rule check: {len(res['functions'])} functions in {len(res['files'])} files")
    print(f"\nFocus function {FOCUS}() ({focus['file']}, {focus['lines']} lines):")
    for rule, ok in focus["checks"].items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {rule}")
    for rule, ok in res["tests"].items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {rule}")
    print(f"\nAll functions/files: {len(failures)} rule violation(s)")
    for item in failures:
        print("  FAIL", " | ".join(item))
    res["violations"] = [" | ".join(i) for i in failures]
    out = ROOT / "reports" / "hw06" / "raw" / "agent_rules_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"Saved {out.relative_to(ROOT)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
