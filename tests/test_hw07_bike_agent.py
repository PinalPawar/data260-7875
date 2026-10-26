"""
HW7 Part 4: offline tests for the MRKL tools, the pricing extractor, the cost check and the
LangGraph agent wiring.

    python tests/test_hw07_bike_agent.py

No Ollama, no network, no database: the pricing page is a saved fixture with the structure of
the Bay Wheels page, trips are generated in memory, and the model is a scripted stand-in.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fake_llm import ScriptedToolModel  # noqa: E402

from bike_agent import cost_check  # noqa: E402
from bike_agent.agent import parse_final_json, run_bike_agent  # noqa: E402
from bike_agent.pricing_page import PricingSnapshotCache, extract_snippets  # noqa: E402
from bike_agent.tools import calculator, csv_sql, load_trips, policy_retriever  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "baywheels_pricing_sample.html")
HEADER = "ride_id,rideable_type,started_at,ended_at,member_casual\n"


def trips_csv(rows: list) -> str:
    """rows: (bike, 'YYYY-MM-DD HH:MM', minutes) -> Bay Wheels style CSV text."""
    from datetime import datetime, timedelta

    lines = []
    for i, (bike, start, minutes) in enumerate(rows):
        s = datetime.strptime(start, "%Y-%m-%d %H:%M")
        e = s + timedelta(minutes=minutes)
        lines.append(f"r{i},{bike},{s:%Y-%m-%d %H:%M:%S},{e:%Y-%m-%d %H:%M:%S},member")
    return HEADER + "\n".join(lines) + "\n"


SAMPLE = trips_csv(
    [
        ("classic_bike", "2026-01-05 08:00", 10),
        ("electric_bike", "2026-01-06 09:00", 20),
        ("classic_bike", "2026-02-02 08:00", 50),
    ]
)


def test_snippets_keep_plan_labels():
    snippets, text = extract_snippets(open(FIXTURE).read())
    assert "Month pass - Price: $29/month" in snippets
    assert "Single ride - Ebike prices: $1.00 unlock + $0.49/min" in snippets
    assert not any(s.startswith("Single ride: 45 min free") for s in snippets)  # no mislabels
    assert "var x" not in text  # scripts removed from the snapshot text


def test_policy_retriever_shape_and_ranking():
    env = policy_retriever(PricingSnapshotCache(save=False), FIXTURE, "month pass price", 2)
    assert env["success"] and set(env) >= {"success", "data", "source", "ts"}
    top = env["data"]["passages"][0]
    assert set(top) == {"text", "source", "score"} and top["text"].startswith("Month pass")
    assert len(env["data"]["snapshot_sha256"]) == 64


def test_policy_retriever_bad_url_fails_cleanly():
    env = policy_retriever(PricingSnapshotCache(save=False), "/no/such/page.html", "x")
    assert env["success"] is False and "error" in env


def test_csv_sql_select_and_helper_columns():
    conn = load_trips(SAMPLE)
    env = csv_sql(
        conn, "SELECT bike, ride_month, ROUND(duration_min) AS m FROM trips ORDER BY ride_id"
    )
    rows = env["data"]["rows"]
    assert (
        env["success"] and env["data"]["source"] == "uploaded.csv" and env["data"]["row_count"] == 3
    )
    assert rows[1] == {"bike": "ebike", "ride_month": "2026-01", "m": 20.0}


def test_csv_sql_refuses_anything_but_one_select():
    conn = load_trips(SAMPLE)
    for sql in [
        "DELETE FROM trips",
        "SELECT 1; DROP TABLE trips",
        "PRAGMA table_info(trips)",
        "WITH x AS (SELECT 1) DELETE FROM trips",
        "INSERT INTO trips (ride_id) VALUES (1)",
    ]:
        env = csv_sql(conn, sql)
        assert env["success"] is False, sql
    assert csv_sql(conn, "SELECT COUNT(*) AS n FROM trips")["data"]["rows"][0]["n"] == 3


def test_csv_sql_caps_rows_for_the_model():
    rows = [("classic_bike", f"2026-01-01 {h:02d}:00", 5) for h in range(10)]
    conn = load_trips(trips_csv(rows))
    env = csv_sql(conn, "SELECT ride_id FROM trips", max_rows=4)
    assert len(env["data"]["rows"]) == 4 and env["data"]["row_count"] == 10
    assert env["data"]["truncated_to"] == 4 and "Do not re-run" in env["data"]["note"]
    assert len(csv_sql(conn, "SELECT ride_id FROM trips")["data"]["rows"]) == 10


def test_calculator_is_safe():
    assert calculator("29*12 + (0.17*10)", "USD")["data"] == {"value": 349.7, "units": "USD"}
    for bad in ["__import__('os')", "2**8", "1/0", "abs(-1)", ""]:
        assert calculator(bad)["success"] is False, bad


def test_cost_check_matches_hand_calculation():
    snippets, _ = extract_snippets(open(FIXTURE).read())
    p = cost_check.parse_prices(snippets)
    assert p == {
        "ppu_unlock": 1.0,
        "ppu_classic_per_min": 0.19,
        "ppu_ebike_per_min": 0.49,
        "pass_per_month": 29.0,
        "member_free_min": 45.0,
        "member_overage_per_min": 0.17,
        "member_ebike_unlock": 0.0,
        "member_ebike_per_min": 0.17,
    }
    usage = csv_sql(load_trips(SAMPLE), cost_check.usage_sql(45))["data"]["rows"][0]
    costs = cost_check.compute_costs(usage, p)
    # pay-per-use: 3 unlocks + 60 classic min * 0.19 + 20 e-bike min * 0.49 = 3 + 11.4 + 9.8
    assert costs["pay_per_use_total"] == 24.2
    # member: 2 months * 29 + 5 overage min * 0.17 + 20 e-bike min * 0.17 = 58 + 0.85 + 3.4
    assert costs["membership_total"] == 62.25 and costs["decision"] == "Pay Per Ride/Minute"


def test_parse_final_json_tolerates_fences():
    assert parse_final_json('```json\n{"decision": "X"}\n```') == {"decision": "X"}
    assert parse_final_json("no json") is None


def test_agent_run_end_to_end_with_scripted_model():
    final = {
        "decision": "Pay Per Ride/Minute",
        "justification": "j",
        "citations": [],
        "costs": {
            "pay_per_use_total": 24.2,
            "membership_fees": 58,
            "membership_residual": 4.25,
            "membership_total": 62.25,
            "break_even_rides_per_month": 4.4,
            "actual_rides_per_month": 1.5,
        },
        "assumptions": [],
    }
    model = ScriptedToolModel(
        replies=[
            [("policy_retriever", {"url": FIXTURE, "query": "single ride unlock"})],
            [("csv_sql", {"sql": cost_check.usage_sql(45)})],
            [("calculator", {"expression": "3+60*0.19+20*0.49"})],
            json.dumps(final),
        ]
    )
    r = run_bike_agent(SAMPLE, FIXTURE, model=model, save_snapshot=False)
    assert r["metrics"]["steps"] == 3 and r["metrics"]["stop_reason"] == "final_answer"
    assert [e["type"] for e in r["timeline"]].count("observation") == 3
    assert all(x["match"] for x in r["check"]["comparison"]) and r["rows_loaded"] == 3
    obs = next(
        e for e in r["timeline"] if e["tool"] == "policy_retriever" and e["type"] == "observation"
    )
    assert "UNTRUSTED PAGE DATA" in obs["output"]


def test_decision_guard_follows_own_totals():
    from bike_agent.agent import decision_guard

    wrong = {
        "decision": "Buy Monthly Membership",
        "costs": {"pay_per_use_total": 1189.59, "membership_total": 1450.0},
    }
    g = decision_guard(wrong)
    assert g["corrected"] and wrong["decision"] == "Pay Per Ride/Minute"
    right = {
        "decision": "Buy Monthly Membership",
        "costs": {"pay_per_use_total": 4101.87, "membership_total": 1299.2},
    }
    assert decision_guard(right)["corrected"] is False
    assert decision_guard({"decision": "X"}) is None


def test_agent_flags_wrong_numbers():
    model = ScriptedToolModel(
        replies=[
            '{"decision": "Buy Monthly Membership", '
            '"costs": {"pay_per_use_total": 999, "membership_total": 1}}'
        ]
    )
    r = run_bike_agent(SAMPLE, FIXTURE, model=model, save_snapshot=False)
    assert not any(x["match"] for x in r["check"]["comparison"])
    assert r["check"]["reference"]["decision"] == "Pay Per Ride/Minute"


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
