from __future__ import annotations

from typing import List
from pydantic import BaseModel, field_validator


class PlannerOutputSchema(BaseModel):
    tags: List[str]
    summary: str

    @field_validator("tags")
    @classmethod
    def check_tags(cls, tags: List[str]) -> List[str]:
        if len(tags) != 3:
            raise ValueError(f"must have exactly 3 tags, got {len(tags)}")
        for t in tags:
            if not (3 <= len(t) <= 30):
                raise ValueError(f"tag {t!r} must be 3-30 characters long, got {len(t)}")
        return tags

    @field_validator("summary")
    @classmethod
    def check_summary(cls, summary: str) -> str:
        word_count = len(summary.split())
        if word_count > 25:
            raise ValueError(f"summary must be at most 25 words, got {word_count}")
        return summary


def validate_output(data: dict):
    """
    Returns None if data passes the schema.
    Returns a plain-English error string if it doesn't.
    """
    try:
        PlannerOutputSchema(**data)
        return None
    except Exception as e:
        return str(e)


from typing import TypedDict, Optional, Dict, Any, Literal

from langgraph.graph import StateGraph, END

from agents_demo import parse_and_coerce
from src.model_client import complete
from graph_agent import PLANNER_SYSTEM, _build_task, supervisor_node


class AgentStateV2(TypedDict):
    title: str
    content: str
    email: str
    strict: bool
    task: str
    llm: str

    planner_proposal: Optional[dict]
    validation_error: Optional[str]
    turn_count: int
    turn_ceiling: int


def planner_node_v2(state: AgentStateV2) -> Dict[str, Any]:
    print("[Planner] Node activated (schema mode)")

    title = state["title"]
    content = state["content"]
    email = state["email"]
    strict = state["strict"]

    task = _build_task(title, content, email)

    validation_error = state.get("validation_error")
    if validation_error:
        history_text = (
            f"Validation error from your last attempt: {validation_error}\n"
            "Please fix this and try again."
        )
    else:
        history_text = "(empty)"

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

    return {"planner_proposal": proposal, "validation_error": None}


def validator_node(state: AgentStateV2) -> Dict[str, Any]:
    print("[Validator] Node activated")
    data = state.get("planner_proposal", {}).get("data", {})
    err = validate_output({"tags": data.get("tags", []), "summary": data.get("summary", "")})
    return {"validation_error": err}


def router_logic_v2(state: AgentStateV2) -> Literal["planner", "END"]:
    if not state.get("planner_proposal"):
        return "planner"
    if state.get("validation_error") and state.get("turn_count", 0) < state.get("turn_ceiling", 2):
        return "planner"
    return "END"


def build_graph_v2():
    workflow = StateGraph(AgentStateV2)

    workflow.add_node("planner", planner_node_v2)
    workflow.add_node("validator", validator_node)
    workflow.add_node("supervisor", supervisor_node)

    workflow.set_entry_point("planner")

    workflow.add_edge("planner", "validator")
    workflow.add_edge("validator", "supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        router_logic_v2,
        {
            "planner": "planner",
            "END": END,
        },
    )

    return workflow.compile()
