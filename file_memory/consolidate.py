"""HW6 Part 4 - consolidating MEMORY.md.

Every fact is one line:   - [YYYY-MM-DD] key = value (source: user)
Consolidation
  1. merges duplicates: same key and an equivalent value (word overlap,
     negation-aware) become one line that records how many were merged;
  2. resolves contradictions on single-valued keys with the rule
     "newest wins", and records every replaced value under
     "## Resolved contradictions", so nothing is deleted silently;
  3. checks every resolution: if the replaced value came from a stronger
     source (user/doctor beats dream/assistant) or the key is safety-critical
     (allergies, health), the newest-wins result is marked as likely
     incorrect, the stronger fact is kept active and the case goes to
     "## Needs review".
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .memory_files import count_memory_lines, set_last_consolidated

FACT_RE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*([a-z][a-z0-9_.]*)\s*=\s*(.+?)\s*"
                     r"\(source:\s*([a-z ]+?)\s*\)\s*(?:\(([^()]*)\))?\s*$")
MULTI_VALUED = {"home.food", "recall.returned", "family.member", "note"}
SAFETY_PREFIXES = ("allergy.", "health.")
SOURCE_RANK = {"doctor": 3, "user": 2, "store": 2, "dream": 1, "assistant": 1, "inferred": 1}
HISTORY_SECTIONS = ("resolved contradictions", "needs review")
NEGATIONS = {"no", "not", "never", "none", "without", "dont", "doesnt", "isnt"}
STOPWORDS = {"a", "an", "the", "to", "of", "and", "is", "are", "in", "on", "for", "at", "my",
             "his", "her", "their", "user", "he", "she", "it", "very", "every", "because"}
SIMILAR = 0.6


@dataclass
class Fact:
    """One fact line of MEMORY.md."""
    date: str
    key: str
    value: str
    source: str
    merged: int = 1
    tag: str = ""

    def line(self) -> str:
        """Render the fact as a MEMORY.md line."""
        tags = [f"merged {self.merged}"] if self.merged > 1 else []
        tags += [self.tag] if self.tag else []
        suffix = f" ({'; '.join(tags)})" if tags else ""
        return f"- [{self.date}] {self.key} = {self.value} (source: {self.source}){suffix}"


def parse_memory(text: str) -> Tuple[List[Fact], Dict[str, List[str]], List[str]]:
    """Split MEMORY.md into facts, history lines (per section) and other notes."""
    facts, history, notes, section = [], {s: [] for s in HISTORY_SECTIONS}, [], ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)   # comments (incl. multi-line) are not data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section in HISTORY_SECTIONS:
            history[section].append(line)
            continue
        match = FACT_RE.match(line)
        if match:
            date, key, value, source, tag = match.groups()
            merged = re.search(r"merged (\d+)", tag or "")
            facts.append(Fact(date, key, value.strip(), source.strip(),
                              int(merged.group(1)) if merged else 1,
                              "under review" if "under review" in (tag or "") else ""))
        else:
            notes.append(line)
    return facts, history, notes


def _stem(word: str) -> str:
    """Very small stemmer: 'allergic'/'allergy'/'allergies' and 'Saturday'/'Saturdays' match."""
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3]
    elif word.endswith("es") and len(word) > 4:
        word = word[:-2]
    elif word.endswith("s") and len(word) > 3:
        word = word[:-1]
    if word.endswith("ic") and len(word) > 4:
        word = word[:-2]
    elif word.endswith("y") and len(word) > 4:
        word = word[:-1]
    return word


def normalize(value: str) -> set:
    """Lower-case, drop punctuation and stopwords, and stem a fact value."""
    words = re.findall(r"[a-z0-9]+", value.lower().replace("'", ""))
    return {_stem(w) for w in words if w not in STOPWORDS}


def same_meaning(a: str, b: str) -> bool:
    """True when two values say the same thing (word overlap, negation-aware)."""
    wa, wb = normalize(a), normalize(b)
    if bool(wa & NEGATIONS) != bool(wb & NEGATIONS):
        return False
    numbers_a, numbers_b = {w for w in wa if w.isdigit()}, {w for w in wb if w.isdigit()}
    if numbers_a and numbers_b and numbers_a != numbers_b:
        return False          # "3 years old" and "4 years old" are different facts
    wa, wb = wa - NEGATIONS, wb - NEGATIONS
    if not wa or not wb:
        return wa == wb
    return len(wa & wb) / min(len(wa), len(wb)) >= SIMILAR


def merge_duplicates(facts: List[Fact]) -> Tuple[List[Fact], List[str]]:
    """Merge facts with the same key and meaning; keep the newest wording."""
    clusters: List[List[Fact]] = []
    for fact in facts:
        home = next((c for c in clusters if c[0].key == fact.key
                     and same_meaning(c[0].value, fact.value)), None)
        if home is None:
            clusters.append([fact])
        else:
            home.append(fact)
    merged, log = [], []
    for cluster in clusters:
        newest = max(cluster, key=lambda f: (f.date, SOURCE_RANK.get(f.source, 0)))
        best = max(cluster, key=lambda f: SOURCE_RANK.get(f.source, 0)).source
        total = sum(f.merged for f in cluster)
        tag = "under review" if any(f.tag for f in cluster) else ""
        merged.append(Fact(newest.date, newest.key, newest.value, best, total, tag))
        if len(cluster) > 1:
            log.append(f"{newest.key}: merged {len(cluster)} lines into \"{newest.value}\"")
    return merged, log


def combine_lists(facts: List[Fact]) -> Tuple[List[Fact], List[str]]:
    """Put all items of a multi-valued key (e.g. home.food) on one line, oldest first."""
    out, log, groups = [], [], {}
    for fact in facts:
        if fact.key in MULTI_VALUED:
            groups.setdefault(fact.key, []).append(fact)
        else:
            out.append(fact)
    for key, items in groups.items():
        items.sort(key=lambda f: f.date)
        if len(items) == 1:
            out.append(items[0])
            continue
        best = max(items, key=lambda f: SOURCE_RANK.get(f.source, 0)).source
        value = "; ".join(f.value for f in items)
        out.append(Fact(items[-1].date, key, value, best, sum(f.merged for f in items)))
        log.append(f"{key}: {len(items)} items combined into one list line")
    return out, log


def _rank(fact: Fact) -> int:
    """Strength of a fact's source."""
    return SOURCE_RANK.get(fact.source, 0)


def resolve_key(group: List[Fact], today: str) -> Tuple[Fact, List[str], Optional[str]]:
    """Resolve one contradicting key: newest wins, then check the result."""
    ordered = sorted(group, key=lambda f: (f.date, _rank(f)), reverse=True)
    newest, losers = ordered[0], ordered[1:]
    stronger = [f for f in losers if _rank(f) > _rank(newest)]
    safety = newest.key.startswith(SAFETY_PREFIXES)
    if not stronger and not safety:
        old = "; ".join(f"\"{f.value}\" ({f.date}, {f.source})" for f in losers)
        return newest, [f"- {newest.key}: kept \"{newest.value}\" ({newest.date}, {newest.source}); "
                        f"replaced {old} - rule: newest wins [{today}]"], None
    keep = max(group, key=lambda f: (_rank(f), f.date))
    keep.tag = "under review"
    others = "; ".join(f"\"{f.value}\" ({f.date}, {f.source})" for f in group if f is not keep)
    why = ("the replaced value came from a stronger source" if stronger
           else "the key is safety-critical")
    note = (f"- {newest.key}: newest-wins would keep \"{newest.value}\" ({newest.date}, {newest.source}) "
            f"- LIKELY INCORRECT because {why}; kept \"{keep.value}\" ({keep.date}, {keep.source}) "
            f"active; conflicting: {others}; confirm with the user [{today}]")
    return keep, [], note


def resolve_contradictions(facts: List[Fact], today: str) -> Tuple[List[Fact], List[str], List[str]]:
    """Apply resolve_key to every single-valued key that has several values."""
    by_key: Dict[str, List[Fact]] = {}
    for fact in facts:
        by_key.setdefault(fact.key, []).append(fact)
    active, resolved, review = [], [], []
    for key, group in by_key.items():
        if len(group) == 1 or key in MULTI_VALUED:
            active.extend(group)
            continue
        kept, resolved_lines, review_line = resolve_key(group, today)
        active.append(kept)
        resolved.extend(resolved_lines)
        review.extend([review_line] if review_line else [])
    return active, resolved, review


def render(facts: List[Fact], history: Dict[str, List[str]], notes: List[str]) -> str:
    """Write the consolidated MEMORY.md text (stamp is added by consolidate)."""
    lines = ["# MEMORY.md - durable facts (file-based memory)",
             "<!-- format: - [YYYY-MM-DD] key = value (source: user|doctor|dream|assistant) -->",
             "## Facts"]
    lines += [f.line() for f in sorted(facts, key=lambda f: (f.key, f.date))]
    lines += notes
    for section in HISTORY_SECTIONS:
        if history[section]:
            lines += [f"## {section.capitalize()}"] + history[section]
    return "\n".join(lines) + "\n"


def consolidate(text: str, now: Optional[datetime] = None) -> Tuple[str, dict]:
    """Consolidate a MEMORY.md text. Returns (new text, report)."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    facts, history, notes = parse_memory(text)
    merged, merge_log = merge_duplicates(facts)
    merged, list_log = combine_lists(merged)
    active, resolved, review = resolve_contradictions(merged, today)
    history["resolved contradictions"] += resolved
    history["needs review"] += review
    new_text = set_last_consolidated(render(active, history, notes), now)
    report = {
        "lines_before": count_memory_lines(text), "lines_after": count_memory_lines(new_text),
        "facts_before": len(facts), "facts_after": len(active),
        "duplicates_merged": merge_log, "lists_combined": list_log,
        "contradictions_resolved": resolved,
        "needs_review": review, "consolidated_at": now.isoformat(timespec="seconds"),
    }
    return new_text, report


def format_report(report: dict) -> str:
    """Human-readable consolidation report (Markdown)."""
    out = [f"Lines: {report['lines_before']} -> {report['lines_after']}   "
           f"Facts: {report['facts_before']} -> {report['facts_after']}"]
    out += ["", f"Duplicates merged ({len(report['duplicates_merged'])}):"]
    out += [f"  - {m}" for m in report["duplicates_merged"]]
    out += ["", f"List facts combined ({len(report.get('lists_combined', []))}):"]
    out += [f"  - {m}" for m in report.get("lists_combined", [])]
    out += ["", f"Contradictions resolved by newest-wins ({len(report['contradictions_resolved'])}):"]
    out += [f"  {r}" for r in report["contradictions_resolved"]]
    out += ["", f"Resolutions flagged as likely incorrect / needs review ({len(report['needs_review'])}):"]
    out += [f"  {r}" for r in report["needs_review"]]
    return "\n".join(out)
