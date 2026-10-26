"""
HW7 Part 4: deterministic cost model, used to (a) cross-check the agent's numbers and
(b) build the by-week table from the same uploaded data and the same captured pricing page.

Prices are parsed from the run's pricing snapshot with regular expressions, never typed in:
  pay-per-use  unlock fee, classic $/min, e-bike $/min        ("Single ride - ...")
  month pass   price per month, free classic minutes per ride, classic overage $/min,
               e-bike unlock and $/min                        ("Month pass - ...")
If any price cannot be found the check reports which one, instead of guessing.
"""

import re
from typing import Optional

MONEY = r"\$(\d+(?:\.\d+)?)"


def _find(snippets: list, plan: str, label: str, pattern: str) -> Optional[float]:
    """First number matching pattern in a '<plan> - <label>: ...' grid snippet."""
    for s in snippets:
        if s.lower().startswith(f"{plan.lower()} - {label.lower()}"):
            m = re.search(pattern, s, re.IGNORECASE)
            if m:
                return float(m.group(1))
    return None


def parse_prices(snippets: list) -> dict:
    """Prices needed for both plans, parsed from the snapshot's snippets (None if missing)."""
    member_classic = next((s for s in snippets if s.lower().startswith("month pass - classic")), "")
    member_ebike = next((s for s in snippets if s.lower().startswith("month pass - ebike")), "")
    return {
        "ppu_unlock": _find(snippets, "Single ride", "Classic", MONEY + r"\s*to unlock"),
        "ppu_classic_per_min": _find(snippets, "Single ride", "Classic", MONEY + r"/min"),
        "ppu_ebike_per_min": _find(snippets, "Single ride", "Ebike", MONEY + r"/min"),
        "pass_per_month": _find(snippets, "Month pass", "Price", MONEY + r"/month"),
        "member_free_min": _num(r"(\d+)\s*min free", member_classic),
        "member_overage_per_min": _num(MONEY + r"/min", member_classic),
        "member_ebike_unlock": 0.0
        if re.search(r"free unlock", member_ebike, re.I)
        else _num(MONEY + r"\s*unlock", member_ebike),
        "member_ebike_per_min": _num(MONEY + r"/min", member_ebike),
    }


def _num(pattern: str, text: str) -> Optional[float]:
    """First captured number in text, or None."""
    m = re.search(pattern, text or "", re.IGNORECASE)
    return float(m.group(1)) if m else None


def usage_sql(free_min: float) -> str:
    """One aggregate query over the trips table (the same query the agent is asked to run)."""
    return (
        "SELECT COUNT(*) AS rides, COUNT(DISTINCT ride_month) AS months, "
        "SUM(bike = 'classic') AS classic_rides, "
        "ROUND(SUM(CASE WHEN bike = 'classic' THEN duration_min ELSE 0 END), 2) AS classic_min, "
        "SUM(bike = 'ebike') AS ebike_rides, "
        "ROUND(SUM(CASE WHEN bike = 'ebike' THEN duration_min ELSE 0 END), 2) AS ebike_min, "
        f"ROUND(SUM(CASE WHEN bike = 'classic' AND duration_min > {free_min:g} "
        f"THEN duration_min - {free_min:g} ELSE 0 END), 2) AS classic_over_free_min, "
        "SUM(duration_min IS NULL) AS rows_missing_times, SUM(bike IS NULL) AS rows_missing_bike "
        "FROM trips"
    )


def weekly_sql(p: dict) -> str:
    """Rides, average minutes and pay-per-use spend per ISO week."""
    return (
        "SELECT ride_week AS week, COUNT(*) AS rides, ROUND(AVG(duration_min), 1) AS avg_min, "
        f"ROUND(SUM({p['ppu_unlock']} + CASE WHEN bike = 'ebike' THEN {p['ppu_ebike_per_min']} "
        f"ELSE {p['ppu_classic_per_min']} END * duration_min), 2) AS pay_per_use_spend "
        "FROM trips WHERE duration_min IS NOT NULL GROUP BY ride_week ORDER BY ride_week"
    )


def compute_costs(usage: dict, p: dict) -> dict:
    """Both totals, the residual member charges and the break-even point."""
    ppu = (
        usage["rides"] * p["ppu_unlock"]
        + usage["classic_min"] * p["ppu_classic_per_min"]
        + usage["ebike_min"] * p["ppu_ebike_per_min"]
    )
    residual = (
        usage["classic_over_free_min"] * p["member_overage_per_min"]
        + usage["ebike_rides"] * p["member_ebike_unlock"]
        + usage["ebike_min"] * p["member_ebike_per_min"]
    )
    fees = usage["months"] * p["pass_per_month"]
    per_ride_ppu = ppu / usage["rides"] if usage["rides"] else 0.0
    per_ride_member = residual / usage["rides"] if usage["rides"] else 0.0
    saving = per_ride_ppu - per_ride_member
    return {
        "pay_per_use_total": round(ppu, 2),
        "membership_fees": round(fees, 2),
        "membership_residual": round(residual, 2),
        "membership_total": round(fees + residual, 2),
        "decision": "Buy Monthly Membership" if fees + residual < ppu else "Pay Per Ride/Minute",
        "break_even_rides_per_month": round(p["pass_per_month"] / saving, 1)
        if saving > 0
        else None,
        "actual_rides_per_month": round(usage["rides"] / usage["months"], 1)
        if usage["months"]
        else None,
    }


def compare(agent_costs: dict, reference: dict, tolerance: float = 0.02) -> list:
    """Per-figure comparison of the agent's numbers with the reference (2% tolerance)."""
    rows = []
    keys = (
        "pay_per_use_total",
        "membership_fees",
        "membership_residual",
        "membership_total",
        "break_even_rides_per_month",
        "actual_rides_per_month",
    )
    for key in keys:
        ref, got = reference.get(key), (agent_costs or {}).get(key)
        try:
            ok = got is not None and abs(float(got) - ref) <= tolerance * max(abs(ref), 1.0)
        except (TypeError, ValueError):
            ok = False
        rows.append({"figure": key, "agent": got, "reference": ref, "match": ok})
    return rows
