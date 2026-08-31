
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


def complete(messages, tools=None, model=None, base_url=None, temperature=0.0):
   
    client = ollama.Client(host=base_url or DEFAULT_BASE_URL)
    response = client.chat(
        model=model or DEFAULT_MODEL,
        messages=messages,
        options={"temperature": temperature},
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
    }