"""HW6 Part 2 - short-term, long-term and episodic memory for /api/chat.

Three kinds of memory, all stored in the s7875_doc database:

  short-term  -> `messages`: sliding window of the last SHORT_TERM_N messages
                 of the current session.
  long-term   -> `summaries`: every SUMMARIZE_EVERY_USER_MSGS user messages
                 the recent conversation is summarized into bullets
                 (scope='session'); every LIFETIME_EVERY_SESSION_SUMMARIES
                 session summaries are condensed into one lifetime summary
                 (scope='user', session_id=None).
  episodic    -> `episodes`: up to 3 short facts extracted from each user
                 message, each with an importance score (0..1) and an
                 embedding; retrieved by cosine similarity to the new message.

The model is always called through the HW1 adapter, src/model_client.complete().
"""
import json
import math
import re
import threading
import time
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING

from src.model_client import complete

from .config import (CHAT_MODEL, COMPRESS_MAX_WORDS, EMBED_MODEL_NAME,
                     EPISODE_DUPLICATE_SIMILARITY, EPISODIC_TOP_K,
                     LIFETIME_EVERY_SESSION_SUMMARIES, MAX_FACTS_PER_MESSAGE, NUM_CTX,
                     SEED, SHORT_TERM_N, SUMMARIZE_EVERY_USER_MSGS, TOKENIZER_NAME)
from .db import get_episodes_collection, get_messages_collection, get_summaries_collection

SYSTEM_PRIMER = (
    "You are RecallHelper, an assistant for a grocery supply and recall-notice "
    "service. You help shoppers and store staff understand food recalls, "
    "contamination risks (Listeria, Salmonella, E. coli), foreign material, "
    "mislabelled allergens and supply shortages. Answer in 2-4 short sentences. "
    "You do NOT have access to a live recall database: never claim that a "
    "specific recall exists unless the user told you about it; instead suggest "
    "checking FDA.gov/recalls or the store. Use the memory sections below when "
    "they are relevant, and say honestly if you do not know something. /no_think"
)


def now():
    return datetime.now(timezone.utc)


def strip_think(text: str) -> str:
    """qwen3 models may wrap reasoning in <think>...</think>; drop it."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return text.replace("<think>", "").replace("</think>", "").strip()


MODEL_TIMEOUT_S = 180  # one model call may not take longer than this


# ---------------------------------------------------------------------------
# Token counting (HW6 Part 3)
# ---------------------------------------------------------------------------
_tokenizer = None
_tokenizer_failed = False


def get_tokenizer():
    """The chat model's own tokenizer (downloaded once, a few MB). If it cannot
    be loaded, token counts fall back to an estimate of 1 token per 4 chars."""
    global _tokenizer, _tokenizer_failed
    if _tokenizer is None and not _tokenizer_failed:
        try:
            from transformers import AutoTokenizer
            _tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
        except Exception as exc:
            print(f"[HW6] tokenizer unavailable, estimating tokens: {exc}")
            _tokenizer_failed = True
    return _tokenizer


def count_tokens(text: str) -> int:
    if not text:
        return 0
    tok = get_tokenizer()
    if tok is None:
        return max(1, round(len(text) / 4))
    return len(tok.encode(text, add_special_tokens=False))


def count_prompt_tokens(messages) -> int:
    """Full prompt length, chat template included. This is what a hosted API
    would bill as input, independent of Ollama's prompt cache."""
    tok = get_tokenizer()
    if tok is None:
        return sum(count_tokens(m["content"]) + 4 for m in messages)
    try:
        ids = tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                      enable_thinking=False)
    except TypeError:
        ids = tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    if hasattr(ids, "keys"):          # newer transformers return a dict
        ids = ids["input_ids"]
    if ids and isinstance(ids[0], list):
        ids = ids[0]
    return len(ids)


# Every model call made while handling one request is recorded here, so the
# request can report the cost of memory upkeep (fact extraction, summaries).
_calls = threading.local()


def start_call_log():
    _calls.items = []


def get_call_log():
    return list(getattr(_calls, "items", []))


def call_model(messages, temperature=0.0, max_tokens=300, purpose="reply"):
    """One model call through the HW1 adapter. Returns (text, usage).
    max_tokens caps the reply length so a call can never run forever."""
    t0 = time.perf_counter()
    # think=False: qwen3 otherwise spends the token budget on hidden reasoning
    # and can return an empty answer.
    out = complete(messages, model=CHAT_MODEL, temperature=temperature,
                   max_tokens=max_tokens, timeout=MODEL_TIMEOUT_S, think=False,
                   seed=SEED, num_ctx=NUM_CTX)
    usage = {
        "prompt_tokens": out["input_tokens"],               # as reported by Ollama
        "prompt_tokens_full": count_prompt_tokens(messages),  # full prompt, tokenizer
        "completion_tokens": out["output_tokens"],
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    if hasattr(_calls, "items"):
        _calls.items.append({"purpose": purpose, **usage})
    return strip_think(out["content"]), usage


# ---------------------------------------------------------------------------
# Embeddings + cosine similarity
# ---------------------------------------------------------------------------
_embedder = None


def get_embedder():
    """Loaded once, on first use (the first call downloads ~90MB)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
    return _embedder


def embed(texts):
    vectors = get_embedder().encode(list(texts), normalize_embeddings=True)
    return [[float(x) for x in v] for v in vectors]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Short-term memory (messages)
# ---------------------------------------------------------------------------
def save_message(user_id, session_id, role, content):
    doc = {"user_id": user_id, "session_id": session_id, "role": role,
           "content": content, "created_at": now()}
    doc["_id"] = get_messages_collection().insert_one(doc).inserted_id
    return doc


def load_short_term(user_id, session_id, n=SHORT_TERM_N, before_id=None):
    """Last n messages of this session, oldest first. `before_id` excludes the
    message just saved, because the current message is added to the prompt
    separately."""
    query = {"user_id": user_id, "session_id": session_id}
    if before_id is not None:
        query["_id"] = {"$ne": before_id}
    docs = list(get_messages_collection().find(query)
                .sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(n))
    return list(reversed(docs))


# ---------------------------------------------------------------------------
# Long-term memory (summaries)
# ---------------------------------------------------------------------------
def latest_session_summary(user_id, session_id):
    return get_summaries_collection().find_one(
        {"user_id": user_id, "session_id": session_id, "scope": "session"},
        sort=[("created_at", DESCENDING)])


def latest_lifetime_summary(user_id):
    return get_summaries_collection().find_one(
        {"user_id": user_id, "scope": "user", "session_id": None},
        sort=[("created_at", DESCENDING)])


def _transcript(messages):
    return "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)


def summarize_session(user_id, session_id):
    """Summarize the recent conversation (plus the previous session summary,
    so nothing older is lost) into concise bullets, scope='session'."""
    previous = latest_session_summary(user_id, session_id)
    recent = load_short_term(user_id, session_id, n=2 * SUMMARIZE_EVERY_USER_MSGS)
    prompt = (
        "Summarize this conversation between a user and a grocery-recall "
        "assistant into 3-6 concise bullet points. Each line must start with "
        "'- '. Keep facts about the user (name, location, family, allergies, "
        "products they bought, stores) and any recalls discussed. No preamble.\n\n"
        + (f"Earlier summary:\n{previous['text']}\n\n" if previous else "")
        + f"Recent messages:\n{_transcript(recent)}"
    )
    text, usage = call_model([{"role": "user", "content": prompt + " /no_think"}],
                             purpose="session_summary")
    if not text:
        raise RuntimeError("model returned an empty session summary; not stored")
    doc = {"user_id": user_id, "session_id": session_id, "scope": "session",
           "text": text, "created_at": now()}
    get_summaries_collection().insert_one(doc)
    return doc, usage


def condense_lifetime_summary(user_id):
    """Condense the latest summary of each recent session (plus the previous
    lifetime summary) into one lifetime summary: scope='user', session_id=None."""
    col = get_summaries_collection()
    pipeline = [
        {"$match": {"user_id": user_id, "scope": "session"}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$session_id", "text": {"$first": "$text"},
                    "created_at": {"$first": "$created_at"}}},
        {"$sort": {"created_at": -1}},
        {"$limit": 6},
    ]
    sessions = [x for x in col.aggregate(pipeline) if x.get("text")]
    if not sessions:
        raise RuntimeError("no session summaries to condense")
    previous = latest_lifetime_summary(user_id)
    prompt = (
        "Condense these notes about one user into a single lifetime profile of "
        "4-8 bullet points ('- ' each). Merge duplicates. If two notes "
        "conflict, keep the most recent one. No preamble.\n\n"
        + (f"Previous lifetime profile:\n{previous['text']}\n\n" if previous else "")
        + "\n\n".join(f"Session notes:\n{s['text']}" for s in reversed(sessions))
    )
    text, usage = call_model([{"role": "user", "content": prompt + " /no_think"}],
                             max_tokens=400, purpose="lifetime_summary")
    if not text:
        raise RuntimeError("model returned an empty lifetime summary; not stored")
    doc = {"user_id": user_id, "session_id": None, "scope": "user",
           "text": text, "created_at": now()}
    col.insert_one(doc)
    return doc, usage


def maybe_summarize(user_id, session_id):
    """Summarization trigger, run after each turn.
    - every SUMMARIZE_EVERY_USER_MSGS user messages in the session -> session summary
    - every LIFETIME_EVERY_SESSION_SUMMARIES session summaries of the user -> lifetime summary"""
    result = {"session_summary_updated": False, "lifetime_summary_updated": False}
    user_msgs = get_messages_collection().count_documents(
        {"user_id": user_id, "session_id": session_id, "role": "user"})
    if user_msgs == 0 or user_msgs % SUMMARIZE_EVERY_USER_MSGS != 0:
        return result
    summarize_session(user_id, session_id)
    result["session_summary_updated"] = True
    n_session_summaries = get_summaries_collection().count_documents(
        {"user_id": user_id, "scope": "session"})
    if n_session_summaries % LIFETIME_EVERY_SESSION_SUMMARIES == 0:
        condense_lifetime_summary(user_id)
        result["lifetime_summary_updated"] = True
    return result


# ---------------------------------------------------------------------------
# Episodic memory (episodes)
# ---------------------------------------------------------------------------
def _parse_facts(text):
    """Pull the JSON list out of the model's reply; tolerate extra text."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    facts = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact", "")).strip()
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        if fact:
            facts.append({"fact": fact[:200], "importance": min(max(importance, 0.0), 1.0)})
    return facts[:MAX_FACTS_PER_MESSAGE]


def extract_episodes(user_id, session_id, message):
    """Ask the model for up to 3 short, durable facts in the user's message,
    embed each one and store it. Near-duplicates of stored facts are skipped."""
    prompt = (
        "Extract up to 3 short facts worth remembering about the USER from the "
        "message below (who they are, where they live or shop, family, "
        "allergies or diet, products they bought, preferences). Ignore greetings "
        "and plain questions. Give each fact an importance from 0 to 1 "
        "(1 = safety-critical, e.g. an allergy or a recalled product at home).\n"
        'Reply with ONLY a JSON list, e.g. [{"fact": "User is allergic to peanuts", '
        '"importance": 0.9}]. Reply [] if there is nothing to remember.\n\n'
        f"Message: {message} /no_think"
    )
    text, _ = call_model([{"role": "user", "content": prompt}], max_tokens=200,
                         purpose="episode_extraction")
    facts = _parse_facts(text)
    if not facts:
        return []
    vectors = embed([f["fact"] for f in facts])
    col = get_episodes_collection()
    existing = list(col.find({"user_id": user_id}, {"embedding": 1}))
    stored = []
    for f, vec in zip(facts, vectors):
        if any(cosine(vec, e["embedding"]) >= EPISODE_DUPLICATE_SIMILARITY for e in existing):
            continue
        doc = {"user_id": user_id, "session_id": session_id, "fact": f["fact"],
               "importance": f["importance"], "embedding": vec, "created_at": now()}
        col.insert_one(doc)
        existing.append(doc)
        stored.append({"fact": f["fact"], "importance": f["importance"]})
    return stored


def retrieve_episodes(user_id, query_vector, k=EPISODIC_TOP_K):
    """Top-k episodes of this user (any session) by cosine similarity."""
    scored = []
    for e in get_episodes_collection().find({"user_id": user_id}):
        scored.append({"fact": e["fact"], "importance": e["importance"],
                       "score": round(cosine(query_vector, e["embedding"]), 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]


# ---------------------------------------------------------------------------
# Memory-saving policy (HW6 Part 3): compress the short-term window
# ---------------------------------------------------------------------------
def compress_window(window, max_words=COMPRESS_MAX_WORDS):
    """Compression policy. User turns are kept word for word (they carry the
    facts); each assistant turn is cut to its first sentence, at most
    max_words words. Assistant replies are long and repetitive, so most of the
    window's tokens are saved while every user fact stays in the window."""
    out = []
    for m in window:
        if m["role"] != "assistant":
            out.append(m)
            continue
        first = re.split(r"(?<=[.!?])\s+", m["content"].strip(), maxsplit=1)[0]
        words = first.split()
        if len(words) > max_words:
            first = " ".join(words[:max_words]) + " ..."
        out.append({**m, "content": first})
    return out


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------
def build_prompt(message, window, session_summary, lifetime_summary, facts):
    """system primer + long-term summaries + episodic facts (one system
    message), then the short-term window as real turns, then the new message.
    Also returns each part's text so Part 3 can measure its token cost."""
    parts = {"system_primer": SYSTEM_PRIMER, "long_term_summary": "", "episodic_facts": "",
             "short_term_window": _transcript(window), "current_message": message}
    system = SYSTEM_PRIMER
    long_term = []
    if lifetime_summary:
        long_term.append(f"What you know about this user overall:\n{lifetime_summary}")
    if session_summary:
        long_term.append(f"Summary of this conversation so far:\n{session_summary}")
    if long_term:
        parts["long_term_summary"] = "\n\n".join(long_term)
        system += "\n\n## Long-term memory\n" + parts["long_term_summary"]
    if facts:
        parts["episodic_facts"] = "\n".join(f"- {f['fact']}" for f in facts)
        system += "\n\n## Relevant facts from earlier conversations\n" + parts["episodic_facts"]
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in window]
    messages.append({"role": "user", "content": message})
    return messages, parts
