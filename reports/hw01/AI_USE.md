# AI_USE.md

## 1. What I used an AI assistant for, and what I did myself

I mostly used an AI assistant as a tutor rather than a code generator I just copy-pasted from.
Before writing anything I'd ask it to explain the concept first: what a Planner/Reviewer/Finalizer
pipeline is actually supposed to do, why a closure keeps its own private counter, why the token
count keeps climbing turn after turn. Once I understood the "why" I used it to help draft the
multi-agent code in `agents_demo.py`, the automation script that runs the 40 non-determinism trials
for Part 3 (`run_nondeterminism.py`), and the model-client pieces for Part 4
(`src/model_client.py`, `hw1_client.py`, `AGENT.md`).

Everything that actually ran, I ran myself. Every command was typed into my own terminal on my own
MacBook, and when things broke, which they did, I was the one debugging it: a broken import, a file
I could've sworn was in one folder but was actually in another, a terminal that froze after a bad
paste, and a Docker "port is already allocated" error that took a minute to figure out. I made a
point of actually reading the console output myself each time before trusting that something
worked, instead of assuming the AI's code was correct just because it looked reasonable.

One more note on process: I also used an AI assistant to help format and assemble the final report.pdf itself, pulling my screenshots, tables, and notes into a single write-up. The actual answers, explanations, and analysis in it are mine, the AI just helped with the layout and typing it up.

## 2. One AI-produced output that was wrong/unsuitable

During the Part 4 five-turn conversation demo, the model I was running locally (`qwen3:8b`) kept
insisting my code had an invalid `/think` suffix in it. It said this across four different turns.
That was odd because I never typed anything like that in any of my messages.

## 3. How I detected the problem

I went back and reread everything I had typed into the terminal, line by line, checking whether
`/think` showed up anywhere. It didn't. That's when it clicked that the model wasn't actually
reviewing my code correctly, it was hallucinating a problem that wasn't there.

## 4. What I changed, and why it works now

I didn't touch my own code, because there was nothing wrong with it, the issue was entirely on the
model's side. My best guess is that `qwen3:8b` is a "thinking" model under the hood, meaning it
uses special `/think` and `/no_think` tokens internally to toggle its own reasoning mode, and one
of those tokens must have leaked into what it thought was my input. So it ended up "reviewing" a
line that never existed in my actual message. The takeaway for me was not to take an AI reviewer's
claims at face value. I now double-check what it says against what I actually typed before changing
anything based on its feedback.
