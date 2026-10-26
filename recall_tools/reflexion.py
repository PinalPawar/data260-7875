"""
HW7 Part 3: a bounded Reflexion path around the Part 2 agent loop.

    run_reflexion(task, user_id) -> {"status", "attempts", "reflections", ...}

1. Run the Part 2 loop (run_agent) on the task.
2. Check the result with the task's deterministic verifier (task_checks.verify_task).
3. If it failed, write ONE short reflection (what went wrong + a better strategy) and
   store it with the evidence from the failed run: the failed checks, the last tool
   call and its observation.
4. Retry with the reflection in context. At most MAX_RETRIES retries.

Bounds: a hard tool-call budget and token budget shared by all attempts of one task.
The run always ends with exactly one status: success, budget_exhausted or human_review.

Reflections are untrusted data. They are stored per (user_id, run_id) and only ever
read back for that same user and run; they are passed to run_agent as labelled
user-role notes, never into the system prompt, and they cannot change the tool list
or execute_tool's safety gate (run_agent sends the same schemas and prompt every time).
Only a concise failure explanation and strategy are kept, never hidden reasoning.
"""

import json
import os
import re
import uuid
from datetime import datetime
from typing import Callable, Optional

from recall_tools.agent_loop import SEED, hw1_chat, run_agent
from recall_tools.task_checks import verify_task

MAX_RETRIES = 2
TOOL_CALL_BUDGET = 12  # all attempts of one task together
TOKEN_BUDGET = 40000  # prompt + completion tokens, all attempts of one task together
MAX_REFLECTION_CHARS = 400
STORE_PATH = os.path.join("reports", "hw07", "raw", "part3_reflections.jsonl")
# Text a reflection may never carry into the next attempt (it is data, not instructions).
_BLOCKED = re.compile(
    r"system prompt|ignore (all|previous|the above)|you are now|new instructions|"
    r"disable|bypass|safety|permission|allow (the )?tool",
    re.IGNORECASE,
)
REFLECT_SYSTEM = (
    "You review a failed attempt by a recall-notice assistant. Using only the evidence given, "
    "write exactly two short sentences: first what went wrong, then a better strategy for the "
    "next attempt (which tool to call, in what order, and what to cite). Do not repeat the "
    "evidence and do not write anything else."
)


class ReflectionStore:
    """Append-only JSONL store; reads are always filtered to one user and one run."""

    def __init__(self, path: str = STORE_PATH):
        self.path = path

    def add(self, record: dict) -> None:
        """Append one reflection record."""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def for_run(self, user_id: str, run_id: str) -> list:
        """Only this user's reflections from this run (isolation by construction)."""
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        return [r for r in rows if r["user_id"] == user_id and r["run_id"] == run_id]


def sanitize_reflection(text: str) -> str:
    """One line, length-capped, with instruction-like sentences removed."""
    sentences = re.split(r"(?<=[.!?])\s+", " ".join((text or "").split()))
    kept = [s for s in sentences if s and not _BLOCKED.search(s)]
    return " ".join(kept)[:MAX_REFLECTION_CHARS].strip()


def build_evidence(result: dict, verdict: dict) -> dict:
    """The facts that triggered the reflection: failed checks, last call and its observation."""
    last = result["trace"][-1] if result["trace"] else None
    observation = None
    if last:
        observation = json.dumps(last["result"].get("data") or last["result"].get("error"))[:300]
    return {
        "failed_checks": [c for c in verdict["checks"] if not c["passed"]],
        "passed_checks": [c for c in verdict["checks"] if c["passed"]],
        "unsupported_claims": verdict["unsupported_claims"],
        "tool_sequence": [f"{t['tool']}({json.dumps(t['arguments'])})" for t in result["trace"]],
        "last_tool_call": f"{last['tool']}({json.dumps(last['arguments'])})" if last else None,
        "last_observation": observation,
        "stop_reason": result["stop_reason"],
        "answer_excerpt": result["answer"][:200],
    }


# Verifier-grounded strategies: one fixed sentence per failed check, filled from the evidence.
GROUNDED_STRATEGY = {
    "search_ran": "Start with search_notices for the product named in the question.",
    "detail_of_first_result": "Call get_notice_detail on the first code in the search results "
    "({detail}).",
    "answer_cites_code": "After the lookup, stop calling tools and answer citing that notice code.",
    "aggregate_ran": "First call recall_stats with group_by category.",
    "example_from_top_group": "Then search with the top category from recall_stats as the filter.",
    "two_detail_lookups": "Look up exactly the first two search results ({detail}).",
    "answer_cites_both": "After the two lookups, stop calling tools and cite both codes ({pair}).",
    "answer_reports_pair_facts": "Answer only from the two get_notice_detail results: give each "
    "notice's units_affected and manufacturer and say which affected more units; do not use "
    "recall_stats totals.",
    "no_unsupported_codes": "Never write a code that no tool returned ({detail}).",
}


def grounded_reflection(task: dict, evidence: dict) -> str:
    """Reflection written from the verifier's evidence instead of the model's self-diagnosis."""
    checks = evidence["failed_checks"] + evidence.get("passed_checks", [])
    lookup_detail = next((c["detail"] for c in checks if c["check"] == "two_detail_lookups"), "")
    pair = " and ".join(re.findall(r"RCL-\d{4}-\d{5}", lookup_detail.split(";")[0]))
    failed = [c["check"] for c in evidence["failed_checks"]]
    steps = [
        GROUNDED_STRATEGY[c["check"]].format(detail=c["detail"], pair=pair)
        for c in evidence["failed_checks"]
        if c["check"] in GROUNDED_STRATEGY
    ]
    names = [t.split("(")[0] for t in evidence["tool_sequence"]]
    counts = {n: names.count(n) for n in dict.fromkeys(names)}
    calls = ", ".join(n if k == 1 else f"{n} x{k}" for n, k in counts.items()) or "no tools"
    return f"Last attempt called {calls}; failed {', '.join(failed)}. " + " ".join(steps)


grounded_reflection.source = "grounded"  # label stored with each reflection


def template_reflection(evidence: dict) -> str:
    """Deterministic fallback when the model's reflection is unusable."""
    failed = ", ".join(c["check"] for c in evidence["failed_checks"]) or "verifier"
    calls = "; ".join(evidence["tool_sequence"]) or "no tool calls"
    return (
        f"The previous attempt failed the {failed} check after these calls: {calls}. "
        "Call each tool the question needs, one at a time, use codes only from earlier "
        "results, and answer exactly the question while citing those codes."
    )


def write_reflection(task: dict, evidence: dict, reflect: Optional[Callable]) -> tuple:
    """Model-written two-sentence reflection, else the template.

    reflect() may return a string or the adapter's dict (content + token counts).
    Returns (text, source, tokens_spent).
    """
    tokens = 0
    if reflect is not None:
        try:
            reply = reflect(task, evidence)
        except Exception:  # model down or bad reply: the template still gives a usable reflection
            reply = ""
        if isinstance(reply, dict):
            tokens = (reply.get("input_tokens") or 0) + (reply.get("output_tokens") or 0)
            reply = reply.get("content", "")
        text = sanitize_reflection(reply)
        if len(text) >= 30:
            return text, getattr(reflect, "source", "model"), tokens
    return sanitize_reflection(template_reflection(evidence)), "template", tokens


def model_reflector(temperature: float = 0.0, seed: int = SEED) -> Callable:
    """Reflection writer backed by the HW1 adapter (no tools offered)."""
    from src.model_client import complete

    def reflect(task: dict, evidence: dict) -> dict:
        """Two sentences from the evidence only."""
        messages = [
            {"role": "system", "content": REFLECT_SYSTEM},
            {
                "role": "user",
                "content": f"Task: {task['prompt']}\nEvidence: {json.dumps(evidence)}",
            },
        ]
        reply = complete(
            messages,
            model=os.getenv("HW7_MODEL", "qwen3:1.7b"),
            temperature=temperature,
            seed=seed,
            think=False,
            max_tokens=120,
        )
        return reply  # content plus token counts, so reflection cost is budgeted too

    return reflect


def _attempt_summary(n: int, result: dict, verdict: dict, notes: list) -> dict:
    """What one attempt cost and how it scored (kept for the comparison table)."""
    return {
        "attempt": n,
        "passed": verdict["passed"],
        "stop_reason": result["stop_reason"],
        "tool_calls": result["tool_calls"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "latency_ms": result["latency_ms"],
        "unsupported_claims": verdict["unsupported_claims"],
        "notes_in_context": len(notes),
        "checks": verdict["checks"],
        "answer": result["answer"],
        "trace": result["trace"],
    }


def _reflect_and_store(ctx: dict, n: int, result: dict, verdict: dict) -> None:
    """Write one reflection for a failed attempt and append it to the store."""
    evidence = build_evidence(result, verdict)
    text, source, tokens = write_reflection(ctx["task"], evidence, ctx["reflect"])
    ctx["tokens"] += tokens
    record = {
        "user_id": ctx["user_id"],
        "run_id": ctx["run_id"],
        "task_id": ctx["task"]["id"],
        "failed_attempt": n,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reflection": text,
        "source": source,
        "reflection_tokens": tokens,
        "evidence": evidence,
    }
    ctx["store"].add(record)
    ctx["reflections"].append(record)


def _run_attempt(ctx: dict, n: int, chat_for: Callable, tool_store) -> tuple[dict, dict]:
    """One attempt inside the remaining budgets, with this run's reflections as notes."""
    notes = [r["reflection"] for r in ctx["store"].for_run(ctx["user_id"], ctx["run_id"])]
    result = run_agent(
        ctx["task"]["prompt"],
        chat=chat_for(n),
        store=tool_store,
        context_notes=notes,
        max_tool_calls=TOOL_CALL_BUDGET - ctx["calls"],
        max_tokens=TOKEN_BUDGET - ctx["tokens"],
    )
    verdict = verify_task(ctx["task"], result)
    ctx["attempts"].append(_attempt_summary(n, result, verdict, notes))
    ctx["calls"] += result["tool_calls"]
    ctx["tokens"] += result["input_tokens"] + result["output_tokens"]
    return result, verdict


def _new_context(task: dict, user_id: str, reflect, store) -> dict:
    """Per-run state: a fresh run_id isolates this run's reflections from every other run."""
    return {
        "task": task,
        "user_id": user_id,
        "run_id": uuid.uuid4().hex[:8],
        "reflect": reflect,
        "store": store or ReflectionStore(),
        "reflections": [],
        "attempts": [],
        "calls": 0,
        "tokens": 0,
    }


def _final(ctx: dict, status: str) -> dict:
    """The Reflexion run as a plain dict."""
    return {
        "task_id": ctx["task"]["id"],
        "user_id": ctx["user_id"],
        "run_id": ctx["run_id"],
        "status": status,
        "retries": len(ctx["attempts"]) - 1,
        "attempts": ctx["attempts"],
        "reflections": ctx["reflections"],
        "tool_calls": ctx["calls"],
        "tokens": ctx["tokens"],
        "latency_ms": round(sum(a["latency_ms"] for a in ctx["attempts"]), 1),
    }


def run_reflexion(
    task: dict,
    user_id: str,
    chat_for: Optional[Callable] = None,
    reflect: Optional[Callable] = None,
    store: Optional[ReflectionStore] = None,
    tool_store=None,
) -> dict:
    """Run a task with at most MAX_RETRIES Reflexion retries inside hard budgets.

    chat_for(attempt_number) returns the chat function for that attempt (attempt 0 is the
    original Part 2 run). Returns status success | budget_exhausted | human_review.
    """
    chat_for = chat_for or (lambda n: hw1_chat(seed=SEED + 1000 * n))
    ctx = _new_context(task, user_id, reflect, store)
    for n in range(MAX_RETRIES + 1):
        if ctx["calls"] >= TOOL_CALL_BUDGET or ctx["tokens"] >= TOKEN_BUDGET:
            return _final(ctx, "budget_exhausted")
        result, verdict = _run_attempt(ctx, n, chat_for, tool_store)
        if verdict["passed"]:
            return _final(ctx, "success")
        if result["stop_reason"] == "budget_exhausted":
            return _final(ctx, "budget_exhausted")
        if n < MAX_RETRIES:
            _reflect_and_store(ctx, n, result, verdict)
    return _final(ctx, "human_review")  # every allowed retry still failed the verifier
