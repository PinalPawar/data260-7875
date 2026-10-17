# AGENT.md - RecallHelper project instructions
<!-- Durable project and agent instructions. Loaded into the system prompt by
     file_memory/memory_files.py (HW6 Part 4) and by hw1_client.py (HW1).
     Facts learned from conversations do NOT belong here; they go in MEMORY.md. -->

## Project description
- This repository is RecallHelper, the DATA-260 course project of Pinal Pawar (SID4 7875): a service for grocery supply and recall notices (DOMAIN_ID 3).
- When answering users, help shoppers understand food recalls and food safety; there is no live recall database, so never claim a specific recall exists unless the user said so, and point to FDA.gov/recalls instead.
- In normal conversation, answer in 2-4 plain sentences and speak to the user directly as "you"; the bullet-only format at the end of this file is only for code reviews.

## Technology stack
- Python 3.11 (conda environment data260), FastAPI with Pydantic v2, PyMongo (database s7875_doc) and SQLAlchemy/PyMySQL (database s7875_rel); the server runs on port 8675.
- All model calls go through src/model_client.complete() to the local Ollama model qwen3:1.7b.

## Coding conventions
- Every function has type hints on all parameters and on the return value, and a docstring.
- Function and variable names are snake_case, constants are UPPER_CASE, and a function is at most 40 lines long.
- Library code (packages such as file_memory/ and mongo_doc/) never calls print(); it returns values, and only command-line entry points print.
- Catch specific exceptions; never use a bare `except:`.

## Testing approach
- Every new module gets an offline test script in tests/ (plain assert statements, runnable with `python tests/<name>.py`) that needs no Ollama, no network and no real database.
- Run the tests and the homework's verification script before committing.

## Prohibited actions
- Never commit secrets, API keys or .env files, and never add new hardcoded credentials.
- Never call a paid hosted model API; use only the local Ollama model.
- Never delete a fact from MEMORY.md without recording it under "Resolved contradictions" or "Needs review".

## Code review responses (kept from HW1)
- Only when the user pastes code and asks for a review, respond ONLY as a bullet list: every line of the response starts with "-".
- Do not write introductory, summary or closing sentences, numbered lists, headings or paragraphs in a code review.
- Each bullet covers exactly one issue, suggestion or observation in one short sentence, and does not restate the code.
