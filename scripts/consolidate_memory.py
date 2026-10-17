"""HW6 Part 4.5 - run the consolidation on a MEMORY.md file and save the result.

    python scripts/consolidate_memory.py reports/hw06/memory_test/MEMORY_original.md \
        --out reports/hw06/memory_test/MEMORY_consolidated.md \
        --report reports/hw06/memory_test/consolidation_report.md

The original file is never modified.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from file_memory.consolidate import consolidate, format_report  # noqa: E402
from file_memory.memory_files import needs_consolidation, read_text  # noqa: E402


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser()
    ap.add_argument("memory_file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    text = read_text(Path(args.memory_file))
    due, reasons = needs_consolidation(text, now)
    print(f"Consolidation required: {due} ({'; '.join(reasons) or 'no rule triggered'})")
    new_text, report = consolidate(text, now)
    Path(args.out).write_text(new_text, encoding="utf-8")
    body = format_report(report)
    Path(args.report).write_text(
        "# Consolidation report\n\n"
        f"Input: `{args.memory_file}`  \nOutput: `{args.out}`  \nRun at: {report['consolidated_at']}  \n"
        f"Why it was required: {'; '.join(reasons)}\n\n```\n{body}\n```\n", encoding="utf-8")
    Path(args.report).with_suffix(".json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(body)
    print(f"\nSaved {args.out}, {args.report}")


if __name__ == "__main__":
    main()
