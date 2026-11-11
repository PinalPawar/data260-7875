"""HW10 Part 3.1: freeze 20 Writer drafts from my system into hw10/eval_cases.json.

Each question goes through the SAME Planner and Writer prompts and model as the HW8 Kafka
agents (kafka_hw8/agents.py, qwen3:1.7b, temperature 0, seed 7875), called in-process
(like HW9_PIPELINE=direct) so the run does not need the agent terminals. Nothing is scored here.

    python hw10/build_eval_cases.py            # refuses to overwrite an existing file
    git add hw10/eval_cases.json && git commit ...   (then label, see label_drafts.py)
"""

import argparse
import json
import time

import yaml

import hw10cfg as cfg


def make_case(i: int, question: str) -> dict:
    """Plan + draft for one question with the HW8 agent prompts."""
    from kafka_hw8.agents import PLANNER_SYSTEM, WRITER_SYSTEM, parse_plan
    from kafka_hw8.llm import chat, model_label
    t0 = time.perf_counter()
    plan = parse_plan(chat(PLANNER_SYSTEM, question)) or ["Answer the question"]
    prompt = (f"Question: {question}\n\nPlan:\n" + "\n".join(f"- {p}" for p in plan)
              + "\n\nWrite the answer now.")
    draft = chat(WRITER_SYSTEM, prompt).strip()
    return {"case_id": f"c{i:02d}", "question": question, "plan": plan, "draft": draft,
            "writer_model": model_label(), "seconds": round(time.perf_counter() - t0, 1)}


def main() -> None:
    """Generate and save the 20 cases."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite (only before committing!)")
    args = ap.parse_args()
    print(cfg.banner("Part 3.1 build eval_cases.json"))
    if cfg.EVAL_CASES.exists() and not args.force:
        raise SystemExit(f"{cfg.EVAL_CASES.name} exists - it is frozen; not overwriting")
    qs = yaml.safe_load(open(cfg.HW10 / "eval_questions.yaml"))["questions"]
    assert len(qs) == 20, "Part 3.1 needs exactly 20 drafts"
    cases = []
    for i, q in enumerate(qs, 1):
        c = make_case(i, q)
        cases.append(c)
        print(f"[{c['case_id']}] {c['seconds']:>5}s  {q[:60]}\n       draft: {c['draft'][:110]}")
    doc = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "n": len(cases),
           "source": "HW8 Planner + Writer prompts (kafka_hw8/agents.py), in-process",
           "settings": {"temperature": 0.0, "seed": cfg.SEED}, "cases": cases}
    cfg.EVAL_CASES.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    print(f"\nsaved {cfg.EVAL_CASES.relative_to(cfg.ROOT)} ({len(cases)} drafts)")


if __name__ == "__main__":
    main()
