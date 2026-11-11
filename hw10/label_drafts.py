"""HW10 Part 3.1: YOU label each of the 20 drafts for helpfulness, 1-5, by hand.

Shows one draft at a time and asks for your score; nothing here calls a model. Writes
hw10/human_labels.csv (case_id,human_label,labeler,labeled_at,note). Commit it together with
eval_cases.json BEFORE running validate_judge.py, and do not relabel after seeing judge scores.

    python hw10/label_drafts.py

Scale (the same one the judge uses):
    1 very poor  - wrong, unsafe, off-topic or unusable
    2 poor       - major gaps or errors; a shopper would be misled or stuck
    3 acceptable - mostly right but misses an important point or is vague
    4 good       - accurate, safe and useful with only minor gaps
    5 excellent  - accurate, safe, specific, complete and easy to act on
"""

import csv
import json
import textwrap
import time

import hw10cfg as cfg

SCALE = __doc__.split("Scale (the same one the judge uses):")[1]


def ask_label(case: dict) -> tuple[int, str]:
    """Show one case and read a 1-5 label (and an optional short note)."""
    print("\n" + "=" * 90)
    print(f"{case['case_id']}  QUESTION: {case['question']}")
    print("PLAN:\n" + "\n".join(f"  - {p}" for p in case["plan"]))
    print("DRAFT:\n" + textwrap.fill(case["draft"], 88, initial_indent="  ",
                                      subsequent_indent="  "))
    while True:
        raw = input("Your helpfulness label 1-5: ").strip()
        if raw in {"1", "2", "3", "4", "5"}:
            return int(raw), input("Optional note (enter to skip): ").strip()
        print("  please type a whole number 1-5")


def main() -> None:
    """Label all 20 drafts and save the CSV."""
    print(cfg.banner("Part 3.1 human labels"))
    if cfg.HUMAN_LABELS.exists():
        raise SystemExit(f"{cfg.HUMAN_LABELS.name} exists - labels are frozen; not relabeling")
    cases = json.loads(cfg.EVAL_CASES.read_text())["cases"]
    print(SCALE)
    rows = []
    for c in cases:
        label, note = ask_label(c)
        rows.append({"case_id": c["case_id"], "human_label": label, "labeler": cfg.STUDENT_NAME,
                     "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "note": note})
    with open(cfg.HUMAN_LABELS, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nsaved {cfg.HUMAN_LABELS.relative_to(cfg.ROOT)} - now commit both files")


if __name__ == "__main__":
    main()
