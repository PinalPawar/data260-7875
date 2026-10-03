"""
HW5 Parts 4-5: offline test runner for the three domain tools and the agent loop.

    python3 tests/test_hw05_tools.py

Plain assert statements, no test framework. Every test goes through
execute_tool with an injected InMemoryStore fixture, so the suite needs no
database, no network and no LLM, and gives the same result every run.
The Part 5 agent test uses MockModel instead of Ollama.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recall_tools.agent import MockModel, run_agent
from recall_tools.execute import execute_tool
from recall_tools.retry import FlakyStore, ResilientStore, RetryPolicy
from recall_tools.store import InMemoryStore

FIXTURE_NOTICES = [
    {"notice_code": "RCL-2026-00001", "product": "Frozen Spinach", "category": "bacterialContamination",
     "units_affected": 100, "description": "Listeria found in lot L1.", "contact_email": "qa@greenfields.com",
     "manufacturer": {"code": "MFR-0001", "name": "GreenFields Co", "headquarters": "Salinas, CA"}},
    {"notice_code": "RCL-2026-00002", "product": "Baby Spinach Salad Kit", "category": "foreignMaterial",
     "units_affected": 250, "description": "Metal fragments reported.", "contact_email": "qa@acme.com",
     "manufacturer": {"code": "MFR-0002", "name": "ACME Foods", "headquarters": "Fresno, CA"}},
    {"notice_code": "RCL-2026-00003", "product": "Peanut Butter", "category": "mislabelling",
     "units_affected": 40, "description": "Undeclared allergen.", "contact_email": "qa@acme.com",
     "manufacturer": {"code": "MFR-0002", "name": "ACME Foods", "headquarters": "Fresno, CA"}},
]


def fresh_store():
    """A new temporary fixture for every test, so tests can't affect each other."""
    return InMemoryStore(FIXTURE_NOTICES)


def call(name, inputs, store=None):
    raw = execute_tool(name, inputs, store=store or fresh_store())
    assert isinstance(raw, str), "execute_tool must return a JSON string"
    result = json.loads(raw)
    assert set(result) == {"ok", "data", "error"}, "envelope must be exactly {ok, data, error}"
    return result


# --- search_notices ---------------------------------------------------------
def test_search_valid():
    r = call("search_notices", {"query": "spinach", "limit": 5})
    assert r["ok"] is True and r["error"] is None
    assert r["data"]["count"] == 2
    assert {n["notice_code"] for n in r["data"]["notices"]} == {"RCL-2026-00001", "RCL-2026-00002"}


def test_search_rejects_limit_over_20():
    r = call("search_notices", {"query": "spinach", "limit": 500})
    assert r["ok"] is False and r["data"] is None
    assert "limit" in r["error"]


# --- get_notice_detail ------------------------------------------------------
def test_detail_valid():
    r = call("get_notice_detail", {"notice_code": "RCL-2026-00003"})
    assert r["ok"] is True
    assert r["data"]["product"] == "Peanut Butter"
    assert r["data"]["manufacturer"]["code"] == "MFR-0002"


def test_detail_rejects_bad_code_format():
    r = call("get_notice_detail", {"notice_code": "ABC-123"})
    assert r["ok"] is False and r["data"] is None
    assert "notice_code" in r["error"]


# --- recall_stats -----------------------------------------------------------
def test_stats_valid():
    r = call("recall_stats", {"group_by": "manufacturer"})
    assert r["ok"] is True
    assert r["data"]["total_notices"] == 3 and r["data"]["total_units_affected"] == 390
    acme = next(g for g in r["data"]["groups"] if g["group"] == "ACME Foods")
    assert acme["notice_count"] == 2 and acme["total_units_affected"] == 290


def test_stats_rejects_unknown_group_by():
    r = call("recall_stats", {"group_by": "color"})
    assert r["ok"] is False and r["data"] is None
    assert "group_by" in r["error"]


# --- execute_tool itself ----------------------------------------------------
def test_unknown_tool_returns_clean_error():
    r = call("delete_everything", {})
    assert r["ok"] is False and "unknown tool" in r["error"]


def test_storage_failure_returns_clean_error_not_crash():
    always_failing = FlakyStore(fresh_store(), script=["fail", "fail", "fail"])
    store = ResilientStore(always_failing, RetryPolicy(max_attempts=3), sleep=lambda seconds: None)
    r = call("search_notices", {"query": "spinach"}, store=store)
    assert r["ok"] is False and "storage error" in r["error"]
    assert store.last_call["attempts"] == 3


# --- Part 5 additions -------------------------------------------------------
def test_safety_rule_blocks_email_lookup():
    r = call("search_notices", {"query": "qa@acme.com"})
    assert r["ok"] is False and r["data"] is None
    assert r["error"].startswith("safety rule:")
    allowed = call("search_notices", {"query": "acme"})
    assert allowed["ok"] is True, "the same tool must still work for an allowed query"


def test_agent_stops_at_max_steps_with_mock_model():
    # A model that asks for the same tool on every turn and never answers.
    never_finishes = MockModel([{"tool_calls": [{"name": "recall_stats", "arguments": {"group_by": "category"}}]}])
    outcome = run_agent("How many recalls are there?", model=never_finishes, store=fresh_store(),
                        max_steps=3, log_path=None)
    assert outcome["stop_reason"] == "max_steps"
    assert outcome["steps"] == 3 and outcome["tool_calls"] == 3
    assert never_finishes.calls == 3, "the model must not be called again after the limit"


TESTS = [
    test_search_valid,
    test_search_rejects_limit_over_20,
    test_detail_valid,
    test_detail_rejects_bad_code_format,
    test_stats_valid,
    test_stats_rejects_unknown_group_by,
    test_unknown_tool_returns_clean_error,
    test_storage_failure_returns_clean_error_not_crash,
    test_safety_rule_blocks_email_lookup,
    test_agent_stops_at_max_steps_with_mock_model,
]


def main():
    print("HW5 offline tool tests -- Pinal Pawar (SID4 7875)")
    passed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            print(f"FAIL  {test.__name__}  {exc}")
        except Exception as exc:
            print(f"FAIL  {test.__name__}  unexpected {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(TESTS)} tests passed")
    return 0 if passed == len(TESTS) else 1


if __name__ == "__main__":
    sys.exit(main())
