"""HW6 Part 2 - chat endpoints with short-term, long-term and episodic memory.

  POST /api/chat                 one chat turn (memory read -> model -> memory write)
  GET  /api/memory/{user_id}     what is stored for a user
  GET  /api/aggregate/{user_id}  daily message counts + recent summaries
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from .. import memory
from ..config import AGGREGATE_TIMEZONE, CHAT_LOG_PATH, CHAT_MODEL, EPISODIC_TOP_K, SHORT_TERM_N
from ..db import get_episodes_collection, get_messages_collection, get_summaries_collection
from ..schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["HW6 chat memory"])


def _iso(dt):
    return dt.isoformat() if dt else None


def _summary_out(doc):
    if not doc:
        return None
    return {"scope": doc["scope"], "session_id": doc["session_id"],
            "text": doc["text"], "created_at": _iso(doc["created_at"])}


def _db_error(exc):
    if isinstance(exc, ServerSelectionTimeoutError):
        raise HTTPException(status_code=503, detail="MongoDB is not reachable.")
    raise HTTPException(status_code=500, detail="Database error in chat memory.")


def _log_request(record):
    """HW6 Part 3: append one JSON line per /api/chat request."""
    try:
        os.makedirs(os.path.dirname(CHAT_LOG_PATH) or ".", exist_ok=True)
        with open(CHAT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[HW6] could not write chat log: {exc}")


@router.post("/chat")
def chat(req: ChatRequest,
         short_term_n: Optional[int] = Query(None, ge=1, le=100,
             description="Experiment override for SHORT_TERM_N (Part 3)"),
         policy: Literal["none", "compress"] = Query("none",
             description="Memory-saving policy for the short-term window (Part 3)")):
    t0 = time.perf_counter()
    n = short_term_n or SHORT_TERM_N
    session_id = req.session_id or uuid.uuid4().hex[:12]
    memory.start_call_log()
    try:
        # 1. save the user message
        user_doc = memory.save_message(req.user_id, session_id, "user", req.message)
        # 2. short-term window: last N messages before this one
        window = memory.load_short_term(req.user_id, session_id, n,
                                        before_id=user_doc["_id"])
        prompt_window = memory.compress_window(window) if policy == "compress" else window
        # 3. latest session summary + lifetime summary
        session_summary = memory.latest_session_summary(req.user_id, session_id)
        lifetime_summary = memory.latest_lifetime_summary(req.user_id)
        # 4. top-k episodic facts by cosine similarity to this message
        query_vector = memory.embed([req.message])[0]
        facts = memory.retrieve_episodes(req.user_id, query_vector, EPISODIC_TOP_K)
        # 5. compose the prompt
        messages, parts = memory.build_prompt(
            req.message, prompt_window,
            session_summary["text"] if session_summary else None,
            lifetime_summary["text"] if lifetime_summary else None,
            facts)
    except PyMongoError as exc:
        _db_error(exc)

    # 6. call the local model through the HW1 adapter
    try:
        reply, usage = memory.call_model(messages)
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"Local model (Ollama) call failed: {exc}")
    if not reply:
        raise HTTPException(status_code=502, detail="The model returned an empty reply. Please try again.")

    try:
        # 7. save the assistant reply
        memory.save_message(req.user_id, session_id, "assistant", reply)
    except PyMongoError as exc:
        _db_error(exc)

    # 8 + 9 are background memory writes: if one fails (e.g. a model timeout)
    # the user still gets the reply, and the error is reported in the response.
    memory_errors = []
    try:
        # 8. extract new episodic facts from this message
        new_facts = memory.extract_episodes(req.user_id, session_id, req.message)
    except Exception as exc:
        new_facts = []
        memory_errors.append(f"episode extraction failed: {exc}")
    try:
        # 9. summarization trigger (session every M user msgs, lifetime occasionally)
        summary_events = memory.maybe_summarize(req.user_id, session_id)
    except Exception as exc:
        summary_events = {"session_summary_updated": False, "lifetime_summary_updated": False}
        memory_errors.append(f"summarization failed: {exc}")

    # token cost of this turn: the reply call, plus memory upkeep calls
    calls = memory.get_call_log()
    upkeep = [c for c in calls if c["purpose"] != "reply"]
    parts_tokens = {k: memory.count_tokens(v) for k, v in parts.items()}
    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    _log_request({
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": req.user_id, "session_id": session_id, "model": CHAT_MODEL,
        "short_term_n": n, "policy": policy, "window_count": len(window),
        "prompt_tokens_ollama": usage["prompt_tokens"],
        "prompt_tokens": usage["prompt_tokens_full"],
        "completion_tokens": usage["completion_tokens"],
        **{f"tokens_{k}": v for k, v in parts_tokens.items()},
        "reply_latency_ms": usage["latency_ms"], "request_latency_ms": total_ms,
        "upkeep_calls": len(upkeep),
        "upkeep_prompt_tokens": sum(c["prompt_tokens_full"] for c in upkeep),
        "upkeep_completion_tokens": sum(c["completion_tokens"] for c in upkeep),
        "upkeep_latency_ms": round(sum(c["latency_ms"] for c in upkeep), 1),
        "session_summary_updated": summary_events["session_summary_updated"],
        "lifetime_summary_updated": summary_events["lifetime_summary_updated"],
        "message": req.message, "reply": reply,
    })

    return {
        "reply": reply,
        "user_id": req.user_id,
        "session_id": session_id,
        "memory_used": {
            "short_term": {
                "count": len(window),
                "n_limit": n,
                "policy": policy,
                "messages": [{"role": m["role"], "content": m["content"]} for m in window],
            },
            "session_summary": session_summary["text"] if session_summary else None,
            "lifetime_summary": lifetime_summary["text"] if lifetime_summary else None,
            "episodic_facts": facts,
        },
        "memory_written": {"new_episodic_facts": new_facts, **summary_events,
                           "errors": memory_errors},
        "usage": {**usage, "total_request_ms": total_ms,
                  "upkeep_calls": upkeep},
        "prompt_parts_tokens": parts_tokens,
    }


@router.get("/memory/{user_id}")
def get_memory(user_id: str):
    try:
        msgs = list(get_messages_collection().find({"user_id": user_id})
                    .sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(16))
        session_summary = get_summaries_collection().find_one(
            {"user_id": user_id, "scope": "session"}, sort=[("created_at", DESCENDING)])
        lifetime_summary = memory.latest_lifetime_summary(user_id)
        episodes = list(get_episodes_collection().find({"user_id": user_id})
                        .sort("created_at", DESCENDING).limit(20))
    except PyMongoError as exc:
        _db_error(exc)
    if not msgs and not episodes:
        raise HTTPException(status_code=404, detail=f"No memory stored for user '{user_id}'.")
    return {
        "user_id": user_id,
        "recent_messages": [{"session_id": m["session_id"], "role": m["role"],
                             "content": m["content"], "created_at": _iso(m["created_at"])}
                            for m in reversed(msgs)],
        "latest_session_summary": _summary_out(session_summary),
        "latest_lifetime_summary": _summary_out(lifetime_summary),
        "episodic_facts": [{"fact": e["fact"], "importance": e["importance"],
                            "session_id": e["session_id"],
                            "embedding_dims": len(e["embedding"]),
                            "created_at": _iso(e["created_at"])} for e in episodes],
    }


@router.get("/aggregate/{user_id}")
def get_aggregate(user_id: str):
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at",
                                      "timezone": AGGREGATE_TIMEZONE}},
            "total": {"$sum": 1},
            "user": {"$sum": {"$cond": [{"$eq": ["$role", "user"]}, 1, 0]}},
            "assistant": {"$sum": {"$cond": [{"$eq": ["$role", "assistant"]}, 1, 0]}},
            "sessions": {"$addToSet": "$session_id"},
        }},
        {"$sort": {"_id": 1}},
    ]
    try:
        days = list(get_messages_collection().aggregate(pipeline))
        summaries = list(get_summaries_collection().find({"user_id": user_id})
                         .sort("created_at", DESCENDING).limit(5))
    except PyMongoError as exc:
        _db_error(exc)
    if not days:
        raise HTTPException(status_code=404, detail=f"No messages for user '{user_id}'.")
    return {
        "user_id": user_id,
        "timezone": AGGREGATE_TIMEZONE,
        "daily_message_counts": [{"date": d["_id"], "total": d["total"], "user": d["user"],
                                  "assistant": d["assistant"], "sessions": len(d["sessions"])}
                                 for d in days],
        "recent_summaries": [_summary_out(s) for s in summaries],
    }
