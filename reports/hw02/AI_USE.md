1. What I used an AI assistant for, and what I did myself

I didn't lean on an AI assistant for most of this assignment — I only pulled it in for the handful of things that actually needed explaining before I could write anything sensible myself: understanding what a "supervisor pattern" actually means in LangGraph (versus just chaining nodes), why a router function has to be read-only instead of mutating state, and what a Pydantic field_validator is doing under the hood when it raises a ValueError. Once those clicked, I wrote the actual node logic in graph_agent.py and schema_agent.py myself.

Where I did use it more directly was for the repetitive parts: once I had one experiment script working (run_experiment1.py), the other two (run_experiment2.py, run_experiment3.py) follow almost the same shape, just looping differently, so I had it help draft those faster instead of retyping the same boilerplate three times. I also used it to help assemble the final report.pdf — pulling my screenshots, code, and results into one formatted document — same as I did for HW1.

Everything that actually ran, ran on my own MacBook, in my own terminal. Every screenshot in this report is a real run I watched happen, not something generated for me.

2. One AI-produced output that was wrong/unsuitable

The first draft of planner_node in graph_agent.py (Part 3) had a real bug: it never cleared out the old reviewer_feedback when it produced a new proposal. It looked completely reasonable reading it top to bottom — nothing about it looked wrong.

3. How I detected the problem

I tested the loop-back logic by temporarily forcing reviewer_node to always report an issue, expecting to see Planner → Reviewer → Planner → Reviewer alternate a few times before stopping. Instead, watching the printed output of each node as the graph streamed, I noticed the Planner ran three times in a row but the [Reviewer] Node activated line only ever printed once. That mismatch is what gave it away — if the loop were working, the Reviewer should have run just as many times as the Planner.

4. What I changed, and why it works now

I traced it to reviewer_feedback never getting reset. Because it stayed set to the old value, router_logic kept seeing the same stale feedback and routing straight back to the Planner without ever sending the new proposal past the Reviewer again. I changed planner_node to reset reviewer_feedback to None every time it produces a new proposal, so the router always sees a fresh state. After the fix, I reran the same forced-issue test and confirmed it now properly alternates Planner → Reviewer → Planner → Reviewer before stopping at the turn ceiling — saved in reports/hw02/part3_run_log.txt.
