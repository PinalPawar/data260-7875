"""
HW7 Part 2: offline tests for the hand-written agent loop and the task verifier.

    python tests/test_hw07_agent_loop.py

Plain asserts, no framework. A scripted chat function stands in for the model and
an InMemoryStore stands in for MySQL, so the suite needs no Ollama, no network and
no database, and gives the same result every run.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from recall_tools import agent_loop  # noqa: E402
from recall_tools.agent_loop import run_agent, validate_call  # noqa: E402
from recall_tools.store import InMemoryStore  # noqa: E402
from recall_tools.task_checks import verify_task  # noqa: E402

agent_loop.log.disabled = True  # keep test output short

MFR_A = {"code": "MFR-0001", "name": "GreenFields Co", "headquarters": "Salinas, CA"}
MFR_B = {"code": "MFR-0002", "name": "ACME Foods", "headquarters": "Fresno, CA"}
NOTICES = [
    {
        "notice_code": "RCL-2026-00001",
        "product": "Frozen Spinach",
        "category": "bacterialContamination",
        "units_affected": 100,
        "description": "Listeria in lot L1.",
        "contact_email": "qa@g.com",
        "manufacturer": MFR_A,
    },
    {
        "notice_code": "RCL-2026-00002",
        "product": "Peanut Butter",
        "category": "mislabelling",
        "units_affected": 40,
        "description": "Undeclared allergen.",
        "contact_email": "qa@a.com",
        "manufacturer": MFR_B,
    },
    {
        "notice_code": "RCL-2026-00003",
        "product": "Peanut Butter Cups",
        "category": "mislabelling",
        "units_affected": 75,
        "description": "Wrong label.",
        "contact_email": "qa@a.com",
        "manufacturer": MFR_A,
    },
]
TASK_A = {"id": "A", "kind": "search_then_detail", "search_term": "spinach", "min_tool_calls": 2}
TASK_B = {"id": "B", "kind": "aggregate_then_example", "group_by": "category", "min_tool_calls": 2}
TASK_C = {"id": "C", "kind": "compare_two", "search_term": "peanut", "min_tool_calls": 3}
TASK_E = {"id": "E", "kind": "nonexistent_id", "notice_code": "RCL-2026-99999"}


def call(name, **arguments):
    """One structured tool call as the model adapter returns it."""
    return {"name": name, "arguments": arguments}


def scripted(*replies):
    """A chat function that plays back replies; the last one repeats forever."""
    state = {"i": 0, "seen": []}

    def chat(messages, tools):
        state["seen"].append([dict(m) for m in messages])
        reply = replies[min(state["i"], len(replies) - 1)]
        state["i"] += 1
        if isinstance(reply, str):
            return {"content": reply, "tool_calls": [], "input_tokens": 10, "output_tokens": 5}
        return {"content": "", "tool_calls": list(reply), "input_tokens": 10, "output_tokens": 5}

    chat.state = state
    return chat


def run(*replies, **kwargs):
    return run_agent("question", chat=scripted(*replies), store=InMemoryStore(NOTICES), **kwargs)


def test_task_a_two_step_chain():
    r = run(
        [call("search_notices", query="spinach")],
        [call("get_notice_detail", notice_code="RCL-2026-00001")],
        "RCL-2026-00001 is Frozen Spinach by GreenFields Co: Listeria in lot L1.",
    )
    assert r["stop_reason"] == "final_answer" and r["tool_calls"] == 2
    assert verify_task(TASK_A, r)["passed"]


def test_task_b_aggregate_then_example():
    r = run(
        [call("recall_stats", group_by="category")],
        [call("search_notices", query="peanut", category="mislabelling")],
        "mislabelling has the most notices; example RCL-2026-00002.",
    )
    assert verify_task(TASK_B, r)["passed"]


def test_task_c_compare_needs_two_lookups():
    good = run(
        [call("search_notices", query="peanut butter")],
        [call("get_notice_detail", notice_code="RCL-2026-00002")],
        [call("get_notice_detail", notice_code="RCL-2026-00003")],
        "RCL-2026-00003 (75 units, GreenFields Co) beat RCL-2026-00002 (40 units, ACME Foods).",
    )
    assert good["tool_calls"] == 3 and verify_task(TASK_C, good)["passed"]
    lost = run(
        [call("search_notices", query="peanut butter")], "RCL-2026-00002 and RCL-2026-00003 exist."
    )
    verdict = verify_task(TASK_C, lost)
    assert not verdict["passed"] and not verdict["checks"][1]["passed"]  # two_detail_lookups failed


def test_only_one_call_per_turn_runs():
    # the model asks for the whole chain at once, guessing a code it has not seen
    r = run(
        [
            call("search_notices", query="spinach"),
            call("get_notice_detail", notice_code="RCL-2026-00009"),
        ],
        [call("get_notice_detail", notice_code="RCL-2026-00001")],
        "RCL-2026-00001 by GreenFields Co.",
    )
    assert [t["tool"] for t in r["trace"]] == ["search_notices", "get_notice_detail"]
    assert r["trace"][1]["arguments"]["notice_code"] == "RCL-2026-00001"
    assert r["parallel_calls_dropped"] == 1 and verify_task(TASK_A, r)["passed"]


def test_dropped_calls_are_named_to_the_model():
    chat = scripted(
        [call("search_notices", query="peanut"), call("recall_stats", group_by="category")],
        [call("recall_stats", group_by="category")],
        "done",
    )
    run_agent("q", chat=chat, store=InMemoryStore(NOTICES))
    second_prompt = chat.state["seen"][1]
    assert (
        second_prompt[-1]["role"] == "user"
        and "did not run: recall_stats" in second_prompt[-1]["content"]
    )


def test_task_c_must_compare_only_the_first_two():
    many = NOTICES + [
        {**NOTICES[1], "notice_code": "RCL-2026-00004", "product": "Peanut Butter Bars"}
    ]
    store = InMemoryStore(many)
    drifted = run_agent(
        "q",
        store=store,
        chat=scripted(
            [call("search_notices", query="peanut butter")],
            [call("get_notice_detail", notice_code="RCL-2026-00002")],
            [call("get_notice_detail", notice_code="RCL-2026-00003")],
            [call("get_notice_detail", notice_code="RCL-2026-00004")],
            "Largest is RCL-2026-00004 (40 units); also RCL-2026-00002 and RCL-2026-00003.",
        ),
    )
    verdict = verify_task(TASK_C, drifted)
    failed = {c["check"] for c in verdict["checks"] if not c["passed"]}
    assert failed == {"answer_reports_pair_facts"}  # codes cited, but not their units/makers
    extra = run_agent(
        "q",
        store=store,
        chat=scripted(
            [call("search_notices", query="peanut butter")],
            [call("get_notice_detail", notice_code="RCL-2026-00002")],
            [call("get_notice_detail", notice_code="RCL-2026-00003")],
            "RCL-2026-00003: 75 units, GreenFields Co; RCL-2026-00002: 40 units, ACME Foods. "
            "RCL-2026-00003 affected more. (RCL-2026-00004 also exists.)",
        ),
    )
    assert verify_task(TASK_C, extra)["passed"]  # extra detail is not a reason to reject
    wrong_pair = run_agent(
        "q",
        store=store,
        chat=scripted(
            [call("search_notices", query="peanut butter")],
            [call("get_notice_detail", notice_code="RCL-2026-00003")],
            [call("get_notice_detail", notice_code="RCL-2026-00004")],
            "RCL-2026-00003 vs RCL-2026-00004.",
        ),
    )
    assert not verify_task(TASK_C, wrong_pair)["checks"][1]["passed"]  # not the first two


def test_unknown_tool_is_repaired_once():
    r = run(
        [call("find_notice", query="spinach")], [call("search_notices", query="spinach")], "done"
    )
    first, repair = r["call_events"]
    assert first["failure_type"] == "unknown_tool" and not first["well_formed"]
    assert repair["repair_attempt"] and repair["well_formed"] and repair["slot"] == first["slot"]
    assert r["repairs_used"] == 1 and r["tool_calls"] == 1


def test_schema_and_json_failures_are_malformed():
    assert validate_call("get_notice_detail", {"notice_code": "123"})[0] == "malformed_arguments"
    assert validate_call("search_notices", '{"query": "spin"')[0] == "malformed_arguments"
    assert validate_call("search_notices", '{"query": "spinach"}')[0] is None  # JSON string is fine
    assert validate_call("recall_stats", {"group_by": "colour"})[0] == "malformed_arguments"


def test_bad_call_is_never_executed_and_problem_is_specific():
    chat = scripted([call("get_notice_detail", notice_code="12")], "giving up")
    r = run_agent("q", chat=chat, store=InMemoryStore(NOTICES))
    assert r["trace"] == []  # nothing ran
    repair_msg = chat.state["seen"][1][-1]
    assert repair_msg["role"] == "tool" and "notice_code" in repair_msg["content"]


def test_text_instead_of_tool_gets_reprompted():
    r = run("I think spinach was recalled.", [call("search_notices", query="spinach")], "found it")
    assert r["call_events"][0]["failure_type"] == "text_instead_of_tool"
    assert r["call_events"][1]["well_formed"] and r["stop_reason"] == "final_answer"


def test_tool_call_written_as_text_is_malformed():
    r = run(
        '<tool_call>{"name": "search_notices", "arguments": {"query": "spinach"}}</tool_call>',
        [call("search_notices", query="spinach")],
        "ok",
    )
    assert r["call_events"][0]["failure_type"] == "malformed_arguments"


def test_repair_budget_stops_cleanly():
    r = run([call("nope")])  # always invalid
    assert r["stop_reason"] == "repair_limit"
    assert r["repairs_used"] == agent_loop.MAX_REPAIRS
    assert len(r["call_events"]) == agent_loop.MAX_REPAIRS + 1


def test_iteration_ceiling():
    r = run([call("search_notices", query="spinach")], max_iterations=3)  # never answers
    assert r["stop_reason"] == "max_iterations" and r["iterations"] == 3 and r["tool_calls"] == 3


def test_nonexistent_id_returns_useful_error():
    r = run(
        [call("get_notice_detail", notice_code="RCL-2026-99999")],
        "There is no recall notice RCL-2026-99999 in the database.",
    )
    assert r["trace"][0]["result"]["error"] == "notice RCL-2026-99999 not found"
    assert verify_task(TASK_E, r)["passed"]


def test_unsupported_code_fails_verifier():
    r = run(
        [call("search_notices", query="spinach")],
        [call("get_notice_detail", notice_code="RCL-2026-00001")],
        "RCL-2026-00001 and also RCL-2026-04444.",
    )
    verdict = verify_task(TASK_A, r)
    assert verdict["unsupported_claims"] == ["RCL-2026-04444"] and not verdict["passed"]


def test_invented_non_rcl_code_is_unsupported():
    r = run(
        [call("recall_stats", group_by="category")],
        "mislabelling leads; examples PEANUT-BUTTER-2023-001 and PEANUTBUTTER-1234.",
    )
    verdict = verify_task(TASK_B, r)
    assert verdict["unsupported_claims"] == ["PEANUT-BUTTER-2023-001", "PEANUTBUTTER-1234"]
    assert not verdict["passed"]


def test_budgets_and_context_notes():
    r = run([call("search_notices", query="spinach")], max_tool_calls=2)
    assert r["stop_reason"] == "budget_exhausted" and r["tool_calls"] == 2
    chat = scripted("I need a tool", [call("search_notices", query="spinach")], "ok")
    run_agent("q", chat=chat, store=InMemoryStore(NOTICES), context_notes=["search first"])
    first_prompt = chat.state["seen"][0]
    assert first_prompt[0]["role"] == "system" and "search first" not in first_prompt[0]["content"]
    assert first_prompt[2]["role"] == "user" and "Untrusted" in first_prompt[2]["content"]


def test_reliability_row_counts_before_and_after():
    import run_hw07_part2 as runner

    r = run(
        [call("find_notice")],
        [call("search_notices", query="spinach")],
        [call("get_notice_detail", notice_code="RCL-2026-00001")],
        "RCL-2026-00001 GreenFields Co",
    )
    row = runner.attempt_row(1, TASK_A, 7876, r, verify_task(TASK_A, r))
    assert row["intended_calls"] == 2 and row["well_formed_first_try"] == 1
    assert row["well_formed_after_repair"] == 2 and row["fail_unknown_tool"] == 1
    assert row["outcome"] == "success"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)
