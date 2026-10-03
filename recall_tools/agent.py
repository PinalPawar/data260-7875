"""
HW5 Part 5: the agent loop.

    run_agent(user_input) -> {"answer", "stop_reason", "steps", "tool_calls", "run_id"}

A local Ollama model decides, turn by turn, whether to call one of the three
domain tools or to answer. Every tool call goes through execute_tool. The
loop stops for exactly one of three reasons:
    completed     the model answered without asking for another tool
    safety_block  execute_tool refused a call because of the safety rule
    max_steps     the turn counter reached max_steps
Every step, tool call, input, result and the final stop reason is appended
to agent_runs.jsonl.
"""
import json
import os
import uuid
from datetime import datetime

from recall_tools.execute import SAFETY_PREFIX, execute_tool

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_LOG = os.path.join("reports", "hw05", "raw", "agent_runs.jsonl")
SEED = 7875  # SID4

SYSTEM_PROMPT = (
    "You are a grocery recall assistant. Answer only from the results of the tools. "
    "Use search_notices to find notices, get_notice_detail for one notice code, and "
    "recall_stats for counts. When you have enough information, reply to the user in "
    "one or two short sentences and do not call another tool."
)

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_notices",
        "description": "Search recall notices by product or manufacturer name.",
        "parameters": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string", "description": "Product or manufacturer text, at least 2 characters"},
            "category": {"type": "string", "enum": ["supplyShortage", "bacterialContamination",
                                                     "foreignMaterial", "mislabelling"]},
            "limit": {"type": "integer", "description": "1 to 20, default 5"}}}}},
    {"type": "function", "function": {
        "name": "get_notice_detail",
        "description": "Get every field of one recall notice by its code.",
        "parameters": {"type": "object", "required": ["notice_code"], "properties": {
            "notice_code": {"type": "string", "description": "Format RCL-2026-00001"}}}}},
    {"type": "function", "function": {
        "name": "recall_stats",
        "description": "Count notices and total units affected, grouped by category or manufacturer.",
        "parameters": {"type": "object", "required": ["group_by"], "properties": {
            "group_by": {"type": "string", "enum": ["category", "manufacturer"]}}}}},
]


class OllamaModel:
    """Talks to a local Ollama server's /api/chat endpoint with tool calling."""

    def __init__(self, model=DEFAULT_MODEL, url=OLLAMA_URL, timeout_s=180):
        self.name = model
        self._url = url.rstrip("/") + "/api/chat"
        self._timeout_s = timeout_s

    def chat(self, messages, tools):
        import requests  # imported here so offline tests never need it

        payload = {"model": self.name, "messages": messages, "tools": tools, "stream": False,
                   "think": False, "options": {"temperature": 0, "seed": SEED}}
        response = requests.post(self._url, json=payload, timeout=self._timeout_s)
        response.raise_for_status()
        message = response.json().get("message", {})
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):  # some models send the arguments as a JSON string
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            calls.append({"name": function.get("name", ""), "arguments": arguments})
        return {"content": message.get("content", "") or "", "tool_calls": calls}


class MockModel:
    """
    A stand-in for the LLM, for offline tests. Give it a list of scripted
    replies; when the list runs out it repeats the last one forever (which
    is how the max_steps test makes a model that never stops calling tools).
    """

    name = "mock-model"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def chat(self, messages, tools):
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return {"content": reply.get("content", ""), "tool_calls": list(reply.get("tool_calls", []))}


def _log(path, record):
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_agent(user_input, model=None, store=None, max_steps=5, log_path=DEFAULT_LOG):
    model = model or OllamaModel()
    run_id = uuid.uuid4().hex[:8]
    base = {"run_id": run_id, "model": model.name}

    def log(event, **fields):
        _log(log_path, {**base, "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "event": event, **fields})

    log("run_start", user_input=user_input, max_steps=max_steps)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_input}]
    steps = tool_calls = 0
    answer, stop_reason = "", None

    while stop_reason is None:
        if steps >= max_steps:  # the turn counter is checked before every model turn
            stop_reason = "max_steps"
            answer = f"Stopped: reached the limit of {max_steps} steps before finishing."
            break
        steps += 1
        try:
            reply = model.chat(messages, TOOL_SCHEMAS)
        except Exception as exc:
            stop_reason = "model_error"
            answer = f"Stopped: the model could not be reached ({type(exc).__name__})."
            log("model_error", step=steps, error=str(exc))
            break
        log("model_reply", step=steps, content=reply["content"],
            requested_tools=[c["name"] for c in reply["tool_calls"]])

        if not reply["tool_calls"]:
            stop_reason, answer = "completed", reply["content"]
            break

        messages.append({"role": "assistant", "content": reply["content"],
                         "tool_calls": [{"function": c} for c in reply["tool_calls"]]})
        for call in reply["tool_calls"]:
            tool_calls += 1
            raw = execute_tool(call["name"], call["arguments"], store=store)
            result = json.loads(raw)
            log("tool_call", step=steps, tool=call["name"], input=call["arguments"], result=result)
            messages.append({"role": "tool", "tool_name": call["name"], "content": raw})
            if not result["ok"] and str(result["error"]).startswith(SAFETY_PREFIX):
                stop_reason = "safety_block"
                answer = f"Stopped: {result['error']}"
                break

    log("run_end", stop_reason=stop_reason, steps=steps, tool_calls=tool_calls, answer=answer)
    return {"run_id": run_id, "answer": answer, "stop_reason": stop_reason,
            "steps": steps, "tool_calls": tool_calls}
