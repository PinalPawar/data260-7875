"""
HW7 Parts 2-3: deterministic checks for the fixed verification tasks.

verify_task(task, result) looks only at the tool trace and the final answer that
run_agent() returned. It never calls a model, so the same run always gets the same
verdict. Each check is objective: which tools ran, in what order, with arguments
that came from earlier tool results, and whether the answer cites those results.
"""

import json
import os
import re

CASES_PATH = os.path.join("reports", "hw07", "cases", "verification_tasks.json")
CODE_RE = re.compile(r"RCL-\d{4}-\d{5}")
# Any identifier shaped like a code: capitals/digits joined by dashes and containing a digit,
# e.g. RCL-2026-04983 or invented ones such as PEANUT-BUTTER-2023-001 / PEANUTBUTTER-1234.
CODE_LIKE_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")


def load_cases(path: str = CASES_PATH) -> dict:
    """Read the fixed tasks and the error case from the cases JSON file."""
    with open(path) as f:
        return json.load(f)


def _ok_calls(result: dict, tool: str) -> list:
    """Successful invocations of one tool, in order."""
    return [t for t in result["trace"] if t["tool"] == tool and t["result"]["ok"]]


def _seen_codes(result: dict) -> set:
    """Every notice code that appeared in any tool result (or tool input)."""
    return set(CODE_RE.findall(json.dumps(result["trace"])))


def unsupported_claims(result: dict) -> list:
    """Code-like IDs in the answer that never appeared in any tool call or result."""
    seen = json.dumps(result["trace"])
    found = CODE_LIKE_RE.findall(result.get("answer", ""))
    return sorted({c for c in found if any(ch.isdigit() for ch in c) and c not in seen})


def _check(name: str, passed: bool, detail: str) -> dict:
    """One named check with its outcome and a short reason."""
    return {"check": name, "passed": bool(passed), "detail": detail}


def _search_then_detail(task: dict, result: dict) -> list:
    """Task A: search for the term, then look up the FIRST search result."""
    searches = [
        s
        for s in _ok_calls(result, "search_notices")
        if task["search_term"] in s["arguments"].get("query", "").lower()
        and s["result"]["data"]["notices"]
    ]
    first = searches[0]["result"]["data"]["notices"][0]["notice_code"] if searches else None
    details = [d["arguments"]["notice_code"] for d in _ok_calls(result, "get_notice_detail")]
    return [
        _check("search_ran", bool(searches), f"search for '{task['search_term']}' with results"),
        _check(
            "detail_of_first_result", first in details, f"first result {first}; looked up {details}"
        ),
        _check(
            "answer_cites_code",
            bool(first) and first in result["answer"],
            f"answer mentions {first}",
        ),
    ]


def _aggregate_then_example(task: dict, result: dict) -> list:
    """Task B: stats by category, then an example notice from the top category."""
    stats = [
        s
        for s in _ok_calls(result, "recall_stats")
        if s["arguments"].get("group_by") == task["group_by"]
    ]
    top = stats[0]["result"]["data"]["groups"][0]["group"] if stats else None
    examples = [
        n["notice_code"]
        for s in _ok_calls(result, "search_notices")
        for n in s["result"]["data"]["notices"]
        if n["category"] == top
    ]
    examples += [
        d["result"]["data"]["notice_code"]
        for d in _ok_calls(result, "get_notice_detail")
        if d["result"]["data"]["category"] == top
    ]
    answer = result["answer"]
    return [
        _check("aggregate_ran", bool(stats), f"recall_stats(group_by={task['group_by']})"),
        _check("example_from_top_group", bool(examples), f"top={top}; examples={examples[:3]}"),
        _check(
            "answer_cites_both",
            bool(top) and top.lower() in answer.lower() and any(c in answer for c in examples),
            "answer names the top group and an example code",
        ),
    ]


def _pair_facts(result: dict, codes: list) -> dict:
    """units_affected and manufacturer of each code, as get_notice_detail returned them."""
    facts = {}
    for d in _ok_calls(result, "get_notice_detail"):
        data = d["result"]["data"]
        if data["notice_code"] in codes:
            facts[data["notice_code"]] = (data["units_affected"], data["manufacturer"]["name"])
    return facts


def _states_facts(answer: str, facts: dict) -> bool:
    """True when the answer gives every notice's units (commas ignored) and manufacturer."""
    text = answer.replace(",", "").lower()
    return bool(facts) and all(
        re.search(rf"\b{units}\b", text) and maker.lower() in text
        for units, maker in facts.values()
    )


def _compare_two(task: dict, result: dict) -> list:
    """Task C: look up the FIRST TWO search results and compare those two from their details.

    Revised twice after reading answers in Part 3. Version 1 accepted any two looked-up codes
    (false acceptance). Version 2 rejected any answer mentioning other codes, which rejected a
    correct answer (false rejection) and still accepted answers that cited both codes with the
    wrong numbers. This version checks the substance: both notices' units and manufacturers.
    """
    searches = [
        s
        for s in _ok_calls(result, "search_notices")
        if task["search_term"] in s["arguments"].get("query", "").lower()
        and len(s["result"]["data"]["notices"]) >= 2
    ]
    first_two = (
        [n["notice_code"] for n in searches[0]["result"]["data"]["notices"][:2]] if searches else []
    )
    looked_up = {d["arguments"]["notice_code"] for d in _ok_calls(result, "get_notice_detail")}
    facts = _pair_facts(result, first_two)
    cited = set(CODE_RE.findall(result["answer"]))
    return [
        _check("search_ran", bool(searches), f"search for '{task['search_term']}' with 2+ results"),
        _check(
            "two_detail_lookups",
            bool(first_two) and set(first_two) <= looked_up,
            f"first two {first_two}; looked up {sorted(looked_up)}",
        ),
        _check(
            "answer_cites_both",
            bool(first_two) and set(first_two) <= cited,
            f"answer mentions {sorted(cited)}",
        ),
        _check(
            "answer_reports_pair_facts",
            len(facts) == 2 and _states_facts(result["answer"], facts),
            f"needs units and manufacturer of each: {facts}",
        ),
    ]


def _nonexistent_id(task: dict, result: dict) -> list:
    """Error case: the lookup fails cleanly and the agent says so instead of inventing data."""
    lookups = [
        t
        for t in result["trace"]
        if t["tool"] == "get_notice_detail"
        and t["arguments"].get("notice_code") == task["notice_code"]
    ]
    error = lookups[0]["result"]["error"] if lookups else None
    return [
        _check("lookup_attempted", bool(lookups), f"get_notice_detail({task['notice_code']})"),
        _check("useful_error_returned", bool(error) and "not found" in error, f"error={error!r}"),
        _check(
            "clean_stop", result["stop_reason"] == "final_answer", f"stop={result['stop_reason']}"
        ),
    ]


CHECKERS = {
    "search_then_detail": _search_then_detail,
    "aggregate_then_example": _aggregate_then_example,
    "compare_two": _compare_two,
    "nonexistent_id": _nonexistent_id,
}


def verify_task(task: dict, result: dict) -> dict:
    """Run every check for one task. passed = all checks pass and no unsupported codes."""
    try:
        checks = CHECKERS[task["kind"]](task, result)
    except (KeyError, TypeError, IndexError) as exc:  # odd trace shape counts as a failed check
        checks = [_check("trace_readable", False, f"{type(exc).__name__}: {exc}")]
    made_up = unsupported_claims(result)
    checks.append(_check("no_unsupported_codes", not made_up, f"unsupported={made_up}"))
    return {
        "task_id": task["id"],
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "unsupported_claims": made_up,
    }
