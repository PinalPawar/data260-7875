Metrics (Part 4 — Output Schema and Loop Safety)

Model: qwen3:1.7b (documented substitute for qwen3:8b — see report.pdf Section 0).

Experiment 1 — 30 runs on a fixed input

Fixed input: reports/hw02/cases/schema_input.json (turn_ceiling = 4). Raw data: reports/hw02/raw/experiment1_raw.json.

Outcome	Count	Mean latency (ms)
Valid first attempt	30	15420
Valid after 1 retry	0	—
Valid after 2+ retries	0	—
Hit turn ceiling	0	—
Experiment 2 — Turn ceiling 2 vs. 10 (20 runs each)

Same frozen input and model settings as Experiment 1. Raw data: reports/hw02/raw/experiment2_raw.json.

Turn ceiling	Completion rate	Mean latency (ms)
2	100.0%	14908
10	100.0%	14841

Deployment decision: turn_ceiling = 2 — same completion rate and latency as 10, so the lower ceiling is preferred (fails faster in the rare case a real input needs many retries).

Experiment 3 — Adversarial input (5 runs each, 3 attempts)
Attempt	Input	Hit turn ceiling	Notes
1 — acronym-heavy	cases/adversarial_input.json	0/5	All 5 runs produced identical tags (id lot, ai ml, id lot ai) — from coerce_reply's deterministic padding, not the model.
2 — corrupted data export	cases/adversarial_input_v2.json	0/5	Tags (id id, id id id, lot code) — one extra real phrase in the wrapper text supplied a third candidate, narrowly avoiding the short-word fallback.
3 — minimal input	cases/adversarial_input_v3.json	0/5	All 5 runs needed exactly 1 retry (turn_count = 2), unforced — the model itself proposed the tag "id" (2 characters); the validator caught it and the Planner corrected itself on the very next attempt. Full example: reports/hw02/raw/natural_retry_example.txt.

Raw data: reports/hw02/raw/experiment3_raw.json (attempt 1), experiment3_v2_raw.json (attempt 2), experiment3_v3_raw.json (attempt 3).
