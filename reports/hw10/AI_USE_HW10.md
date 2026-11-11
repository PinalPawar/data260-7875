# HW10 - AI_USE.md (Pinal Pawar, SID4 7875)

## 1. What I used an AI assistant for, and what I did myself

I used Claude to read the HW10 assignment the GEval example `ge-eval2.py` and the Streamlit demo) with me. It explained
the concepts as we went: LLM-as-judge with GEval/DeepEval, Spearman rank correlation and mean
absolute difference, judge repeatability, trace propagation with structured spans, and p50/p95
latency, the traced ingress , the span writer and the span hooks in the HW8 agent loop, the evaluator and local-judge
wrapper, the Part 3 and Part 4.3 scripts and the Streamlit dashboard. It also drafted the report around my screenshots and results.

Claude could not reach my Kafka, Redis, MySQL or Ollama - they run on my Mac Everything reported here I ran myself on a
MacBook Air (Apple M2, 16 GB) in the `data260` conda env: Kafka and Redis Stack in Docker, MySQL
`s7875_rel`, the three HW8 agents, and qwen3:1.7b / qwen3:8b in Ollama. I took every screenshot and
read the outputs before accepting them. **I assigned all 20 human helpfulness labels myself** with
`hw10/label_drafts.py` (it only shows the draft and reads my keystroke; no model is involved), and I
committed `eval_cases.json` and `human_labels.csv` (commit `8454314`) before the judge ever ran. I
did not relabel anything after seeing the judge's scores.

## 2. One AI-produced output that was wrong/unsuitable

The judge set-up the assistant wrote was not a reliable judge of helpfulness. Every GEval
evaluation step included the same safety sentence ("a recalled food is never safe to eat; advice
must say stop using it, discard or return it, clean surfaces, and see a doctor"). That pushed the
judge (qwen3:8b) to score how well a draft repeats the recall checklist instead of whether it
answers the question. Against my labels it gave a **Spearman correlation of −0.54** with a mean
absolute difference of 1.0. It gave 5/5 to two drafts I rated 2/5 because they never answered the
question (c14, "a store is still selling a recalled product"; c18, "I threw the package away, was
my chicken the recalled one?"). It gave 3/5 to two direct answers I rated 5/5 because they left out
the checklist (c15, donating canned goods; c20, symptom onset).

A second problem in the same area: the assistant's Final-vs-Draft metric scores the final answer
with the Reviewer's verdict line attached. Because my Reviewer never changes the text (51 of 51
finals were identical to the draft), the "improvement" only measures the judge's reaction to that
line: +0.62 on average for approved answers and −2.84 for all 19 rejected ones.

Smaller ones:
- The first MySQL check it gave me used the wrong names (`engine`, `recall_notices` instead of
  `get_engine`, `notices`) and failed with an ImportError.
- `ingress.py --examples` ran the Part 2 evaluation but did not print the scores; I needed an extra
  command to see them.
- Four lines were over the 100-character limit, which my repo's ruff pre-commit hook would have
  rejected at commit time.

## 3. How I detected the problem

The judge bias was caught by the Part 3 comparison with my frozen labels, not by the Part 2 run
(the single test question scored a believable 4/5/5). The negative Spearman made me print the
judge's own reasons for the four biggest disagreements, and every reason was about the checklist
("stopping use, discarding, returning, cleaning") rather than the question asked. The verdict-line
problem showed on the dashboard's Evaluation page: one trace had draft 4 and final 5 with identical
text. A summary over all 51 evaluated requests, then a split by Reviewer verdict, showed the pattern
(51/51 identical text; approved +0.62, rejected −2.84). The import error showed up in my terminal,
and the lint problem was found by running ruff on the HW10 files before the final commit.

## 4. What I changed and why it works now

- **Judge: reported, not re-tuned.** I did not change the rubric and rerun Part 3. Tuning the judge
  until it agrees with the same 20 frozen labels would make the comparison meaningless. Instead the
  report states that this judge should not gate a deployment, and lists what I would require first:
  Spearman ≥ 0.7 on a fresh frozen set of 50–100 drafts covering all of 1–5 (including deliberately
  bad drafts), a second human labeller, a rubric that scores "answers the question" separately from
  safety, and a judge from a different model family than the Reviewer.
- **Final-vs-Draft: interpreted honestly.** The report and the dashboard explain that the Reviewer is
  a gate, not an editor, and that the improvement score reflects the verdict line, not better
  answers. The real coordination gap is that a rejected draft is not sent back to the Writer.
- **Other fixes.** The MySQL check was rerun with the right names (5,001 notices). The Part 2 scores
  were printed from `eval_results.jsonl` with `evaluator.print_row`. The long lines were rewrapped
  (formatting only); ruff passes and the 27 HW10 and 57 HW8 offline tests still pass.
- **Measurement detail I added after seeing the data.** Cache-hit latency looked slow (9–14 s) in
  one-shot commands, so I measured warm hits in one process: about 34 ms. Both are in the report,
  and the cold start (loading the embedding model) is named as the cause.
- **Self-check.** `scripts/verify_hw10.py` re-checks the deliverables (20 frozen drafts and labels,
  labels committed before judging, required span fields, all three trace examples, 50 confirmed
  cache misses) and saved `reports/hw10/verification.json`: 19/19 checks passed.
