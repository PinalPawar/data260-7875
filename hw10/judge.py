"""HW10 Parts 2-3: the GEval judge (DeepEval) on a LOCAL Ollama model, on a 1-5 scale.

Judge model: HW10_JUDGE_MODEL (default qwen3:8b) through Ollama at temperature 0, seed 7875,
thinking off, JSON-schema constrained output. It plugs into DeepEval as a custom
DeepEvalBaseLLM, so GEval runs unchanged with no OpenAI key.

Scale: every metric has a 5-band Rubric with score_range (1,1) ... (5,5), so GEval asks the
judge for an integer 1-5 directly. DeepEval normalises that to (s-1)/4 in metric.score; we
store the 1-5 value (score_1_5) and the normalised value.

Bounds (2.1): the Ollama client has a timeout, and each metric runs in a worker thread that is
abandoned after JUDGE_TIMEOUT_S, so an unavailable or stuck judge returns status
"judge_error" / "judge_timeout" instead of hanging the run.
"""

import concurrent.futures as cf
import json
import re
import time

import hw10cfg as cfg

from deepeval.metrics import GEval
from deepeval.metrics.g_eval import Rubric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase

try:  # deepeval >= 4 renamed LLMTestCaseParams
    from deepeval.test_case import SingleTurnParams as P
except ImportError:  # pragma: no cover - older deepeval
    from deepeval.test_case import LLMTestCaseParams as P

BANDS = [(1, "very poor: wrong, unsafe, off-topic or unusable"),
         (2, "poor: major gaps or errors; a shopper would be misled or left stuck"),
         (3, "acceptable: mostly right but missing an important point or vague"),
         (4, "good: accurate, safe and useful with only minor gaps"),
         (5, "excellent: accurate, safe, specific, complete and easy to act on")]
RUBRIC = [Rubric(score_range=(s, s), expected_outcome=t) for s, t in BANDS]
SAFETY = ("A recalled food is never safe to eat; advice must say stop using it, discard or "
          "return it, clean surfaces, and see a doctor for symptoms or high-risk people.")


class OllamaJudge(DeepEvalBaseLLM):
    """DeepEval custom model: local Ollama, deterministic settings, schema-constrained JSON."""

    def __init__(self, model: str = cfg.JUDGE_MODEL, base_url: str = cfg.JUDGE_URL) -> None:
        self.model_id, self.base_url = model, base_url
        super().__init__(model)

    def load_model(self):
        """Create the Ollama client (timeout keeps a dead server from hanging us)."""
        import ollama
        return ollama.Client(host=self.base_url, timeout=cfg.JUDGE_TIMEOUT_S)

    def generate(self, prompt: str, schema=None):
        """One judge call; returns a schema instance when DeepEval asks for one."""
        kwargs = {"format": schema.model_json_schema()} if schema is not None else {}
        resp = self.model.chat(
            model=self.model_id, messages=[{"role": "user", "content": prompt}], think=False,
            options={"temperature": cfg.JUDGE_TEMPERATURE, "seed": cfg.JUDGE_SEED,
                     "num_predict": cfg.JUDGE_MAX_TOKENS}, **kwargs)
        text = re.sub(r"<think>.*?</think>", "", resp["message"]["content"] or "", flags=re.S)
        if schema is None:
            return text.strip()
        return schema(**json.loads(_json_part(text)))

    async def a_generate(self, prompt: str, schema=None):
        """Async variant (DeepEval may call it); runs the sync call."""
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        """Name DeepEval prints and we store with every score."""
        return f"{self.model_id} (Ollama, temperature 0, seed {cfg.JUDGE_SEED}, think off)"


def _json_part(text: str) -> str:
    """The outermost {...} in a reply (guards against stray text around the JSON)."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _metric(name: str, steps: list[str], params: list, judge: DeepEvalBaseLLM) -> GEval:
    """A GEval metric with fixed evaluation steps (no step-generation call) and 1-5 rubric."""
    return GEval(name=name, evaluation_steps=steps, evaluation_params=params, rubric=RUBRIC,
                 model=judge, async_mode=False, threshold=0.5, verbose_mode=False)


def build_metrics(judge: DeepEvalBaseLLM | None = None) -> dict[str, GEval]:
    """The four Part 2 criteria. final_helpfulness is reused for the draft in 'improvement'."""
    judge = judge or OllamaJudge()
    io = [P.INPUT, P.ACTUAL_OUTPUT]
    return {
        "plan_quality": _metric("Plan Quality", [
            "Read the shopper's question in Input and the Planner's step list in Actual Output.",
            "Check the steps cover what the question needs: the product and recall reason, "
            "what to do with the product, health risk and symptoms, and who to contact.",
            "Check the steps are short, ordered, actionable and do not repeat each other.",
            "Penalise steps that are off-topic, invent facts, or suggest a recalled product "
            "might be safe. " + SAFETY], io, judge),
        "writer_helpfulness": _metric("Writer Helpfulness", [
            "Read the question and plan in Input and the Writer's draft answer in Actual Output.",
            "Check the draft is accurate: no invented lot numbers, dates or brands, and no "
            "claim that is false for food recalls. " + SAFETY,
            "Check it is useful: it answers the actual question with concrete next steps "
            "and covers the plan.",
            "Penalise vagueness, contradictions, unsafe advice and padding."], io, judge),
        "final_helpfulness": _metric("Final Answer Helpfulness", [
            "Read the shopper's question in Input and the answer the shopper receives in "
            "Actual Output (it may end with the Reviewer's verdict).",
            "Check the answer is relevant to this exact question and helps the shopper act.",
            "Check it is accurate and safe. " + SAFETY,
            "Penalise answers that are off-topic, generic, unsafe or confusing."], io, judge),
    }


def measure(metric: GEval, inp: str, out: str, timeout_s: float = cfg.JUDGE_TIMEOUT_S
            ) -> dict:
    """Run one metric with a hard time bound. Never raises; failures come back as status."""
    t0 = time.perf_counter()
    case = LLMTestCase(input=inp, actual_output=out)
    pool = cf.ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(metric.measure, case, _show_indicator=False)
        fut.result(timeout=timeout_s)
        s = float(metric.score)
        res = {"status": "ok", "score_1_5": round(1 + 4 * s, 3), "score_norm": round(s, 4),
               "reason": metric.reason}
    except cf.TimeoutError:
        res = {"status": "judge_timeout", "score_1_5": None, "score_norm": None,
               "reason": f"judge did not answer within {timeout_s:.0f}s"}
    except Exception as exc:  # noqa: BLE001 - unavailable judge / bad JSON must not stop us
        res = {"status": "judge_error", "score_1_5": None, "score_norm": None,
               "reason": f"{type(exc).__name__}: {exc}"[:400]}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    res["judge_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return res


def judge_settings(judge: DeepEvalBaseLLM | None = None) -> dict:
    """Settings saved next to every score so a run can be reproduced."""
    import deepeval
    return {"framework": f"DeepEval {deepeval.__version__} GEval",
            "judge_model": (judge or OllamaJudge()).get_model_name(),
            "scale": "1-5 integer rubric (1 very poor ... 5 excellent)",
            "temperature": cfg.JUDGE_TEMPERATURE, "seed": cfg.JUDGE_SEED,
            "max_tokens": cfg.JUDGE_MAX_TOKENS, "timeout_s": cfg.JUDGE_TIMEOUT_S,
            "evaluation_steps": "fixed in hw10/judge.py (no step-generation call)"}
