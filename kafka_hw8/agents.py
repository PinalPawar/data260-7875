"""HW8 Part 2: Planner, Writer and Reviewer. Each runs as its own process (planner.py, writer.py,
reviewer.py at the repo root) and only ever talks to the others through Kafka:

    you -> s7875_inbox -> Planner -> s7875_tasks -> Writer -> s7875_drafts
        -> Reviewer -> s7875_final

correlation_id is copied unchanged from the question into every later message, and each agent
adds one entry to `trace` (which topic/partition/offset it read, and when), so the final message
carries its whole journey. Messages are keyed by correlation_id.

The Writer also handles the Part 3 ordering test messages (kind == "order_test"): it records
the order it processed them in and sends nothing on.
"""

import asyncio
import json
import os
import re

from .agent_base import KafkaAgent, Out, main, trace_entry
from .config import (
    DRAFTS_TOPIC,
    FINAL_TOPIC,
    INBOX_TOPIC,
    PLANNER_GROUP,
    REVIEWER_GROUP,
    TASKS_TOPIC,
    WRITER_GROUP,
)
from .llm import chat, model_label
from .logutil import log, now

# Food-safety rules every agent gets. Added after the first real run: qwen3:1.7b planned a step
# "determine if the spinach you ate is still safe", wrote "it may still be safe", and the
# Reviewer approved it. A recalled product is never safe to eat, whatever its date or batch.
RECALL_SAFETY = (
    "Food-safety rules: a recalled product must never be eaten, whatever its date, batch or how "
    "it looks or smells. Tell the reader to stop using it and throw it away or return it to the "
    "store, and to clean surfaces it touched. If they already ate some, tell them to watch for "
    "the illness's symptoms and to call a doctor, sooner if they are pregnant, older, or have a "
    "weak immune system. Never suggest a recalled product might still be safe."
)
PLANNER_SYSTEM = (
    "You are the Planner agent of a grocery recall-notice assistant. Break the user's question "
    "into 2 to 4 short steps that a writer should cover in the answer. Reply with one step per "
    "line and nothing else: no numbering, no title, no extra text. " + RECALL_SAFETY
)
WRITER_SYSTEM = (
    "You are the Writer agent of a grocery recall-notice assistant. Write the answer to the "
    "question, covering every step of the plan in order. Plain text, at most 120 words, no "
    "headings, no lists. Do not invent specific lot numbers, dates or brands. " + RECALL_SAFETY
)
REVIEWER_SYSTEM = (
    "You are the Reviewer agent of a grocery recall-notice assistant. Check the draft answer "
    "against the question and the plan: it must answer the question, cover the plan, and give "
    "safe advice. REJECT any draft that says or hints that a recalled product could be safe to "
    "eat. Reply with exactly one line, either 'APPROVE: <short reason>' or "
    "'REJECT: <short reason>'. " + RECALL_SAFETY
)
# Rule check run before the model review: phrases that call recalled food safe. "is not safe"
# does not match (the word "not" sits between "is" and "safe").
UNSAFE_PATTERNS = [
    r"\b(?:may|might|could|can|should|would|is|are|be)\s+(?:still\s+)?(?:be\s+)?"
    r"(?:fine|ok|okay|safe)\b(?!\s+to\s+say)",
    r"\bit'?s\s+(?:still\s+)?(?:fine|ok|okay|safe)\b(?!\s+to\s+say)",
    r"\bsafe\s+to\s+(?:eat|consume|keep\s+eating)\b",
]
MAX_DRAFT_WORDS = 200


def parse_plan(text: str) -> list[str]:
    steps = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)]|step\s*\d+[:.)]?)\s*", "", line,
                      flags=re.I).strip()
        if line:
            steps.append(line)
    return steps[:4]


def unsafe_phrase(draft: str) -> str | None:
    """The first phrase in the draft that calls a recalled product safe, or None."""
    for pat in UNSAFE_PATTERNS:
        m = re.search(pat, draft, flags=re.I)
        if m:
            before = draft[max(0, m.start() - 12):m.start()].lower()
            if re.search(r"\b(?:not|never|no longer)\s*$", before):
                continue  # "it is not safe to eat" / "never safe" is the right message
            return m.group(0)
    return None


def parse_review(text: str) -> tuple[str, str]:
    """(status, reason). status is approved / rejected / needs_human_review."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    m = re.match(r"\W*(APPROVE|REJECT)\w*\W*\s*(.*)", first, flags=re.I)
    if not m:
        return "needs_human_review", f"reviewer reply not in APPROVE/REJECT form: {first[:120]}"
    verdict, reason = m.group(1).upper(), m.group(2).strip()
    return ("approved" if verdict == "APPROVE" else "rejected"), reason


class Planner(KafkaAgent):
    name = "planner"
    in_topic = INBOX_TOPIC
    group = PLANNER_GROUP

    async def handle(self, msg, record):
        question = msg.get("question") if isinstance(msg, dict) else None
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question is missing or empty")
        reply = await asyncio.to_thread(chat, PLANNER_SYSTEM, question)
        plan = parse_plan(reply)
        if not plan:
            raise ValueError("model returned an empty plan")
        log(self.tag, "PROCESS-DONE", msg.get("correlation_id"), steps=len(plan),
            model=model_label())
        out = {
            "correlation_id": msg["correlation_id"],
            "stage": "plan",
            "question": question,
            "plan": plan,
            "trace": msg.get("trace", []) + [trace_entry(self, record)],
        }
        return [Out(TASKS_TOPIC, msg["correlation_id"], out)]


class Writer(KafkaAgent):
    name = "writer"
    in_topic = TASKS_TOPIC
    group = WRITER_GROUP

    async def handle(self, msg, record):
        if isinstance(msg, dict) and msg.get("kind") == "order_test":
            return await self._order_test(msg, record)
        plan = msg.get("plan") if isinstance(msg, dict) else None
        question = msg.get("question") if isinstance(msg, dict) else None
        if not isinstance(plan, list) or not plan or not all(isinstance(p, str) for p in plan):
            raise ValueError("task has no usable plan (expected a non-empty list of steps)")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("task has no question")
        prompt = (f"Question: {question}\n\nPlan:\n" + "\n".join(f"- {p}" for p in plan)
                  + "\n\nWrite the answer now.")
        draft = (await asyncio.to_thread(chat, WRITER_SYSTEM, prompt)).strip()
        if not draft:
            raise ValueError("model returned an empty draft")
        log(self.tag, "PROCESS-DONE", msg.get("correlation_id"), words=len(draft.split()),
            model=model_label())
        out = {**{k: msg[k] for k in ("correlation_id", "question", "plan")},
               "stage": "draft", "draft": draft,
               "trace": msg.get("trace", []) + [trace_entry(self, record)]}
        return [Out(DRAFTS_TOPIC, msg["correlation_id"], out)]

    async def _order_test(self, msg, record):
        await asyncio.sleep(msg.get("work_ms", 0) / 1000)
        row = {"writer": self.agent_id, "partition": record.partition, "offset": record.offset,
               "key": record.key.decode() if record.key else None,
               "message_id": msg["message_id"], "entity": msg["entity"], "seq": msg["seq"],
               "run": msg.get("run"), "processed_at": now()}
        log(self.tag, "ORDER-PROCESSED", msg.get("correlation_id"), entity=msg["entity"],
            seq=msg["seq"], p=record.partition, off=record.offset)
        path = os.getenv("HW8_ORDER_LOG")
        if path:
            with open(path, "a") as fh:
                fh.write(json.dumps(row) + "\n")
        return []


class Reviewer(KafkaAgent):
    name = "reviewer"
    in_topic = DRAFTS_TOPIC
    group = REVIEWER_GROUP

    async def handle(self, msg, record):
        draft = msg.get("draft") if isinstance(msg, dict) else None
        if not isinstance(draft, str) or not draft.strip():
            raise ValueError("draft is missing or empty")
        words = len(draft.split())
        unsafe = unsafe_phrase(draft)
        if words > MAX_DRAFT_WORDS:  # rule checks first; no model call needed
            status, reason = "rejected", f"draft too long ({words} words > {MAX_DRAFT_WORDS})"
        elif unsafe:
            status, reason = "rejected", (f"rule check: draft calls a recalled product safe "
                                          f"(\"{unsafe}\")")
        else:
            prompt = (f"Question: {msg.get('question')}\n\nPlan:\n"
                      + "\n".join(f"- {p}" for p in msg.get("plan", []))
                      + f"\n\nDraft answer:\n{draft}")
            status, reason = parse_review(await asyncio.to_thread(chat, REVIEWER_SYSTEM, prompt))
        log(self.tag, "PROCESS-DONE", msg.get("correlation_id"), status=status,
            model=model_label())
        final = {
            "correlation_id": msg["correlation_id"],
            "status": status,
            "answer": draft,
            "review": reason,
            "question": msg.get("question"),
            "plan": msg.get("plan"),
            "model": model_label(),
            "trace": msg.get("trace", []) + [trace_entry(self, record)],
            "finished_at": now(),
        }
        return [Out(FINAL_TOPIC, msg["correlation_id"], final)]


__all__ = ["Planner", "Writer", "Reviewer", "main"]
