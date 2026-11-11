"""HW10 Part 2: evaluate one request of the HW8 Planner -> Writer -> Reviewer Kafka pipeline.

Join key: correlation_id (== trace_id). The evaluator reads, by that key,
    plan   from s7875_tasks   (Planner output)
    draft  from s7875_drafts  (Writer output)
    final  from s7875_final   (Reviewer output)
keeps the original messages + their topic/partition/offset, and scores four criteria with
GEval on the local judge (hw10/judge.py):

    plan_quality          Planner plan                    score + reason
    writer_helpfulness    Writer draft                    score + trace_id
    final_helpfulness     Reviewer final answer           score + final answer
    improvement           final_helpfulness(final) - final_helpfulness(draft), same metric

Bounded (2.1): each topic read has a timeout, malformed / missing messages give status
"incomplete" with the reason (no judge call), and each metric has a hard judge timeout.

    python hw10/evaluator.py --trace-id <id>       # evaluate an earlier request
"""

import argparse
import asyncio
import json
import time

import hw10cfg as cfg
from kafka_hw8.config import BOOTSTRAP, DRAFTS_TOPIC, FINAL_TOPIC, TASKS_TOPIC
from kafka_hw8.tracing import now_ms, write_span

TOPICS = {"plan": TASKS_TOPIC, "draft": DRAFTS_TOPIC, "final": FINAL_TOPIC}


async def _find(topic: str, corr: str, start: dict[int, int] | None, timeout_s: float
                ) -> dict | None:
    """First message on `topic` whose correlation_id is corr (None after timeout)."""
    from kafka_hw8.kafka_util import partitions_of, read_from
    if start is None:
        start = {p: 0 for p in await partitions_of(BOOTSTRAP, topic)}

    def mine(items: list[dict]) -> list[dict]:
        return [i for i in items if isinstance(i["value"], dict)
                and i["value"].get("correlation_id") == corr]

    hits = mine(await read_from(BOOTSTRAP, topic, start, timeout_s,
                                until=lambda items: bool(mine(items))))
    return ({"topic": topic, **hits[0]} if hits else None)


def load_messages(corr: str, starts: dict | None = None, timeout_s: float = 20) -> dict:
    """{'plan': msg|None, 'draft': ..., 'final': ...} read from Kafka by correlation_id."""
    async def go() -> dict:
        out = {}
        for name, topic in TOPICS.items():
            out[name] = await _find(topic, corr, (starts or {}).get(topic), timeout_s)
        return out
    return asyncio.run(go())


def extract_inputs(msgs: dict) -> tuple[dict, list[str]]:
    """Validated evaluation inputs and a list of problems (empty list = usable)."""
    problems, v = [], {k: (m or {}).get("value") for k, m in msgs.items()}
    for k in TOPICS:
        if not isinstance(v.get(k), dict):
            problems.append(f"{k} message missing or not JSON")
    plan = (v.get("plan") or {}).get("plan")
    draft = (v.get("draft") or {}).get("draft")
    final = v.get("final") or {}
    if not (isinstance(plan, list) and plan and all(isinstance(p, str) for p in plan)):
        problems.append("plan is not a non-empty list of strings")
    if not (isinstance(draft, str) and draft.strip()):
        problems.append("draft text missing")
    if not (isinstance(final.get("answer"), str) and final.get("answer", "").strip()):
        problems.append("final answer missing")
    question = (v.get("plan") or {}).get("question") or final.get("question") or ""
    final_text = (f"{final.get('answer', '')}\n\n[Reviewer verdict: {final.get('status')} - "
                  f"{final.get('review')}]")
    return ({"question": question, "plan": plan, "draft": draft,
             "final_answer": final.get("answer"), "final_status": final.get("status"),
             "review": final.get("review"), "final_as_received": final_text}, problems)


def interpret(draft_s: float | None, final_s: float | None, same_text: bool) -> str:
    """Plain-language reading of the final-vs-draft comparison (no forced positive)."""
    if draft_s is None or final_s is None:
        return "not scored (judge unavailable)"
    d = round(final_s - draft_s, 3)
    why = ("the Reviewer only approves/rejects and passes the Writer's text through unchanged, "
           "so the answer text is identical" if same_text else "the Reviewer changed the text")
    if d > 0:
        return f"final scored {d:+} higher; {why} - the gain comes only from the verdict line"
    if d < 0:
        return f"final scored {d:+} lower; {why} - the verdict line made it look worse"
    return f"no improvement (difference 0); {why}"


def score_all(inp: dict, judge=None) -> dict:
    """Run the four criteria. Fresh metric objects per call (thread-timeout safety)."""
    from judge import build_metrics, measure
    m = build_metrics(judge)
    q, plan_txt = inp["question"], "\n".join(f"- {p}" for p in inp["plan"])
    qp = f"Question: {q}\n\nPlan:\n{plan_txt}"
    plan = measure(m["plan_quality"], q, plan_txt)
    writer = measure(m["writer_helpfulness"], qp, inp["draft"])
    final = measure(m["final_helpfulness"], q, inp["final_as_received"])
    draft_same = measure(build_metrics(judge)["final_helpfulness"], q, inp["draft"])
    same = (inp["draft"] or "").strip() == (inp["final_answer"] or "").strip()
    ds, fs = draft_same["score_1_5"], final["score_1_5"]
    return {"plan_quality": plan, "writer_helpfulness": writer, "final_helpfulness": final,
            "improvement": {"draft_score": ds, "final_score": fs,
                            "difference": None if ds is None or fs is None else round(fs - ds, 3),
                            "draft_judged": draft_same, "final_text_identical_to_draft": same,
                            "interpretation": interpret(ds, fs, same)}}


def evaluate_trace(trace_id: str, starts: dict | None = None, judge=None,
                   msgs: dict | None = None) -> dict:
    """Load by correlation_id, score, save one JSONL row, write the 'evaluation' span."""
    from judge import judge_settings
    t0 = now_ms()
    msgs = msgs if msgs is not None else load_messages(trace_id, starts)
    inp, problems = extract_inputs(msgs)
    scores = None if problems else score_all(inp, judge)
    bad = [k for k, v in (scores or {}).items() if k != "improvement" and v["status"] != "ok"]
    status = "incomplete" if problems else ("judge_error" if bad else "ok")
    row = {"trace_id": trace_id, "correlation_id": trace_id,
           "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "status": status,
           "problems": problems, "judge": judge_settings(judge), "inputs": inp,
           "messages": {k: m for k, m in msgs.items()}, "scores": scores,
           "eval_ms": round(now_ms() - t0, 1)}
    cfg.RAW.mkdir(parents=True, exist_ok=True)
    with open(cfg.EVAL_RESULTS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    err = "; ".join(problems) or (f"judge failed on {bad}" if bad else None)
    write_span(trace_id, "evaluation", t0, now_ms(), "ok" if status == "ok" else "error", err,
               "evaluator", metrics=4, status_detail=status)
    return row


def print_row(row: dict) -> None:
    """Readable console summary (for the screenshot)."""
    print(f"trace_id={row['trace_id']}  status={row['status']}  eval_ms={row['eval_ms']}")
    if row["problems"]:
        print("  problems:", row["problems"])
    for k, v in (row["scores"] or {}).items():
        if k == "improvement":
            print(f"  {k:<20} draft={v['draft_score']} final={v['final_score']} "
                  f"diff={v['difference']}  -> {v['interpretation']}")
        else:
            print(f"  {k:<20} score={v['score_1_5']}  ({v['status']}) {str(v['reason'])[:110]}")


def main() -> None:
    """CLI: evaluate an earlier trace by id."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-id", required=True)
    args = ap.parse_args()
    print(cfg.banner("Part 2 evaluator"))
    print_row(evaluate_trace(args.trace_id))


if __name__ == "__main__":
    main()
