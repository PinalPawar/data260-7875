# HW7 - AI_USE.md (Pinal Pawar, SID4 7875)

## 1. What I used an AI assistant for, and what I did myself

I used Claude for explaining the concepts (JWT
claims and 401 vs 403, ReAct/MRKL tool loops, Reflexion, prompt injection, tool-boundary
checks), the JWT router and migration, the Reflexion wrapper, the attack fixture and scoring, the file tools and the safety gate, the offline
tests, and it also assembled the first draft of this report with my screenshots.

I did all the running and checking myself, on my own MacBook with my own MySQL, Ollama
(qwen3:1.7b and qwen3:8b) and conda environment. I ran the migration, every Swagger request,
every agent run and test, and every Part 4 UI run, took every screenshot, and read the outputs
before accepting them. When a run looked wrong I sent the screenshot back and fixed the
cause instead of re-running until it looked good. Several runs that failed are kept in
`reports/hw07/raw/` and described in the report. I also chose the city (Bay Wheels) and how the
two acceptance scenarios were built from the public trip data. I
am uploading the repository myself.

## 2. One AI-produced output that was wrong/unsuitable

The verifier the assistant wrote for task C in Parts 2 and 3 (compare the two most relevant
recall notices) scored answers wrongly, in both directions.

- **Version 1** accepted any two looked-up codes in sorted order. It passed a retry that
  compared all five notices and named the wrong one as the largest.
- **Version 2** required the answer to mention no other codes. It **rejected a correct answer**
  (run 15 listed all five notices but correctly said RCL-2026-04978, 782 units, beat
  RCL-2026-04983, 377 units), and it still **accepted** two answers that cited both codes but
  gave manufacturer totals instead of each notice's units.

Because Reflexion trusts the verifier, the false rejection triggered a pointless retry, and the
false acceptances inflated the success rate.

## 3. How I detected the problem

The numbers looked fine, so the problem only showed up when I read the answers. For Part 3 I
read every answer the verifier rejected and every retry it accepted, next to the
`get_notice_detail` results in the trace, and wrote down my own verdict for each
(`raw/part3_manual_review.json`, `raw/part3_grounded_manual_review.json`). My verdicts and the
verifier's disagreed on run 15 and on the two grounded retries.

## 4. What I changed, and why it works now

The final check tests what the task actually asks for: the first two search results were both
looked up, the answer cites both codes, and it states each notice's `units_affected` and
`manufacturer` exactly as `get_notice_detail` returned them. Each wrong case became a regression
test. I re-ran the Part 2 reliability test and all of Part 3 with the final verifier, and kept
the earlier runs as evidence (`raw/part3_run1_lenient_C_check/`,
`raw/part3_run2_stays_on_pair_check/`). With the final verifier there were no false rejections,
and every saved answer matches my manual reading. The lesson I took from it: a deterministic
check is only as good as the rule inside it, so I check the checker against real answers.

## Other AI outputs I checked and kept as findings, not hidden

- **Part 2:** the first agent loop scored 0/21 because qwen3:1.7b copied the example code from
  the HW5 tool description and asked for all calls in one turn. Fixed with a description with no
  copyable example and a one-call-per-turn rule.
- **Part 4:** the agent's first plans gave wrong totals (left a placeholder in SQL, split
  formulas across calls, reported the membership total as the fees). One run overflowed the
  model's context with a 199-row tool result; others had every number right but picked the
  wrong plan, or invented a $19.99 pass price after asking for only one passage. The
  independent cost check caught every one; the fixes were a row cap, one calculator call per
  formula, a minimum of 6 passages and a decision guard.
- **Part 5:** the first cost check recomputed from the agent's own copy of the table, so an
  unguarded DELETE would also change the "correct" numbers. It now rebuilds from the uploaded
  file.
- **Part 6:** the first, prefix-only gate allowed `ls && chmod -R 777 .` and
  `echo pwned > /etc/hosts`. While testing extra commands I also found that `ls $(rm -rf x)`
  was blocked but not reported as destructive. Both are fixed and covered by tests.
