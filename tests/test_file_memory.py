"""HW6 Part 4: offline tests for file-based memory and consolidation.

    python tests/test_file_memory.py

Plain assert statements like tests/test_hw05_tools.py. No Ollama, no network,
no database: /dream uses a fake model, and files live in a temporary folder.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from file_memory.consolidate import consolidate, same_meaning  # noqa: E402
from file_memory.dream import dream  # noqa: E402
from file_memory.memory_files import (build_system_prompt, count_memory_lines,  # noqa: E402
                                      needs_consolidation, read_last_consolidated,
                                      set_last_consolidated, write_memory_md, read_text)

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "reports" / "hw06" / "memory_test" / "MEMORY_original.md"
NOW = datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc)
SMALL = """# MEMORY.md
<!-- last_consolidated: 2026-10-16T06:00:00+00:00 -->
<!-- a comment
     over two lines -->
## Facts
- [2026-10-15] allergy.user = allergic to peanuts (source: user)
"""


def test_line_count_ignores_blanks_and_comments() -> None:
    """Blank lines and (multi-line) comments are not counted."""
    assert count_memory_lines(SMALL) == 3


def test_timestamp_read_and_write() -> None:
    """The last-consolidated stamp can be read and replaced."""
    assert read_last_consolidated(SMALL) == datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)
    later = set_last_consolidated(SMALL, NOW)
    assert read_last_consolidated(later) == NOW and later.count("last_consolidated") == 1


def test_consolidation_rules() -> None:
    """Required when >40 lines or older than 24 h; not required otherwise."""
    assert needs_consolidation(SMALL, NOW) == (False, [])
    due, reasons = needs_consolidation(SMALL, NOW + timedelta(hours=25))
    assert due and "24 h" in reasons[0]
    many = SMALL + "".join(f"- [2026-10-15] note = fact {i} (source: user)\n" for i in range(40))
    due, reasons = needs_consolidation(many, NOW)
    assert due and "lines > 40" in reasons[0]
    assert needs_consolidation("# empty", NOW)[0]          # no stamp counts as old


def test_same_meaning() -> None:
    """Paraphrases match; negations and different numbers do not."""
    assert same_meaning("allergic to peanuts", "peanut allergy")
    assert same_meaning("Saturday morning", "Saturdays")
    assert not same_meaning("allergic to eggs", "no food allergies")
    assert not same_meaning("3 years old", "4 years old")


def test_consolidation_of_55_line_file() -> None:
    """The test file shrinks below 40 lines and loses no conflicting information."""
    text = read_text(ORIGINAL)
    assert count_memory_lines(text) == 55
    new, report = consolidate(text, NOW)
    assert report["lines_after"] < 40
    assert len(report["duplicates_merged"]) >= 3 and len(report["contradictions_resolved"]) >= 3
    assert "allergy.son = egg allergy" in new and "no food allergies" in new   # kept, under review
    assert "user.city = San Jose" in new and "\"Fresno\" (2026-10-13, dream)" in new
    assert '"email"' in new and "Costco" in new and "Safeway, because it is closer" in new
    again, report2 = consolidate(new, NOW)
    assert report2["lines_after"] == report["lines_after"] and not report2["contradictions_resolved"]


def test_dream_adds_only_new_facts() -> None:
    """/dream stores new facts with source 'dream' and skips known ones."""
    fake = lambda msgs: ('[{"key": "allergy.user", "value": "peanut allergy"},'
                         ' {"key": "allergy.son", "value": "allergic to eggs"}]')
    history = [{"role": "user", "content": "My son is allergic to eggs."}]
    new, added = dream(history, SMALL, fake, "2026-10-16")
    assert [f.key for f in added] == ["allergy.son"]
    assert "allergy.son = allergic to eggs (source: dream)" in new


def test_prompt_and_file_roundtrip() -> None:
    """The system prompt holds both files; MEMORY.md survives a write/read."""
    prompt = build_system_prompt("## Rules\n- be brief", SMALL)
    assert "be brief" in prompt and "allergic to peanuts" in prompt and "two lines" not in prompt
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "MEMORY.md"
        write_memory_md(SMALL, path)
        assert read_text(path).strip() == SMALL.strip()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)
