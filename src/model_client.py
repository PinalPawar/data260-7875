
import os

import ollama

DEFAULT_MODEL = os.environ.get("SMOL_MODEL", "qwen3:8b")
DEFAULT_BASE_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def _get(obj, key, default=None):
    """Read `key` from obj whether obj is a plain dict or an object with
    attributes (different versions of the `ollama` package return different
    shapes for chat responses)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def complete(messages, tools=None, model=None, base_url=None, temperature=0.0,
             max_tokens=None, timeout=None, think=None, seed=None, num_ctx=None):
    # HW6: optional max_tokens (Ollama num_predict), timeout (seconds) and
    # think (False switches off qwen3's hidden reasoning). All default to None,
    # so every earlier caller behaves exactly as before.
    # Without a cap a small model can occasionally repeat itself forever.
    client = ollama.Client(host=base_url or DEFAULT_BASE_URL, timeout=timeout)
    options = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    if seed is not None:          # HW6 Part 3: reproducible runs (SEED = SID4)
        options["seed"] = seed
    if num_ctx is not None:       # HW6 Part 3: room for a 30-message window
        options["num_ctx"] = num_ctx
    extra = {"think": think} if think is not None else {}
    if tools:                     # HW7 Part 2: native tool calling
        extra["tools"] = tools
    response = client.chat(
        model=model or DEFAULT_MODEL,
        messages=messages,
        options=options,
        **extra,
    )

    message = _get(response, "message")
    content = _get(message, "content", "") or ""
    input_tokens = _get(response, "prompt_eval_count", 0) or 0
    output_tokens = _get(response, "eval_count", 0) or 0

    return {
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        # HW7 Part 2: tool calls the model asked for, as plain dicts. Empty list
        # when no tools were offered, so earlier callers are unaffected.
        "tool_calls": _normalize_tool_calls(_get(message, "tool_calls")),
    }


def _normalize_tool_calls(raw_calls) -> list:
    """Turn Ollama's tool_calls into [{"name": str, "arguments": <as sent>}].

    Arguments are passed through unchanged (normally a dict; a JSON string or
    anything else is left for the caller to report as malformed).
    """
    calls = []
    for call in raw_calls or []:
        function = _get(call, "function") or {}
        arguments = _get(function, "arguments")
        if arguments is not None and not isinstance(arguments, (dict, str, list)):
            arguments = dict(arguments)  # Mapping-like object from the ollama package
        calls.append({"name": _get(function, "name", "") or "", "arguments": arguments})
    return calls