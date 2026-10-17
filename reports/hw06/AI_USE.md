# HW6 - AI_USE.md (Pinal Pawar, SID4 7875)

I used Claude mainly as a support tool for understanding the assignment, clarifying concepts, troubleshooting errors, and getting occasional suggestions for improving my code and report. 

I set up the required software and services on my own computer, implemented and tested the different parts of the assignment, ran the experiments and conversations, collected the outputs, took the screenshots, and reviewed the results. I also handled issues that came up during testing, such as stalled requests and missing information in screenshots.

## 2. An AI-produced output that was wrong

The first version of the model-call code for `/api/chat` had no limit on reply length, no
timeout, and left qwen3's hidden "thinking" mode on. Three things went wrong in real runs:

- Turn 8 of the Part 2 conversation hung for more than 30 minutes. It was the turn that runs
  the most model calls (reply, fact extraction, session summary and the first lifetime
  summary).
- After a restart, a reply came back **empty**.
- The first lifetime summary was **invented**. It described a "35-year-old male with
  hypertension, diabetes ... on metformin", while the real conversation was about peanut
  allergies and grocery recalls.

A second problem, from Part 3: the AI-designed automatic probe scorer only checked whether
key words appeared. It gave 5/5 to answers that were factually wrong, for example
"You and your son are allergic to eggs and peanuts", where the allergies belong to different
people.

## 3. How I detected the problem / verified the result

- **The hang:** the chat page kept waiting. The server log showed no new `POST /api/chat` line,
  and `ollama ps` showed the model "Stopping...". When I stopped the server, it logged
  `CancelledError` and a 500 for that request. MongoDB showed that turn 8's message and reply
  had been saved, so the model had answered and the hang came after it, during the summary
  calls.
- **The empty reply and invented summary:** both were visible on the chat page's memory panel
  (screenshot kept). The invented lifetime summary did not match anything in the `messages`
  collection.
- **The scorer:** I read all 20 probe answers myself against the facts in the conversation and
  compared them with the automatic scores.

## 4. What I changed and why it works now

- `src/model_client.complete()` got optional `max_tokens` (Ollama `num_predict`), `timeout`,
  `think`, `seed` and `num_ctx` arguments. Their defaults keep earlier homeworks unchanged.
  Every HW6 call now uses `think=False`, a token cap and a 180 s timeout. Empty summaries are
  never stored, and an empty reply returns HTTP 502. Fact extraction and summaries run in
  their own error handling, so a failure there no longer blocks the reply.
- I deleted the broken memory and re-ran the 12-message conversation. Turn 8, the worst
  case, finished in 24 s instead of hanging. Model replies took about 1-8 s per turn, and the
  summaries match the conversation.
- **Scoring:** I added a manual review (`raw/p3_probe_manual_review.json`) with one fixed rule:
  -1 for each wrong or invented detail, -2 for an allergy given to the wrong person. The report
  uses the manual scores and shows the automatic ones next to them. This lowered quality from
  3.6-4.4 to 3.2-3.4, but it now measures what the answers actually say.

## Other AI outputs I checked and kept as findings, not hidden

- **Part 2 cURL test:** the model said frozen shrimp is "generally safe for people with
  shellfish allergies" right after storing "User is allergic to shellfish". Memory worked; the
  1.7B model's reasoning did not. This is documented as a limitation.
- **Part 4 first chat run:** `/dream` stored the son's egg allergy as the user's allergy and the
  cantaloupe as a store. Consolidation flagged both instead of overwriting the true facts, and
  I fixed the `/dream` prompt by giving each key a meaning and an example.
- **Part 4 consolidation:** one contradiction (Safeway vs Costco) was resolved incorrectly by
  the newest-wins rule. It is reported, not hidden.
