from __future__ import annotations

from typing import TypedDict, Optional, Dict, Any

from agents_demo import (
    strip_code_and_md,
    extract_json_block,
    coerce_reply,
    parse_and_coerce,
)
from src.model_client import complete


class AgentState(TypedDict):
    title: str
    content: str
    email: str
    strict: bool
    task: str
    llm: str

    planner_proposal: Optional[dict]
    reviewer_feedback: Optional[dict]
    turn_count: int


PLANNER_SYSTEM = (
    "Propose exactly 3 distinct, topical tags (prefer multi-word phrases) "
    "and a one-line summary for the blog post."
)


def _build_task(title: str, content: str, email: str) -> str:
    return (
        f'Given blog title "{title}" and content "{content}", produce exactly 3 topical tags '
        f'and a one-sentence summary in your own words. Email is {email}.'
    )


def planner_node(state: AgentState) -> Dict[str, Any]:
    print("[Planner] Node activated")

    title = state["title"]
    content = state["content"]
    email = state["email"]
    strict = state["strict"]

    task = _build_task(title, content, email)

    history_lines = []
    reviewer_feedback = state.get("reviewer_feedback")
    if reviewer_feedback:
        history_lines.append(f"Reviewer: {reviewer_feedback.get('message', '')}")
    history_text = "\n".join(history_lines) or "(empty)"

    human_prompt = (
        f"Task:\n{task}\n\nConversation so far:\n{history_text}\n\n"
        "Return ONLY one JSON object (no code fences, no markdown, no explanations). "
        "Keys: thought (string), message (non-empty, <=60 words, no code), "
        "data.tags (array of exactly 3 topical tags), "
        "data.summary (<=25 words, no ellipses), data.issues (array).\n"
        "Do not add extra text outside JSON."
    )

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": human_prompt},
    ]

    result = complete(messages, model=state["llm"])
    proposal = parse_and_coerce(result["content"], title, content, strict)

    # Clear out old Reviewer feedback: it was about the previous proposal, not this new one.
    return {"planner_proposal": proposal, "reviewer_feedback": None}


REVIEWER_SYSTEM = (
    "Validate: tags topical and not generic; summary ≤ 25 words; no code or markdown. "
    "If issues, list in data.issues; otherwise echo cleaned tags/summary."
)


def reviewer_node(state: AgentState) -> Dict[str, Any]:
    print("[Reviewer] Node activated")

    title = state["title"]
    content = state["content"]
    email = state["email"]
    strict = state["strict"]

    task = _build_task(title, content, email)

    history_lines = []
    planner_proposal = state.get("planner_proposal")
    if planner_proposal:
        history_lines.append(f"Planner: {planner_proposal.get('message', '')}")
    history_text = "\n".join(history_lines) or "(empty)"

    human_prompt = (
        f"Task:\n{task}\n\nConversation so far:\n{history_text}\n\n"
        "Return ONLY one JSON object (no code fences, no markdown, no explanations). "
        "Keys: thought (string), message (non-empty, <=60 words, no code), "
        "data.tags (array of exactly 3 topical tags), "
        "data.summary (<=25 words, no ellipses), data.issues (array).\n"
        "Do not add extra text outside JSON."
    )

    messages = [
        {"role": "system", "content": REVIEWER_SYSTEM},
        {"role": "user", "content": human_prompt},
    ]

    result = complete(messages, model=state["llm"])
    feedback = parse_and_coerce(result["content"], title, content, strict)

    return {"reviewer_feedback": feedback}


from typing import Literal
from langgraph.graph import StateGraph, END


TURN_CEILING = 4


def supervisor_node(state: AgentState) -> Dict[str, Any]:
    print("[Supervisor] Node activated")
    return {"turn_count": state.get("turn_count", 0) + 1}


def router_logic(state: AgentState) -> Literal["planner", "reviewer", "END"]:
    if not state.get("planner_proposal"):
        return "planner"
    if not state.get("reviewer_feedback"):
        return "reviewer"
    issues = state["reviewer_feedback"].get("data", {}).get("issues", [])
    if issues and state.get("turn_count", 0) < TURN_CEILING:
        return "planner"
    return "END"


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("supervisor", supervisor_node)

    workflow.set_entry_point("planner")

    workflow.add_edge("planner", "supervisor")
    workflow.add_edge("reviewer", "supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        router_logic,
        {
            "planner": "planner",
            "reviewer": "reviewer",
            "END": END,
        },
    )

    return workflow.compile()


import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="Your Blog Title Here")
    ap.add_argument("--content", default="Your blog post content goes here.")
    ap.add_argument("--email", default="student@example.com")
    ap.add_argument("--llm", default="qwen3:1.7b")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    graph = build_graph()

    initial_state: AgentState = {
        "title": args.title,
        "content": args.content,
        "email": args.email,
        "strict": args.strict,
        "task": "",
        "llm": args.llm,
        "planner_proposal": None,
        "reviewer_feedback": None,
        "turn_count": 0,
    }

    print(f"\n=== Running graph for: {args.title!r} ===")

    state = dict(initial_state)
    for step in graph.stream(initial_state):
        for node_name, update in step.items():
            print(f"\n--- Node: {node_name} ---")
            print(json.dumps(update, indent=2))
            state.update(update)

    print("\n=== Final State (Publish Package) ===")
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
