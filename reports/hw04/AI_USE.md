# AI_USE.md - HW4

## 1. What I used an AI assistant for, and what I did myself

I used Claude primarily to understand the underlying concepts before implementing anything myself, across all four parts of this assignment on top of my HW1-3 codebase -- e.g. why an opaque session token stored server-side (referenced only by a random token in an HttpOnly cookie) is different from HW3's signed cookie, how SQLAlchemy's joinedload() avoids the N+1 problem, why removing a ForeignKey constraint from RelatedInfo mattered for the Part 3 index demo, and why my RAG script's answers were coming back empty. Once I understood the reasoning, I wrote and ran everything myself: every actual command -- MySQL setup, pip installs, starting the backend and frontend servers, every Postman request, seeding the 5000-row dataset, running the N+1 measurements, and running rag.py against my own locally installed qwen3 model -- was executed by me on my own MacBook Air, one command at a time. Every screenshot and every line of terminal output in this submission is real output from my own machine, not generated or simulated.

## 2. One AI-produced output that was wrong/unsuitable

The first version of rag.py's generation step (call_ollama) came back with almost entirely empty answers when I actually ran it against my local qwen3:1.7b model -- 10 of 18 question/config pairs returned a blank "A:" across the three RAG configs, and one call took 47 seconds while still returning nothing.

## 3. How I detected the problem

I detected it because I actually ran the script and read my real terminal output line by line instead of assuming it worked -- the pattern was too consistent (every no_rag and most basic_rag/context_engineered answers for Q1-Q4 were blank) to be a fluke, and the 47-second latency on the very first call stood out compared to the roughly 10-second calls that followed it.

## 4. What I changed, and why it works now

The cause was that qwen3 is a "thinking" model that spends its response budget on internal reasoning before writing an actual answer -- with only 200 tokens allowed, it used the entire budget thinking and never produced real output text. The fix was adding "think": false to the Ollama API request (skipping the reasoning step, since a direct answer is all this task needs) and raising the token budget to 400 as a safety margin. Re-running the exact same command produced real, grounded answers for every question, and the context-engineered config correctly refused both questions it should have (Smucker's 2022 peanut-butter revenue -- not in the documents -- and the unrelated Tesla stock price question) while still answering all four in-domain recall questions correctly -- which is the actual behavior Part 4 is meant to demonstrate.
