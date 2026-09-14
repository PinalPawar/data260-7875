# DATA-260 HW1, Pinal Pawar (SID4: 7875)

Domain: **Grocery supply and recall notices** (DOMAIN_ID = 3)

## Section 0, Configuration

| Value | Definition | This submission |
|---|---|---|
| SID4 | Last 4 digits of SJSU Student ID | 7875 |
| PORT_BASE | 8000 + (SID4 mod 900) | 8675 |
| PREFIX | "s" + SID4 | s7875 |
| SEED | SID4 | 7875 |
| VERIFY_SEED | 260000 + SID4 | 267875 |
| DOMAIN_ID | SID4 mod 8 | 3 (Grocery supply and recall notices) |
| Hardware | N/A | MacBook Air, Apple M2, 16GB RAM |
| Local model | N/A | qwen3:8b (via Ollama) |
| Tagged commit | N/A | see `hw1` tag on this repo |

## Reproducible run instructions

### Prerequisites
- Docker Desktop installed and running
- Python 3.11 or 3.12
- [Ollama](https://ollama.com) installed and running, with `qwen3:8b` pulled:
  ```
  ollama pull qwen3:8b
  ```
- Python deps: `pip install ollama langchain langchain-ollama langchain-core`

### Part 1, Run the web app locally with Docker
```
docker build -t my-web-app .
docker run -d -p 8675:8675 --name my-web-app-local my-web-app
```
Then open `http://localhost:8675` in a browser.

To stop/remove:
```
docker stop my-web-app-local && docker rm my-web-app-local
```

### Part 1, Deploy to AWS ECS (Fargate)
1. Push the image to ECR:
   ```
   aws ecr create-repository --repository-name my-web-app --region us-east-1
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
   docker buildx build --platform linux/arm64 -t my-web-app .
   docker tag my-web-app:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/my-web-app:latest
   docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/my-web-app:latest
   ```
2. Create an ECS task definition (Fargate, Linux/ARM64, 0.25 vCPU / 0.5GB, container port 8675)
   pointing at that image.
3. Create an ECS Service (desired count 1) on an existing cluster using that task definition,
   with a security group allowing inbound TCP 8675 from 0.0.0.0/0 and a public IP assigned.
4. Visit `http://<task-public-ip>:8675`.

### Part 2, Agentic AI demo
```
python agents_demo.py --title "Organic Baby Spinach Recall" --content "Routine testing detected Listeria in lot #L4471. Affected bags were sold in California and Nevada stores."
```
Prints Planner output, Reviewer output, Finalized output, and the final Publish package as JSON.

### Part 3, Measuring non-determinism
```
python run_nondeterminism.py
```
Runs the fixed input in `reports/hw01/cases/nondeterminism_input.json` 20 times at temperature 0.7
and 20 times at temperature 0.0, writing `reports/hw01/raw/nondeterminism_raw.json` and
`reports/hw01/METRICS.md`.

### Part 4, Model client & token accounting
```
python hw1_client.py
```
Interactive CLI. Type messages to chat, `/stats` to see cumulative token counts and turn count,
`/exit` to quit and print final totals.

### Self-check
```
python3 scripts/verify_hw01.py
```
Runs static checks against the required files/content and writes `reports/hw01/verification.json`.

## Part 4, Conceptual answers

**(i) Why is prior conversation context resent with every turn?**
The model has no memory between calls on its own, so the client has to resend the whole
conversation so far every single time, or it would have no idea what was said earlier. This shows
up directly in the numbers: input tokens went 147, then 243, 368, 496, 636 across the five turns,
climbing every time even though each new message I typed was short. That climb is just the growing
history getting resent each turn, not longer messages on my end.

**(ii) How is a system prompt different from a user message?**
The system prompt, the bullet-only instruction from AGENT.md in this case, gets set once and holds
for the entire conversation. That's why all 5 responses came back as strictly bullet points. A user
message is just whatever got typed in one specific turn, five separate one-off messages here.

**(iii) Why do input tokens grow over a conversation?**
Same root cause as (i). The full history gets resent every turn, and that history keeps getting
longer, so input tokens climb right along with it. By turn 5 it had gone from 147 up to 636 tokens,
over 4x, and none of that came from longer messages, just accumulated history.

**(iv) What eventually limits that growth?**
Every model has a context window, a hard limit on tokens it can hold at once. So this can't keep
going forever. Once a conversation gets close to that ceiling, older messages have to get dropped,
summarized, or truncated to keep it going.

---

# DATA-260 HW2, Pinal Pawar (SID4: 7875)

GitHub repository: https://github.com/PinalPawar/data260-7875 (this repository, extended from HW1).
Tagged commit: see the `hw2` tag on this repository.
Hardware: MacBook Air, Apple M2, 16GB RAM (same machine as HW1).
Local model: HW1 used qwen3:8b via Ollama. For HW2 Part 3 and Part 4, qwen3:1.7b was used instead
as a documented substitute (see `reports/hw02/report.pdf`, Section 0, for the full reasoning).

## HW2 Reproducible run instructions

### Prerequisites
- Everything listed above for HW1, plus:
- Python deps: `pip install fastapi "uvicorn[standard]" pydantic langgraph` (see `requirements.txt`
  for the pinned FastAPI/uvicorn/pydantic versions)

### Part 1, Responsive UI with loading/empty/error states
Open `index.html` (served by the Part 2 FastAPI app below) and resize the browser to 375px width,
or use browser devtools' device toolbar, to see the responsive layout and the loading, empty, and
error states.

### Part 2, FastAPI backend
```
python3 main.py
```
Starts the FastAPI app on `PORT_BASE` (8675) and serves `index.html` plus the `/api/notices` CRUD
and search endpoints. Visit `http://localhost:8675` in a browser.

### Part 3, Stateful supervisor graph
```
python3 graph_agent.py --title "Organic Baby Spinach Recall" --content "Routine testing detected Listeria in lot #L4471. Affected bags were sold in California and Nevada stores." --llm qwen3:1.7b
```
Streams Planner -> Supervisor -> Reviewer -> Supervisor node-by-node output and prints the final
published state. Add `--strict` to enable strict mode. A saved example run is in
`reports/hw02/part3_run_log.txt`.

### Part 4, Output schema validation and loop safety
```
python3 run_experiment1.py   # 30 runs on the fixed input in reports/hw02/cases/schema_input.json
python3 run_experiment2.py   # 20 runs each at turn_ceiling=2 and turn_ceiling=10
python3 run_experiment3.py   # 5 runs on an adversarial input
python3 natural_retry_test.py  # single run demonstrating an unforced validation retry
```
Each experiment script writes its raw results to `reports/hw02/raw/`. `schema_agent.py` defines the
Pydantic schema (`PlannerOutputSchema`), the validator node, and the schema-aware graph
(`build_graph_v2`) used by all four scripts above.

### Self-check
```
python3 scripts/verify_hw02.py
```
Runs static checks against the required HW2 files/content and writes `reports/hw02/verification.json`.
