"""HW6 Part 4 - /dream: find durable facts in the recent conversation and add them to MEMORY.md.

Only the user's own messages are used as evidence. The model proposes facts as
JSON with a key from a fixed list; facts that MEMORY.md already contains (same
key and meaning) are skipped, so /dream never creates duplicates. New facts are
stored with source "dream", which ranks below facts the user stated directly
when consolidation resolves a contradiction.
"""
import json
import re
from typing import Callable, Dict, List, Tuple

from .consolidate import Fact, parse_memory, same_meaning

DREAM_KEYS = {
    "user.name": "the user's own name", "user.city": "the city the user lives in",
    "allergy.user": "the USER's own food allergies", "allergy.son": "the user's SON's food allergies",
    "health.user": "the user's own health conditions", "family.son_name": "the son's name",
    "family.son_age": "the son's age", "family.sister": "the user's sister",
    "store.main": "the store where the user shops (a store name only)",
    "store.day": "the day the user shops", "home.food": "a food the user has at home or just bought",
    "recall.returned": "a product the user returned because of a recall",
    "alert.channel": "how the user wants recall alerts", "pref.answer_style": "how the user likes answers",
    "note": "any other durable fact about the user",
}
EXAMPLE = ('[{"key": "allergy.son", "value": "allergic to eggs"}, '
           '{"key": "home.food", "value": "whole cantaloupe"}]')
KEY_RE = re.compile(r"^[a-z][a-z0-9_.]*$")


def build_dream_prompt(messages: List[Dict[str, str]]) -> str:
    """Prompt asking the model for durable facts stated by the user."""
    said = "\n".join(f"- {m['content']}" for m in messages if m["role"] == "user")
    keys = "\n".join(f"  {k}: {meaning}" for k, meaning in DREAM_KEYS.items())
    return (
        "From the USER messages below, list durable facts about the user worth remembering "
        "in later conversations (identity, family, allergies, stores, products at home, "
        "recalls, preferences). Ignore questions and facts about other people unless they "
        "are family. Choose the key whose meaning fits exactly:\n" + keys + "\n"
        "Example: for 'My son is allergic to eggs. I bought a whole cantaloupe.' reply " + EXAMPLE + "\n"
        "Reply with ONLY a JSON list of {key, value} objects, or [] if there is nothing durable."
        "\n\nUSER messages:\n" + said + " /no_think"
    )


def parse_dream_reply(reply: str, today: str) -> List[Fact]:
    """Turn the model's JSON reply into Fact objects; invalid items are skipped."""
    start, end = reply.find("["), reply.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(reply[start:end + 1])
    except json.JSONDecodeError:
        return []
    facts = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        key, value = str(item.get("key", "")).strip().lower(), str(item.get("value", "")).strip()
        value = value.replace("(", "").replace(")", "")[:120]
        if KEY_RE.match(key) and value:
            facts.append(Fact(today, key, value, "dream"))
    return facts


def new_facts_only(candidates: List[Fact], existing: List[Fact]) -> List[Fact]:
    """Drop candidates that MEMORY.md (or an earlier candidate) already holds."""
    kept: List[Fact] = []
    for fact in candidates:
        known = existing + kept
        if not any(f.key == fact.key and same_meaning(f.value, fact.value) for f in known):
            kept.append(fact)
    return kept


def append_facts(text: str, facts: List[Fact]) -> str:
    """Insert fact lines at the end of the '## Facts' section (created if missing)."""
    if not facts:
        return text
    lines = text.rstrip("\n").splitlines()
    new = [f.line() for f in facts]
    if "## Facts" not in [l.strip() for l in lines]:
        return "\n".join(lines + ["## Facts"] + new) + "\n"
    start = [l.strip() for l in lines].index("## Facts")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[:end] + new + lines[end:]) + "\n"


def dream(messages: List[Dict[str, str]], memory_text: str,
          complete_fn: Callable[[List[Dict[str, str]]], str], today: str) -> Tuple[str, List[Fact]]:
    """Run /dream: ask the model for facts, keep the new ones, return (new MEMORY.md, added facts)."""
    reply = complete_fn([{"role": "user", "content": build_dream_prompt(messages)}])
    existing, _, _ = parse_memory(memory_text)
    added = new_facts_only(parse_dream_reply(reply, today), existing)
    return append_facts(memory_text, added), added
