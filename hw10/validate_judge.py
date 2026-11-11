"""HW10 Part 3.2-3.3: compare the judge with my human labels, then test repeatability.

Refuses to run unless hw10/eval_cases.json and hw10/human_labels.csv are committed in git and
unchanged since (Part 3.1: freeze before judging). Then it runs the Writer Helpfulness GEval
metric (the same one as Part 2, same 1-5 scale) on the 20 frozen drafts, three times, same
inputs and settings, and writes:

    reports/hw10/raw/part3_judge_runs.csv      raw per-case data (human, run1-3, reasons)
    reports/hw10/raw/part3_judge_summary.json  Spearman, mean abs diff, repeatability

    python hw10/validate_judge.py
"""

import csv
import json
import statistics
import subprocess
import time
from itertools import combinations

import hw10cfg as cfg

RUNS = 3


def frozen_commit() -> dict:
    """Commit that froze both files; SystemExit if they are untracked or modified."""
    files = [str(p.relative_to(cfg.ROOT)) for p in (cfg.EVAL_CASES, cfg.HUMAN_LABELS)]

    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=cfg.ROOT, capture_output=True, text=True).stdout

    for f in files:
        if not git("ls-files", f).strip():
            raise SystemExit(f"{f} is not committed - commit it before judging (Part 3.1)")
    if git("status", "--porcelain", *files).strip():
        raise SystemExit("eval_cases.json / human_labels.csv changed since commit - not judging")
    line = git("log", "-1", "--format=%H|%cI|%s", "--", *files).strip()
    sha, when, subject = line.split("|", 2)
    return {"files": files, "commit": sha, "committed_at": when, "subject": subject}


def ranks(xs: list[float]) -> list[float]:
    """Average ranks (ties share the mean rank), as Spearman needs."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rho = Pearson correlation of the average ranks (handles ties)."""
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return round(num / den, 4) if den else None


def run_judge(cases: list[dict]) -> list[list[dict]]:
    """RUNS passes of Writer Helpfulness over all cases (fresh metric object per call)."""
    from judge import build_metrics, measure
    out = []
    for run in range(1, RUNS + 1):
        res = []
        for c in cases:
            qp = f"Question: {c['question']}\n\nPlan:\n" + "\n".join(f"- {p}" for p in c["plan"])
            r = measure(build_metrics()["writer_helpfulness"], qp, c["draft"])
            res.append(r)
            print(f"run {run} {c['case_id']}: score={r['score_1_5']} ({r['status']}, "
                  f"{r['judge_ms']:.0f} ms)")
        out.append(res)
    return out


def repeatability(runs: list[list[float | None]]) -> dict:
    """How often and how much a case's score changes across the repeated runs."""
    per_case = list(zip(*runs))
    changed = [len({s for s in c}) > 1 for c in per_case]
    diffs = [abs(x - y) for c in per_case for x, y in combinations(c, 2)
             if x is not None and y is not None]
    ranges = [max(c) - min(c) for c in per_case if None not in c]
    return {"cases": len(per_case), "cases_changed": sum(changed),
            "pct_cases_changed": round(100 * sum(changed) / len(per_case), 1),
            "pairwise_mean_abs_change": round(statistics.fmean(diffs), 4) if diffs else None,
            "max_abs_change": max(ranges) if ranges else None,
            "mean_range_per_case": round(statistics.fmean(ranges), 4) if ranges else None}


def summarize(human: list[int], runs: list[list[dict]], frozen: dict) -> dict:
    """All Part 3 statistics (run 1 is the headline; runs 2-3 and the mean also reported)."""
    from judge import judge_settings
    sc = [[r["score_1_5"] for r in run] for run in runs]
    per_run = []
    for i, s in enumerate(sc, 1):
        ok = [(h, j) for h, j in zip(human, s) if j is not None]
        per_run.append({"run": i, "n_scored": len(ok),
                        "spearman": spearman([h for h, _ in ok], [j for _, j in ok]),
                        "mean_abs_diff": round(statistics.fmean(abs(h - j) for h, j in ok), 4)
                        if ok else None,
                        "mean_judge": round(statistics.fmean(j for _, j in ok), 3) if ok else None})
    return {"frozen": frozen, "judge": judge_settings(), "n_cases": len(human),
            "mean_human": round(statistics.fmean(human), 3), "per_run": per_run,
            "headline": per_run[0], "repeatability": repeatability(sc),
            "judge_failures": sum(r["status"] != "ok" for run in runs for r in run),
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def save(cases: list[dict], human: list[int], runs: list[list[dict]], summary: dict) -> None:
    """Raw CSV (recomputable) + summary JSON."""
    cfg.RAW.mkdir(parents=True, exist_ok=True)
    with open(cfg.JUDGE_RUNS, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "human_label", "judge_run1", "judge_run2", "judge_run3",
                    "abs_diff_run1", "changed_across_runs", "reason_run1", "question"])
        for i, c in enumerate(cases):
            s = [runs[k][i]["score_1_5"] for k in range(RUNS)]
            w.writerow([c["case_id"], human[i], *s,
                        None if s[0] is None else abs(human[i] - s[0]), len(set(s)) > 1,
                        runs[0][i]["reason"], c["question"]])
    cfg.JUDGE_SUMMARY.write_text(json.dumps(summary, indent=2))


def main() -> None:
    """Freeze check -> 3 judge runs -> stats -> files."""
    print(cfg.banner("Part 3 judge validation"))
    frozen = frozen_commit()
    print(f"frozen in commit {frozen['commit'][:10]} at {frozen['committed_at']}")
    cases = json.loads(cfg.EVAL_CASES.read_text())["cases"]
    labels = {r["case_id"]: int(r["human_label"]) for r in csv.DictReader(open(cfg.HUMAN_LABELS))}
    human = [labels[c["case_id"]] for c in cases]
    runs = run_judge(cases)
    s = summarize(human, runs, frozen)
    save(cases, human, runs, s)
    h, rep = s["headline"], s["repeatability"]
    print(f"\nSpearman (human vs judge run 1) = {h['spearman']}   "
          f"mean |diff| = {h['mean_abs_diff']}")
    print(f"Repeatability: {rep['cases_changed']}/{rep['cases']} cases changed across "
          f"{RUNS} runs; mean pairwise |change| = {rep['pairwise_mean_abs_change']}, "
          f"max = {rep['max_abs_change']}")
    print(f"saved {cfg.JUDGE_RUNS.relative_to(cfg.ROOT)} and "
          f"{cfg.JUDGE_SUMMARY.relative_to(cfg.ROOT)}")


if __name__ == "__main__":
    main()
