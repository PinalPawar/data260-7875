# How to run this app (Part 1) and the retrieval pipeline (Part 2)

## Requirements
- Python 3.11 (this was built and tested with a conda env named `data260`)
- Install dependencies once:
  ```
  pip install -r requirements.txt
  ```

## Part 1 — run the FastAPI app

From the repo root (`data260-7875/`):

```
python3 main.py
```

This starts the server at `http://127.0.0.1:8675` (PORT_BASE 8000 + SID4 mod 900,
for SID4=7875 that's 8675). You should see:

```
INFO:     Uvicorn running on http://0.0.0.0:8675 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

Then open `http://127.0.0.1:8675/` in a browser. Demo login is
username `admin`, password `password` (overridable via the `DEMO_USERNAME` /
`DEMO_PASSWORD` environment variables — see `routers/auth.py`).

To demo the idle timeout quickly instead of waiting the default 5 minutes,
restart the server with a short override, e.g.:

```
IDLE_TIMEOUT_SECONDS=15 python3 main.py
```

Stop the server with `Ctrl+C`.

## Part 2 — run the chunking/retrieval pipeline

From the repo root, with the same environment active:

```
python3 retrieval_pipeline.py
```

This reads the local corpus in `corpus/`, builds three sets of chunks
(Token / Semantic / Sentence-window), embeds them with
`sentence-transformers/all-MiniLM-L6-v2`, runs the questions in
`questions.yaml` against each technique, and writes the raw results to
`reports/hw03/raw/` (`retrieval_results.csv`, `retrieval_results.jsonl`,
`chunk_stats.json`).

## Verifying everything is in place

```
python3 scripts/verify_hw03.py
```

This checks that the expected files, corpus size, and report sections all
exist and prints a pass/fail count.
