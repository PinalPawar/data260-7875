"""HW6 Part 3 - What memory costs.

Replays the fixed 30-message conversation (reports/hw06/memory_conversation.yaml)
against the running FastAPI server, once per setting, each in a fresh session
under its own user id, then asks the five probes (reports/hw06/memory_probes.yaml)
in the same session and scores the answers.

Settings:
  n4            SHORT_TERM_N = 4
  n12           SHORT_TERM_N = 12
  n30           SHORT_TERM_N = 30
  n12_compress  SHORT_TERM_N = 12 + compression policy (assistant turns in the
                window cut to their first sentence)

Usage (server must be running: python main.py):
  python scripts/run_memory_experiment.py              # all four settings
  python scripts/run_memory_experiment.py --only n4    # one setting
  python scripts/run_memory_experiment.py --analyze    # rebuild tables from raw files

Outputs (reports/hw06/raw/): p3_turns.csv/.json, p3_probe_scores.csv/.json,
p3_summary.json, p3_policy_comparison.json, p3_console.log
and the filled-in tables in reports/hw06/METRICS.md.
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HW = os.path.join(ROOT, "reports", "hw06")
RAW = os.path.join(HW, "raw")
BASE = "http://localhost:8675"

SETTINGS = [
    {"label": "n4", "short_term_n": 4, "policy": "none", "name": "SHORT_TERM_N=4"},
    {"label": "n12", "short_term_n": 12, "policy": "none", "name": "SHORT_TERM_N=12"},
    {"label": "n30", "short_term_n": 30, "policy": "none", "name": "SHORT_TERM_N=30"},
    {"label": "n12_compress", "short_term_n": 12, "policy": "compress",
     "name": "Compression policy (N=12, assistant turns compressed)"},
]

PRICE_IN = 1.0 / 1_000_000    # $ per input token
PRICE_OUT = 5.0 / 1_000_000   # $ per output token
N_CONVERSATIONS = 10_000

_log_file = None


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def post_chat(user_id, session_id, message, n, policy):
    body = {"user_id": user_id, "message": message}
    if session_id:
        body["session_id"] = session_id
    url = f"{BASE}/api/chat?short_term_n={n}&policy={policy}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            log(f"   HTTP {exc.code} on attempt {attempt}: {detail[:200]}")
            if attempt == 2:
                raise
            time.sleep(3)


def reset_user(user_id):
    """Fresh start for a setting: remove this user's earlier memory."""
    from mongo_doc.db import (get_episodes_collection, get_messages_collection,
                              get_summaries_collection)
    for col in (get_messages_collection(), get_summaries_collection(), get_episodes_collection()):
        col.delete_many({"user_id": user_id})


def score_answer(answer, probe):
    text = answer.lower()
    found = [any(s.lower() in text for s in group) for group in probe["expected"]]
    flags = [w for w in probe.get("wrong_if_present", []) if w.lower() in text]
    score = 1 + round(4 * sum(found) / len(found))
    return score, sum(found), len(found), flags


def turn_row(setting, turn, kind, probe_id, message, resp):
    u, p = resp["usage"], resp["prompt_parts_tokens"]
    upkeep = u.get("upkeep_calls", [])
    return {
        "setting": setting["label"], "short_term_n": setting["short_term_n"],
        "policy": setting["policy"], "turn": turn, "kind": kind, "probe_id": probe_id,
        "message": message, "reply": resp["reply"],
        "window_count": resp["memory_used"]["short_term"]["count"],
        "prompt_tokens": u["prompt_tokens_full"],
        "prompt_tokens_ollama": u["prompt_tokens"],
        "completion_tokens": u["completion_tokens"],
        "tokens_system_primer": p["system_primer"],
        "tokens_long_term_summary": p["long_term_summary"],
        "tokens_short_term_window": p["short_term_window"],
        "tokens_episodic_facts": p["episodic_facts"],
        "tokens_current_message": p["current_message"],
        "reply_latency_ms": u["latency_ms"],
        "request_latency_ms": u["total_request_ms"],
        "upkeep_calls": len(upkeep),
        "upkeep_prompt_tokens": sum(c["prompt_tokens_full"] for c in upkeep),
        "upkeep_completion_tokens": sum(c["completion_tokens"] for c in upkeep),
        "session_summary_updated": resp["memory_written"]["session_summary_updated"],
        "lifetime_summary_updated": resp["memory_written"]["lifetime_summary_updated"],
        "memory_errors": "; ".join(resp["memory_written"].get("errors", [])),
    }


def run_setting(setting, conversation, probes):
    user_id = f"p3_{setting['label']}"
    reset_user(user_id)
    log(f"=== {setting['name']}  (user_id={user_id}, short_term_n={setting['short_term_n']}, "
        f"policy={setting['policy']}) ===")
    rows, scores, session_id = [], [], None
    t_start = time.perf_counter()
    for i, msg in enumerate(conversation, 1):
        resp = post_chat(user_id, session_id, msg, setting["short_term_n"], setting["policy"])
        session_id = resp["session_id"]
        row = turn_row(setting, i, "conversation", "", msg, resp)
        rows.append(row)
        log(f"   turn {i:2d}  window={row['window_count']:2d}  prompt={row['prompt_tokens']:5d}  "
            f"completion={row['completion_tokens']:3d}  reply={row['reply_latency_ms']:7.0f} ms  "
            f"request={row['request_latency_ms']:7.0f} ms"
            + ("  [session summary]" if row["session_summary_updated"] else "")
            + ("  [lifetime summary]" if row["lifetime_summary_updated"] else ""))
    for j, probe in enumerate(probes, 1):
        resp = post_chat(user_id, session_id, probe["question"],
                         setting["short_term_n"], setting["policy"])
        row = turn_row(setting, len(conversation) + j, "probe", probe["id"], probe["question"], resp)
        rows.append(row)
        score, found, total, flags = score_answer(resp["reply"], probe)
        scores.append({"setting": setting["label"], "probe_id": probe["id"],
                       "question": probe["question"], "answer": resp["reply"],
                       "key_facts_found": found, "key_facts_total": total,
                       "score": score, "flags": flags})
        log(f"   probe {probe['id']}  score={score}/5 ({found}/{total} facts)"
            + (f"  FLAG: {flags}" if flags else "") + f"  -> {resp['reply'][:110]!r}")
    log(f"=== {setting['label']} done in {time.perf_counter() - t_start:.0f} s ===")
    return rows, scores


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def apply_manual_review(scores):
    """If raw/p3_probe_manual_review.json exists, attach the manual score to
    each probe answer. The automatic keyword score cannot see wrong
    attributions or invented details, so the manual score is the one reported."""
    path = os.path.join(RAW, "p3_probe_manual_review.json")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        reviews = {(r["setting"], r["probe_id"]): r for r in json.load(f)["reviews"]}
    for x in scores:
        r = reviews.get((x["setting"], x["probe_id"]))
        if r:
            x["score_manual"], x["manual_reason"] = r["manual"], r["reason"]
    return True


def analyze(rows, scores):
    summary = []
    for s in SETTINGS:
        conv = [r for r in rows if r["setting"] == s["label"] and r["kind"] == "conversation"]
        auto = [x["score"] for x in scores if x["setting"] == s["label"]]
        sc = [x.get("score_manual", x["score"]) for x in scores if x["setting"] == s["label"]]
        if not conv:
            continue
        mean = lambda k: round(statistics.mean(r[k] for r in conv), 1)
        in_reply = sum(r["prompt_tokens"] for r in conv)
        out_reply = sum(r["completion_tokens"] for r in conv)
        in_all = in_reply + sum(r["upkeep_prompt_tokens"] for r in conv)
        out_all = out_reply + sum(r["upkeep_completion_tokens"] for r in conv)
        cost = lambda i, o: round(N_CONVERSATIONS * (i * PRICE_IN + o * PRICE_OUT), 2)
        summary.append({
            "setting": s["label"], "name": s["name"], "short_term_n": s["short_term_n"],
            "policy": s["policy"], "turns": len(conv),
            "mean_prompt_tokens": mean("prompt_tokens"),
            "mean_completion_tokens": mean("completion_tokens"),
            "mean_tokens_system_primer": mean("tokens_system_primer"),
            "mean_tokens_long_term_summary": mean("tokens_long_term_summary"),
            "mean_tokens_short_term_window": mean("tokens_short_term_window"),
            "mean_tokens_episodic_facts": mean("tokens_episodic_facts"),
            "mean_reply_latency_ms": mean("reply_latency_ms"),
            "mean_request_latency_ms": mean("request_latency_ms"),
            "mean_probe_score": round(statistics.mean(sc), 2) if sc else None,
            "mean_probe_score_auto": round(statistics.mean(auto), 2) if auto else None,
            "probe_scores": sc,
            "probe_scores_auto": auto,
            "conversation_input_tokens_reply": in_reply,
            "conversation_output_tokens_reply": out_reply,
            "conversation_input_tokens_with_upkeep": in_all,
            "conversation_output_tokens_with_upkeep": out_all,
            "cost_10k_reply_only_usd": cost(in_reply, out_reply),
            "cost_10k_with_upkeep_usd": cost(in_all, out_all),
        })
    # best / worst: worst = most expensive; best = cheapest among settings
    # whose probe quality is within 0.5 of the best quality reached
    best = worst = None
    if summary:
        worst = max(summary, key=lambda x: x["cost_10k_with_upkeep_usd"])
        top = max(x["mean_probe_score"] for x in summary)
        ok = [x for x in summary if x["mean_probe_score"] >= top - 0.5]
        best = min(ok, key=lambda x: x["cost_10k_with_upkeep_usd"])
    policy = None
    base = next((x for x in summary if x["setting"] == "n12"), None)
    comp = next((x for x in summary if x["setting"] == "n12_compress"), None)
    if base and comp:
        policy = {
            "baseline": "n12", "policy": "n12_compress",
            "mean_prompt_tokens_baseline": base["mean_prompt_tokens"],
            "mean_prompt_tokens_policy": comp["mean_prompt_tokens"],
            "prompt_tokens_saved_per_turn": round(base["mean_prompt_tokens"] - comp["mean_prompt_tokens"], 1),
            "prompt_tokens_saved_pct": round(100 * (1 - comp["mean_prompt_tokens"] / base["mean_prompt_tokens"]), 1),
            "window_tokens_baseline": base["mean_tokens_short_term_window"],
            "window_tokens_policy": comp["mean_tokens_short_term_window"],
            "probe_score_baseline": base["mean_probe_score"],
            "probe_score_policy": comp["mean_probe_score"],
            "probe_score_change": round(comp["mean_probe_score"] - base["mean_probe_score"], 2),
            "probe_score_auto_baseline": base["mean_probe_score_auto"],
            "probe_score_auto_policy": comp["mean_probe_score_auto"],
            "mean_request_latency_baseline_ms": base["mean_request_latency_ms"],
            "mean_request_latency_policy_ms": comp["mean_request_latency_ms"],
        }
    return summary, best, worst, policy


def write_metrics(summary, best, worst, policy, scores):
    L = ["# HW6 Metrics - Pinal Pawar (SID4 7875)", "",
         f"Generated by `scripts/run_memory_experiment.py` on {datetime.now():%Y-%m-%d %H:%M}.",
         "Model: qwen3:1.7b (Ollama, local), temperature 0, seed 7875. Token counts use the",
         "Qwen3 tokenizer on the full prompt (chat template included). Means are over the 30",
         "conversation turns; probe quality is the mean of the 5 probes asked afterwards.", "",
         "## Part 3.3 / 3.4 - Short-term memory sizes and the compression policy", "",
         "| Setting | Mean prompt tokens/turn | Mean latency (ms) | Probe quality (1-5) |",
         "|---|---|---|---|"]
    for x in summary:
        L.append(f"| {x['name']} | {x['mean_prompt_tokens']} | {x['mean_request_latency_ms']} | {x['mean_probe_score']} |")
    L += ["", "Mean latency is the full /api/chat request (reply + fact extraction + summaries when",
          "triggered). Reply-only latency and the token split per prompt part:", "",
          "| Setting | Reply latency (ms) | Primer | Long-term summary | Short-term window | Episodic facts | Completion tokens |",
          "|---|---|---|---|---|---|---|"]
    for x in summary:
        L.append(f"| {x['setting']} | {x['mean_reply_latency_ms']} | {x['mean_tokens_system_primer']} | "
                 f"{x['mean_tokens_long_term_summary']} | {x['mean_tokens_short_term_window']} | "
                 f"{x['mean_tokens_episodic_facts']} | {x['mean_completion_tokens']} |")
    L += ["", "### Probe scores (manual / automatic)", "",
          "Probe quality above is the manual score. The automatic score only checks that the key",
          "words appear; the manual check (raw/p3_probe_manual_review.json) also deducts for facts",
          "given to the wrong person and for invented details.", "",
          "| Setting | P1 | P2 | P3 | P4 | P5 | Mean manual | Mean automatic |", "|---|---|---|---|---|---|---|---|"]
    for x in summary:
        L.append(f"| {x['setting']} | " + " | ".join(f"{m} / {a}" for m, a in zip(x["probe_scores"], x["probe_scores_auto"]))
                 + f" | {x['mean_probe_score']} | {x['mean_probe_score_auto']} |")
    flagged = [s for s in scores if s["flags"]]
    if flagged:
        L += ["", "Answers flagged for a distractor fact: " +
              ", ".join(f"{s['setting']} {s['probe_id']} ({', '.join(s['flags'])})" for s in flagged)]
    if policy:
        L += ["", "## Part 3.4 - Compression policy vs the same window without it", "",
              "| Metric | N=12 baseline | N=12 + compression | Change |", "|---|---|---|---|",
              f"| Mean prompt tokens/turn | {policy['mean_prompt_tokens_baseline']} | {policy['mean_prompt_tokens_policy']} | "
              f"-{policy['prompt_tokens_saved_per_turn']} ({policy['prompt_tokens_saved_pct']}%) |",
              f"| Short-term window tokens/turn | {policy['window_tokens_baseline']} | {policy['window_tokens_policy']} | "
              f"{round(policy['window_tokens_policy'] - policy['window_tokens_baseline'], 1)} |",
              f"| Probe quality, manual (1-5) | {policy['probe_score_baseline']} | {policy['probe_score_policy']} | {policy['probe_score_change']:+} |",
              f"| Probe quality, automatic (1-5) | {policy['probe_score_auto_baseline']} | {policy['probe_score_auto_policy']} | "
              f"{round(policy['probe_score_auto_policy'] - policy['probe_score_auto_baseline'], 2):+} |",
              f"| Mean request latency (ms) | {policy['mean_request_latency_baseline_ms']} | {policy['mean_request_latency_policy_ms']} | "
              f"{round(policy['mean_request_latency_policy_ms'] - policy['mean_request_latency_baseline_ms'], 1)} |"]
    L += ["", "## Part 3.5 - Estimated cost of 10,000 thirty-turn conversations", "",
          "Pricing: $1 per million input tokens, $5 per million output tokens.", "",
          "| Setting | Input tokens / conv. (incl. upkeep) | Output tokens / conv. (incl. upkeep) | Cost, replies only | Cost incl. memory upkeep |",
          "|---|---|---|---|---|"]
    for x in summary:
        L.append(f"| {x['setting']} | {x['conversation_input_tokens_with_upkeep']:,} | {x['conversation_output_tokens_with_upkeep']:,} | "
                 f"${x['cost_10k_reply_only_usd']:,.2f} | ${x['cost_10k_with_upkeep_usd']:,.2f} |")
    if best and worst:
        L += ["", f"**Best setting: {best['setting']}** (${best['cost_10k_with_upkeep_usd']:,.2f}, quality {best['mean_probe_score']}). "
              f"**Worst setting: {worst['setting']}** (${worst['cost_10k_with_upkeep_usd']:,.2f}, quality {worst['mean_probe_score']}).", "",
              "Selection rule: the worst setting is the most expensive one. The best setting is the cheapest",
              "setting whose probe quality is within 0.5 of the highest quality reached, so a cheaper setting",
              "is not chosen if it forgets noticeably more. Input tokens include the memory-upkeep calls",
              "(fact extraction and summaries), which a hosted API would also bill."]
    with open(os.path.join(HW, "METRICS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def save_all(rows, scores):
    write_csv(os.path.join(RAW, "p3_turns.csv"), rows)
    with open(os.path.join(RAW, "p3_turns.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    write_csv(os.path.join(RAW, "p3_probe_scores.csv"),
              [{**s, "flags": ";".join(s["flags"])} for s in scores])
    with open(os.path.join(RAW, "p3_probe_scores.json"), "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=1, ensure_ascii=False)
    apply_manual_review(scores)
    summary, best, worst, policy = analyze(rows, scores)
    with open(os.path.join(RAW, "p3_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"settings": summary, "best": best and best["setting"],
                   "worst": worst and worst["setting"]}, f, indent=1)
    if policy:
        with open(os.path.join(RAW, "p3_policy_comparison.json"), "w", encoding="utf-8") as f:
            json.dump(policy, f, indent=1)
    write_metrics(summary, best, worst, policy, scores)
    return summary


def main():
    global _log_file, BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=[s["label"] for s in SETTINGS])
    ap.add_argument("--analyze", action="store_true", help="only rebuild tables from raw files")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base
    os.makedirs(RAW, exist_ok=True)

    rows = load_json(os.path.join(RAW, "p3_turns.json"), [])
    scores = load_json(os.path.join(RAW, "p3_probe_scores.json"), [])
    if args.analyze:
        for x in save_all(rows, scores):
            print(x["setting"], x["mean_prompt_tokens"], x["mean_request_latency_ms"], x["mean_probe_score"])
        return

    _log_file = open(os.path.join(RAW, "p3_console.log"), "a", encoding="utf-8")
    with open(os.path.join(HW, "memory_conversation.yaml"), encoding="utf-8") as f:
        conversation = yaml.safe_load(f)["messages"]
    with open(os.path.join(HW, "memory_probes.yaml"), encoding="utf-8") as f:
        probes = yaml.safe_load(f)["probes"]
    log(f"HW6 Part 3 start: {len(conversation)} messages, {len(probes)} probes, server {BASE}")
    try:
        urllib.request.urlopen(f"{BASE}/openapi.json", timeout=10)
    except Exception as exc:
        log(f"Server not reachable at {BASE} ({exc}). Start it with: python main.py")
        sys.exit(1)

    todo = [s for s in SETTINGS if not args.only or s["label"] == args.only]
    for s in todo:
        new_rows, new_scores = run_setting(s, conversation, probes)
        rows = [r for r in rows if r["setting"] != s["label"]] + new_rows
        scores = [x for x in scores if x["setting"] != s["label"]] + new_scores
        save_all(rows, scores)   # save after every setting, so nothing is lost
    summary = save_all(rows, scores)
    log("Results:")
    for x in summary:
        log(f"   {x['name']:<55} prompt/turn={x['mean_prompt_tokens']:7.1f}  "
            f"latency={x['mean_request_latency_ms']:8.1f} ms  quality={x['mean_probe_score']}")
    log("Done. Tables written to reports/hw06/METRICS.md")


if __name__ == "__main__":
    main()
