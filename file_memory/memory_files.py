"""HW6 Part 4 - loading AGENT.md and MEMORY.md and deciding when to consolidate.

AGENT.md holds durable project/agent instructions; MEMORY.md holds durable
facts learned from conversations. Both are plain Markdown, so a person can
read and edit them. MEMORY.md records when it was last consolidated in an
HTML comment:  <!-- last_consolidated: 2026-10-16T07:00:00+00:00 -->
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
AGENT_PATH = ROOT / "AGENT.md"
MEMORY_PATH = ROOT / "MEMORY.md"

MAX_MEMORY_LINES = 40                 # consolidate when MEMORY.md has more lines than this
MAX_AGE = timedelta(hours=24)         # ... or when the last consolidation is older than this
_STAMP_RE = re.compile(r"<!--\s*last_consolidated:\s*([^\s>]+)\s*-->")


def read_text(path: Path) -> str:
    """Return the file's text, or an empty string if the file does not exist."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_agent_md(path: Path = AGENT_PATH) -> str:
    """Load AGENT.md (durable project and agent instructions)."""
    return read_text(path)


def load_memory_md(path: Path = MEMORY_PATH) -> str:
    """Load MEMORY.md (durable facts learned from earlier conversations)."""
    return read_text(path)


def write_memory_md(text: str, path: Path = MEMORY_PATH) -> None:
    """Save MEMORY.md."""
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def content_lines(text: str) -> List[str]:
    """Return the non-empty, non-comment lines; HTML comments may span lines."""
    lines, in_comment = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.startswith("<!--"):
            in_comment = "-->" not in line
            continue
        if line:
            lines.append(line)
    return lines


def count_memory_lines(text: str) -> int:
    """Count the non-empty, non-comment lines of a MEMORY.md text."""
    return len(content_lines(text))


def read_last_consolidated(text: str) -> Optional[datetime]:
    """Return the recorded last-consolidated time, or None if missing or unreadable."""
    match = _STAMP_RE.search(text)
    if not match:
        return None
    try:
        stamp = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def set_last_consolidated(text: str, when: datetime) -> str:
    """Return the text with its last-consolidated stamp set to `when`."""
    stamp = f"<!-- last_consolidated: {when.astimezone(timezone.utc).isoformat(timespec='seconds')} -->"
    if _STAMP_RE.search(text):
        return _STAMP_RE.sub(stamp, text, count=1)
    head, _, rest = text.partition("\n")
    return f"{head}\n{stamp}\n{rest}" if head.startswith("#") else f"{stamp}\n{text}"


def needs_consolidation(text: str, now: Optional[datetime] = None) -> Tuple[bool, List[str]]:
    """Decide whether MEMORY.md must be consolidated and say why.

    Consolidation is required when the file has more than MAX_MEMORY_LINES
    non-empty, non-comment lines, or when its recorded consolidation time is
    more than MAX_AGE old (a missing or unreadable time also counts as old).
    """
    now = now or datetime.now(timezone.utc)
    reasons = []
    n_lines = count_memory_lines(text)
    if n_lines > MAX_MEMORY_LINES:
        reasons.append(f"{n_lines} lines > {MAX_MEMORY_LINES}")
    last = read_last_consolidated(text)
    if last is None:
        reasons.append("no last-consolidated time recorded")
    elif now - last > MAX_AGE:
        hours = (now - last).total_seconds() / 3600
        reasons.append(f"last consolidated {hours:.1f} h ago > {MAX_AGE.total_seconds() / 3600:.0f} h")
    return bool(reasons), reasons


def build_system_prompt(agent_text: str, memory_text: str) -> str:
    """Put AGENT.md and the facts from MEMORY.md into one system prompt."""
    facts = "\n".join(content_lines(memory_text)) or "(no facts stored yet)"
    return (
        "## Agent instructions (AGENT.md)\n"
        f"{agent_text.strip()}\n\n"
        "## Long-term memory (MEMORY.md)\n"
        "Durable facts about the user from earlier conversations. Use them when they are "
        "relevant. Lines under 'Needs review' are unconfirmed: mention the doubt instead of "
        "treating them as certain.\n"
        f"{facts}\n\n"
        "## Your reply\n"
        "This is a normal conversation, not a code review: reply in 2-4 plain sentences "
        "(no bullet list) and speak to the user directly as \"you\".\n"
    )
