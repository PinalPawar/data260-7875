"""HW8 Part 2: the model call each agent makes, through the existing src/model_client.py.

qwen3:1.7b via Ollama, temperature 0, seed SEED, thinking off. With HW8_FAKE_LLM=1 a fixed
offline stand-in answers instead; the Part 3 failure harness and the offline tests use it,
because those tests are about Kafka behaviour, not about model wording.
"""

import os
import re

from .config import AGENT_MODEL, SEED

FAKE = os.getenv("HW8_FAKE_LLM", "0") == "1"


def chat(system: str, user: str, max_tokens: int = 400) -> str:
    if FAKE:
        return _fake(system, user)
    from src.model_client import complete

    out = complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=AGENT_MODEL,
        temperature=0.0,
        seed=SEED,
        think=False,
        max_tokens=max_tokens,
        timeout=180,
    )
    return strip_think(out["content"])


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def model_label() -> str:
    return "offline stand-in (HW8_FAKE_LLM=1)" if FAKE else f"{AGENT_MODEL} via Ollama"


def _fake(system: str, user: str) -> str:
    role = system.split(".", 1)[0]
    if "Planner" in role:
        return ("Identify the product and the reason for the recall\n"
                "Say who is at risk and what symptoms to watch for\n"
                "Give the concrete steps a shopper should take")
    if "Writer" in role:
        return ("Check the recall notice for the product name and lot number. If yours matches, "
                "do not eat it: throw it away or return it to the store for a refund, and clean "
                "any surface it touched. Watch for symptoms such as fever or diarrhea and call a "
                "doctor if they appear.")
    return "APPROVE: answers the question, follows the plan and gives safe, concrete steps."
