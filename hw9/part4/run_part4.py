"""HW9 Part 4 runner.

    python hw9/part4/build_reference.py      # once: ground truth from s7875_rel
    python hw9/part4/run_part4.py train      # training set, repair loop, lessons created on repeats
    python hw9/part4/run_part4.py validate   # keep a lesson only if validation does not regress
    python hw9/part4/run_part4.py demo       # 4.1 controlled revision + 4.2 lesson reuse
    python hw9/part4/run_part4.py test       # 4.4 four variants on the held-out test set

test_data.json is used only by `test`, after lessons are selected.
"""

import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from agents import (LESSONS, AnsweringAgent, EvaluatorAgent, LessonStore,  # noqa: E402
                    find_reference, intents, run_question, summarize_lesson)
from common import banner  # noqa: E402

RAW = os.path.join(HERE, "..", "..", "reports", "hw09", "raw")
GENERAL_CODES = {"MISSING_ACTION", "UNSAFE_CLAIM"}


def load(name):
    return json.load(open(os.path.join(HERE, name)))


def dump(name, obj):
    os.makedirs(RAW, exist_ok=True)
    json.dump(obj, open(os.path.join(RAW, name), "w"), indent=2)


def line(item, r):
    codes = r["trace"][0]["failure_codes"]
    tag = "" if r["attempts"] == 1 else f" -> attempt 2 {r['trace'][1]['result']}"
    print(f"  {item['id']} attempt 1 {r['trace'][0]['result']:<6}{tag:<22} "
          f"final={r['final_result']:<6} attempts={r['attempts']} "
          f"{r['latency_ms']/1000:5.1f}s  {','.join(codes) or ''}")


def run_set(items, ev, *, repair, store=None, allowed=None, quiet=False, validation=False):
    ans, out = AnsweringAgent(), []
    for it in items:
        r = run_question(it["question"], ans, ev, repair=repair, store=store,
                         allowed_lessons=allowed, count=not validation,
                         log=(lambda *_: None) if (quiet or validation) else print)
        r["id"] = it["id"]
        out.append(r)
        if not quiet:
            line(it, r)
    return out


# ------------------------------------------------------------------------------------------
def cmd_train(ev):
    print(banner("Part 4 - training run (Evaluator Repair + lesson creation)"))
    if os.path.exists(LESSONS):
        os.remove(LESSONS)
    store, ans, seen, results = LessonStore(), AnsweringAgent(), {}, []
    for it in load("training_data.json"):
        r = run_question(it["question"], ans, ev, repair=True, store=store)
        r["id"] = it["id"]
        results.append(r)
        line(it, r)
        first = r["trace"][0]
        for code in first["failure_codes"]:
            seen.setdefault(code, []).append({"question": it["question"], "answer": first["answer"],
                                              "feedback": first["feedback"]})
            have = any(les["failure_code"] == code for les in store.lessons)
            if len(seen[code]) >= 2 and not have:  # repeated failure pattern -> lesson
                pattern, correction = summarize_lesson(code, seen[code])
                applies = (["all"] if code in GENERAL_CODES else
                           sorted({t for e in seen[code]
                                   for t in (intents(e["question"]) or ["none"])}))
                les = store.add(pattern, correction, code, applies,
                              [e["question"] for e in seen[code]])
                print(f"    NEW LESSON {les['lesson_id']} from repeated {code} "
                      f"(applies_to={applies}): {correction}")
    dump("part4_train.json", results)
    print(f"\nfailure codes on first attempts: { {k: len(v) for k, v in seen.items()} }")
    print(f"lessons.json now has {len(store.lessons)} lesson(s)")


def score(rs, ev):
    first_fail = sum(r["trace"][0]["result"] != "PASS" for r in rs)
    final_fail = sum(r["final_result"] != "PASS" for r in rs)
    unrelated_ok = all(r["final_result"] == "PASS" for r in rs
                       if find_reference(r["question"], ev.reference) is None)
    return first_fail, final_fail, unrelated_ok


def cmd_validate(ev):
    print(banner("Part 4 - validate lessons on validation_data.json"))
    store, items = LessonStore(), load("validation_data.json")
    kept = [les["lesson_id"] for les in store.lessons if les["validated"]]
    print(f"\n[before] Evaluator Repair + kept lessons {kept or '(none)'}")
    before = run_set(items, ev, repair=True, store=store, allowed=set(kept), validation=True)
    b_first, b_final, _ = score(before, ev)
    for les in [x for x in store.lessons if x["validated"] is None]:
        print(f"\n[candidate {les['lesson_id']}] {les['failure_code']} "
              f"applies_to={les['applies_to']}: "
              f"{les['correction']}")
        after = run_set(items, ev, repair=True, store=store, allowed=set(kept + [les["lesson_id"]]),
                        validation=True)
        a_first, a_final, unrelated_ok = score(after, ev)
        regressions = [a["id"] for b, a in zip(before, after)
                       if b["final_result"] == "PASS" and a["final_result"] != "PASS"]
        keep = a_final <= b_final and a_first <= b_first and not regressions and unrelated_ok
        verdict = {"first_attempt_failures": [b_first, a_first],
                   "final_failures": [b_final, a_final],
                   "regressions": regressions, "unrelated_ok": unrelated_ok,
                   "decision": "KEEP" if keep else "REMOVE"}
        print(f"  first-attempt failures {b_first} -> {a_first} | final failures {b_final} -> "
              f"{a_final} | regressions {regressions or 'none'} | unrelated ok {unrelated_ok} "
              f"=> {verdict['decision']}")
        tgt = next(x for x in store.lessons if x["lesson_id"] == les["lesson_id"])
        tgt["validated"], tgt["validation"] = keep, verdict
        store.save()
        if keep:
            kept.append(les["lesson_id"])
            before, b_first, b_final = after, a_first, a_final
    print(f"\nkept lessons: {kept or '(none)'}")
    dump("part4_validation.json", {"kept": kept, "lessons": store.lessons})


def cmd_demo(ev):
    print(banner("Part 4 - required demonstrations"))
    ans = AnsweringAgent()
    q = "How many units of Butter batch 4609 were recalled?"
    print("\n=== 4.1 controlled revision (attempt 1 is given NO notice on purpose) ===")
    r = run_question(q, ans, ev, repair=True, inject_fault=True)
    print(f"Question: {q}")
    for t in r["trace"]:
        print(f"\n-- attempt {t['attempt']} answer:\n{t['answer']}")
        print(f"-- evaluator: {t['result']} | {t['explanation']}")
        if t["feedback"]:
            print(f"-- feedback: {t['feedback']}")
    print(f"\nFINAL: result={r['final_result']} attempts={r['attempts']} "
          f"latency={r['latency_ms']/1000:.1f}s\nfinal response: {r['final_answer']}")
    dump("part4_demo_revision.json", r)

    print("\n=== 4.2 a stored lesson is loaded for a later, related question ===")
    store = LessonStore()
    kept = {les["lesson_id"] for les in store.lessons if les["validated"]}
    for les in store.lessons:
        print(f"  {les['lesson_id']} validated={les['validated']} use_count={les['use_count']} "
              f"applies_to={les['applies_to']} created from {les['evidence']}")
    q2 = "What should I do if I bought Granola Bars batch 4664?"
    print(f"\nLater question (not in training): {q2}")
    r2 = run_question(q2, ans, ev, repair=True, store=store, allowed_lessons=kept or None)
    print(f"attempt 1 answer:\n{r2['trace'][0]['answer']}")
    print(f"evaluator: {r2['trace'][0]['result']} | {r2['trace'][0]['explanation']}")
    print(f"lessons used: {r2['lessons_used']} | final={r2['final_result']} "
          f"attempts={r2['attempts']}")
    dump("part4_demo_lesson.json", r2)


def cmd_test(ev):
    print(banner("Part 4.4 - four variants on test_data.json (held out)"))
    items, store = load("test_data.json"), LessonStore()
    kept = {les["lesson_id"] for les in store.lessons if les["validated"]}
    all_ids = {les["lesson_id"] for les in store.lessons}
    variants = [("Baseline", dict(repair=False)),
                ("Evaluator Repair", dict(repair=True)),
                ("Lesson Memory", dict(repair=True, store=store, allowed=all_ids)),
                ("Validated Improvement", dict(repair=True, store=store, allowed=kept))]
    table, detail = [], {}
    for name, kw in variants:
        extra = (f" lessons={sorted(kw['allowed'])}" if "allowed" in kw else "")
        print(f"\n[{name}]{extra}")
        rs = run_set(items, ev, **kw)
        correct = sum(r["final_result"] == "PASS" for r in rs)
        table.append({"variant": name, "correct": correct, "incorrect": len(rs) - correct,
                      "avg_attempts": round(statistics.mean(r["attempts"] for r in rs), 2),
                      "avg_latency_s": round(
                          statistics.mean(r["latency_ms"] for r in rs) / 1000, 2)})
        detail[name] = rs
    print(f"\n{'Variant':<22} | {'Correct':>7} | {'Incorrect':>9} | {'Avg attempts':>12} | "
          f"{'Avg latency (s)':>15}")
    for t in table:
        print(f"{t['variant']:<22} | {t['correct']:>4}/{len(items)} | {t['incorrect']:>9} | "
              f"{t['avg_attempts']:>12.2f} | {t['avg_latency_s']:>15.2f}")
    dump("part4_test_results.json", {"table": table, "detail": detail})


def main():
    from semantic_cache import quiet_libs
    import logging
    logging.basicConfig(level=logging.WARNING)
    quiet_libs()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "validate", "demo", "test"])
    args = ap.parse_args()
    ref = json.load(open(os.path.join(HERE, "reference_data.json")))
    ev = EvaluatorAgent(ref)
    {"train": cmd_train, "validate": cmd_validate, "demo": cmd_demo, "test": cmd_test}[args.cmd](ev)


if __name__ == "__main__":
    main()
