"""
HW7 Part 4: build the two Bay Wheels scenario CSVs from public trip data.

    python scripts/build_bikeshare_scenarios.py download   # fetch the monthly zips (about 750 MB)
    python scripts/build_bikeshare_scenarios.py build      # sample the two scenario CSVs

Source: the public Bay Wheels system data bucket, https://s3.amazonaws.com/baywheels-data/
(one zip per month). Every output row is a real trip, copied unchanged from that month's file.
The public data has no rider id, so each scenario represents ONE rider's trip history
assembled by sampling real trips with a fixed seed (SEED = 7875); the agent states this as an
assumption.

  scenario_membership.csv  heavy commuter: 45 trips per month for 12 months (540 rows),
                           a mix of e-bike and classic rides, some classic rides over 45 min
  scenario_payperuse.csv   occasional rider: 10 short classic rides (3-12 min) per month
                           for 50 months (500 rows)

The zips go to data/bikeshare/months/ (git-ignored, too large to commit); the scenario CSVs
and a summary JSON go to data/bikeshare/ and reports/hw07/raw/.
"""
import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import date

import pandas as pd
import requests

BUCKET = "https://s3.amazonaws.com/baywheels-data/"
MONTH_DIR = os.path.join("data", "bikeshare", "months")
OUT_DIR = os.path.join("data", "bikeshare")
RAW_DIR = os.path.join("reports", "hw07", "raw")
SEED = 7875
MEMBERSHIP_MONTHS = [f"{y}{m:02d}" for y, m in [(2025, 10), (2025, 11), (2025, 12)]
                     + [(2026, m) for m in range(1, 10)]]


def month_range(first: str, last: str) -> list:
    """['YYYYMM', ...] from first to last inclusive."""
    y, m = int(first[:4]), int(first[4:])
    out = []
    while f"{y}{m:02d}" <= last:
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


PAYPERUSE_MONTHS = month_range("202208", "202609")  # 50 months


def bucket_keys() -> dict:
    """Map 'YYYYMM' -> object key, from the bucket listing (file names vary by month)."""
    xml = requests.get(BUCKET, timeout=60).text
    keys = re.findall(r"<Key>([^<]+)</Key>", xml)
    return {k[:6]: k for k in keys if re.match(r"^\d{6}-.*\.zip$", k)}


def download(months: list) -> None:
    """Download each month's zip once (skips files already present)."""
    os.makedirs(MONTH_DIR, exist_ok=True)
    keys = bucket_keys()
    for i, ym in enumerate(months, 1):
        if ym not in keys:
            print(f"[{i}/{len(months)}] {ym}: not in bucket, skipped")
            continue
        path = os.path.join(MONTH_DIR, keys[ym])
        if os.path.exists(path) and os.path.getsize(path) > 0:
            print(f"[{i}/{len(months)}] {ym}: already downloaded")
            continue
        with requests.get(BUCKET + keys[ym], stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(path + ".part", "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(path + ".part", path)
        print(f"[{i}/{len(months)}] {ym}: {os.path.getsize(path) / 1e6:.1f} MB")


def load_month(ym: str) -> pd.DataFrame:
    """Read one month's trips (the CSV inside the zip) with a duration_min helper column."""
    name = next(f for f in os.listdir(MONTH_DIR) if f.startswith(ym) and f.endswith(".zip"))
    with zipfile.ZipFile(os.path.join(MONTH_DIR, name)) as z:
        member = next(n for n in z.namelist() if n.endswith(".csv") and "__MACOSX" not in n)
        df = pd.read_csv(io.BytesIO(z.read(member)), low_memory=False)
    start, end = pd.to_datetime(df["started_at"]), pd.to_datetime(df["ended_at"])
    df["_minutes"] = (end - start).dt.total_seconds() / 60.0
    return df


def pick(df: pd.DataFrame, mask, n: int, seed: int) -> pd.DataFrame:
    """n random rows matching mask (fewer if the month has fewer)."""
    pool = df[mask]
    return pool.sample(n=min(n, len(pool)), random_state=seed)


def membership_rows(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Heavy commuter month: 27 e-bike (10-35 min), 15 classic (10-40), 3 classic (46-70)."""
    ebike, classic = df["rideable_type"] == "electric_bike", df["rideable_type"] != "electric_bike"
    mins = df["_minutes"]
    parts = [pick(df, ebike & mins.between(10, 35), 27, seed),
             pick(df, classic & mins.between(10, 40), 15, seed + 1),
             pick(df, classic & mins.between(46, 70), 3, seed + 2)]
    return pd.concat(parts)


def payperuse_rows(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Occasional rider month: 10 short classic rides (3-12 min)."""
    classic = df["rideable_type"] != "electric_bike"
    return pick(df, classic & df["_minutes"].between(3, 12), 10, seed)


def build_one(name: str, months: list, sampler) -> dict:
    """Sample every month, write the CSV (original columns only) and return its summary."""
    frames, columns = [], None
    for i, ym in enumerate(months):
        df = load_month(ym)
        columns = columns or [c for c in df.columns if c != "_minutes"]
        frames.append(sampler(df, SEED + i)[columns + ["_minutes"]])
        print(f"  {name} {ym}: {len(frames[-1])} trips")
    out = pd.concat(frames).sort_values("started_at")
    path = os.path.join(OUT_DIR, f"{name}.csv")
    out[columns].to_csv(path, index=False)
    minutes = out["_minutes"]
    return {"file": path, "rows": len(out), "months": len(months), "first_month": months[0],
            "last_month": months[-1], "seed": SEED, "columns": columns,
            "rideable_type_counts": out["rideable_type"].value_counts().to_dict(),
            "minutes_mean": round(float(minutes.mean()), 2),
            "minutes_median": round(float(minutes.median()), 2),
            "trips_over_45_min": int((minutes > 45).sum()), "built_on": date.today().isoformat()}


def build() -> None:
    """Write both scenario CSVs and their summaries."""
    os.makedirs(RAW_DIR, exist_ok=True)
    summary = {"source": BUCKET, "note": "real trips sampled per month; no rider id in the data",
               "scenario_membership": build_one("scenario_membership", MEMBERSHIP_MONTHS,
                                                membership_rows),
               "scenario_payperuse": build_one("scenario_payperuse", PAYPERUSE_MONTHS,
                                               payperuse_rows)}
    for name in ("scenario_membership", "scenario_payperuse"):
        src = summary[name]["file"]
        pd.read_csv(src).to_csv(os.path.join(RAW_DIR, f"part4_{name}.csv"), index=False)
    with open(os.path.join(RAW_DIR, "part4_scenario_summaries.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k.startswith("scenario")}, indent=2))


def main() -> None:
    """download | build"""
    parser = argparse.ArgumentParser(description="Build the HW7 Part 4 Bay Wheels scenarios")
    parser.add_argument("step", choices=["download", "build"])
    args = parser.parse_args()
    if args.step == "download":
        download(sorted(set(MEMBERSHIP_MONTHS + PAYPERUSE_MONTHS)))
    else:
        build()


if __name__ == "__main__":
    sys.exit(main())
