"""HW9 Part 4: Answering Agent, Evaluator Agent, lesson store, and the repair loop.

Agent communication is a JSON message exchange, kept in a trace:
    Answering -> Evaluator : {"question", "answer", "attempt"}
    Evaluator -> Answering : {"result": PASS|REVISE, "explanation", "feedback", "failure_codes"}
    Answering -> Evaluator : revised {"answer", "attempt": 2}   (only after REVISE)
Stopping condition: PASS, or after the 2nd attempt (whatever the result).

Answering Agent : qwen3:1.7b through the HW8 adapter (kafka_hw8/llm.py: temp 0, seed, think off).
                  Facts come from the operational DB (s7875_rel, same lookup as the Part 2 cache).
Evaluator Agent : checks the answer against reference_data.json (ground truth) with explicit,
                  per-question-type fact checks. It is deliberately rule-based: Part 2 showed a
                  1.7b LLM judge rejecting correct answers with self-contradicting reasons.
                  The LLM is used only to write the text of new lessons (summarize_lesson).
"""

import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HW9 = os.path.dirname(HERE)
ROOT = os.path.dirname(HW9)
for p in (HW9, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from kafka_hw8.agents import unsafe_phrase  # noqa: E402  (HW8 safety rule, reused)
from kafka_hw8.llm import chat  # noqa: E402
from notice_context import context_line, find_notice  # noqa: E402

LESSONS = os.path.join(HERE, "lessons.json")
MAX_ATTEMPTS = 2

ANSWER_SYSTEM = (
    "You are the Answering Agent for a grocery recall help desk. Answer the customer's question "
    "in 2-4 short sentences. Use only the recall notice provided with the question. If no notice "
    "is provided, the question is not about a recall on file: answer briefly and do not invent "
    "recall details such as notice codes, lot numbers, batch numbers or unit counts.")

ACTION_WORDS = ("stop using", "do not eat", "don't eat", "not eat", "throw", "discard",
                "dispose", "return")
CATEGORY_WORDS = {
    "bacterialContamination": ("listeria", "bacteri"),
    "mislabelling": ("allergen", "label"),
    "foreignMaterial": ("metal", "foreign"),
    "supplyShortage": ("packaging", "fill", "shortage"),
}
FEEDBACK = {
    "MISSING_UNITS": "State the exact number of units affected, as written in the notice.",
    "MISSING_LOT": "Give the affected lot number exactly as written in the notice (e.g. L1xxxx).",
    "MISSING_MANUFACTURER": "Name the manufacturer listed on the notice.",
    "MISSING_CODE": "Give the recall notice code exactly as written (RCL-YYYY-NNNNN).",
    "WRONG_REASON": "State the recall reason/category from the notice; do not substitute "
                    "another hazard (e.g. do not say Listeria for an allergen or metal recall).",
    "MISSING_ACTION": "Tell the customer what to do: stop using it, do not eat it, throw it away "
                      "or return it to the store, and clean surfaces it touched.",
    "UNSUPPORTED_CLAIM": "Remove recall details that are not on the notice for this question "
                         "(other notice codes, lot or batch numbers, unit counts).",
    "UNSAFE_CLAIM": "Never suggest a recalled product may be safe to eat.",
}


def intents(question: str) -> list[str]:
    q = question.lower()
    out = []
    if "how many" in q or "units" in q:
        out.append("units")
    if re.search(r"\blot\b", q):
        out.append("lot")
    if any(w in q for w in ("manufactur", "company", "who makes", "brand")):
        out.append("manufacturer")
    if "code" in q:
        out.append("code")
    if any(w in q for w in ("why", "reason", "cause", "because of", "category")):
        out.append("reason")
    if any(w in q for w in ("should i do", "bought", "steps", "safe to")):
        out.append("action")
    return out


def find_reference(question: str, reference: list[dict]) -> dict | None:
    m = re.search(r"batch\s*(\d{3,5})", question, re.I)
    if m:
        return next((r for r in reference if r["batch"] == int(m.group(1))), None)
    m = re.search(r"RCL-\d{4}-\d{5}", question, re.I)
    if m:
        return next((r for r in reference if r["notice_code"] == m.group(0).upper()), None)
    return None


# ------------------------------------------------------------------------------------------
class LessonStore:
    def __init__(self, path=LESSONS):
        self.path = path
        self.lessons = json.load(open(path)) if os.path.exists(path) else []

    def save(self):
        json.dump(self.lessons, open(self.path, "w"), indent=2)

    def relevant(self, question: str, allowed_ids=None, count=True) -> list[dict]:
        """Lessons whose applies_to matches this question's type (or 'all').
        count=False during validation runs, so use_count only reflects real reuse."""
        tags = set(intents(question)) or {"none"}
        if find_notice(question) is None:
            tags.add("none")
        out = [les for les in self.lessons
               if (allowed_ids is None or les["lesson_id"] in allowed_ids)
               and ("all" in les["applies_to"] or tags & set(les["applies_to"]))]
        if count and out:
            for les in out:
                les["use_count"] += 1
            self.save()
        return out

    def add(self, failure_pattern, correction, failure_code, applies_to, evidence):
        lid = f"lesson_{len(self.lessons) + 1:03d}"
        lesson = {"lesson_id": lid, "failure_pattern": failure_pattern, "correction": correction,
                  "created_at": dt.date.today().isoformat(), "use_count": 0,
                  "failure_code": failure_code, "applies_to": applies_to,
                  "evidence": evidence, "validated": None}
        self.lessons.append(lesson)
        self.save()
        return lesson


# ------------------------------------------------------------------------------------------
class AnsweringAgent:
    def answer(self, question, lessons=(), previous=None, feedback=None, withhold_notice=False):
        notice = None if withhold_notice else find_notice(question)
        user = question + (context_line(notice) if notice else "\n\n[No recall notice on file.]")
        if lessons:
            user += "\n\nLessons from earlier evaluated answers (apply them):\n" + "\n".join(
                f"- {les['lesson_id']}: {les['correction']}" for les in lessons)
        if previous is not None:
            user += (f"\n\nYour previous answer:\n{previous}\n\nEvaluator feedback (fix all of "
                     f"it):\n{feedback}\n\nWrite the corrected answer now.")
        return chat(ANSWER_SYSTEM, user, max_tokens=300)


class EvaluatorAgent:
    def __init__(self, reference: list[dict]):
        self.reference = reference

    def evaluate(self, question: str, answer: str) -> dict:
        a = answer.lower()
        ref = find_reference(question, self.reference)
        codes = []
        if ref is None:  # not about a notice on file -> must not invent recall facts
            invented = (r"RCL-\d{4}-\d{5}|\blot\s*#?\s*L\d{4}"
                        r"|\bbatch\s*#?\s*\d{3,5}|units affected")
            if re.search(invented, answer, re.I):
                codes.append("UNSUPPORTED_CLAIM")
        else:
            need = intents(question)
            if "units" in need and not re.search(
                    rf"\b{ref['units_affected']:,}\b|\b{ref['units_affected']}\b", answer):
                codes.append("MISSING_UNITS")
            if "lot" in need and ref["lot"].lower() not in a.replace("#", ""):
                codes.append("MISSING_LOT")
            if "manufacturer" in need and ref["manufacturer"].lower() not in a:
                codes.append("MISSING_MANUFACTURER")
            if "code" in need and ref["notice_code"].lower() not in a:
                codes.append("MISSING_CODE")
            if "reason" in need:
                ok = any(w in a for w in CATEGORY_WORDS[ref["category"]])
                wrong_listeria = (ref["category"] != "bacterialContamination"
                                  and re.search(r"(due to|because of|caused by)\s+listeria", a))
                if not ok or wrong_listeria:
                    codes.append("WRONG_REASON")
            if not any(w in a for w in ACTION_WORDS):
                codes.append("MISSING_ACTION")
            other_codes = set(re.findall(r"RCL-\d{4}-\d{5}", answer.upper())) - {ref["notice_code"]}
            if other_codes:
                codes.append("UNSUPPORTED_CLAIM")
        if unsafe_phrase(answer):
            codes.append("UNSAFE_CLAIM")
        if not codes:
            return {"result": "PASS", "explanation": "All facts the question needs match the "
                    "reference dataset" + (" and the required consumer action is present."
                                           if ref else "; no invented recall details."),
                    "feedback": "", "failure_codes": []}
        return {"result": "REVISE",
                "explanation": "Checked against reference_data.json: " + ", ".join(codes) + ".",
                "feedback": " ".join(FEEDBACK[c] for c in codes), "failure_codes": codes}


# ------------------------------------------------------------------------------------------
def run_question(question, answerer, evaluator, *, repair: bool, store: LessonStore | None = None,
                 allowed_lessons=None, inject_fault=False, log=print, count=True) -> dict:
    """One question through the system. repair=False -> one attempt (Baseline)."""
    t0 = time.perf_counter()
    lessons = store.relevant(question, allowed_lessons, count) if store else []
    if lessons:
        log("    LESSONS LOADED: " + ", ".join(
            f"{les['lesson_id']} (use_count={les['use_count']})" for les in lessons))
    trace = []
    answer = answerer.answer(question, lessons, withhold_notice=inject_fault)
    ev = evaluator.evaluate(question, answer)
    trace.append({"attempt": 1, "answer": answer, **ev})
    attempts = 1
    if repair and ev["result"] == "REVISE" and attempts < MAX_ATTEMPTS:
        answer = answerer.answer(question, lessons, previous=answer, feedback=ev["feedback"])
        ev = evaluator.evaluate(question, answer)
        attempts = 2
        trace.append({"attempt": 2, "answer": answer, **ev})
    return {"question": question, "final_answer": answer, "final_result": ev["result"],
            "attempts": attempts, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "lessons_used": [les["lesson_id"] for les in lessons], "trace": trace}


def summarize_lesson(code: str, examples: list[dict]) -> tuple[str, str]:
    """Evaluator side: turn a repeated failure into a reusable lesson (LLM wording, with a
    rule-based fallback if the model output is not usable JSON)."""
    ex = "\n".join(f"- Q: {e['question']}\n  A: {e['answer'][:200]}\n  Feedback: {e['feedback']}"
                   for e in examples[:3])
    raw = chat("You write short reusable lessons for a recall help-desk agent. Reply with JSON "
               "only: {\"failure_pattern\": \"...\", \"correction\": \"...\"}. One sentence each.",
               f"Repeated failure code: {code}\nExamples:\n{ex}", max_tokens=150)
    try:
        j = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        if j.get("failure_pattern") and j.get("correction"):
            return j["failure_pattern"].strip(), j["correction"].strip()
    except Exception:
        pass
    return (f"Answers repeatedly fail check {code}.", FEEDBACK[code])
