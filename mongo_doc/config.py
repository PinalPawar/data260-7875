"""HW6 Part 1 - server configuration for the MongoDB document API.

Values come from environment variables (or .env) so nothing is hardcoded
for a real deployment. Defaults match the local Docker MongoDB used for HW6.
"""
import os

from dotenv import load_dotenv

load_dotenv()

SID4 = 7875
PREFIX = f"s{SID4}"            # s7875
PORT_BASE = 8000 + (SID4 % 900)  # 8675

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", f"{PREFIX}_doc")  # s7875_doc
NOTICES_COLLECTION = "recall_notices"

# --- HW6 Part 2: chat memory (same database, three new collections) --------
MESSAGES_COLLECTION = "messages"
SUMMARIES_COLLECTION = "summaries"
EPISODES_COLLECTION = "episodes"

# Short-term memory: how many previous messages (user + assistant) go into
# the prompt. Part 3 sweeps this over 4 / 12 / 30.
SHORT_TERM_N = int(os.getenv("SHORT_TERM_N", "12"))
# Long-term memory: write a session summary every M user messages...
SUMMARIZE_EVERY_USER_MSGS = int(os.getenv("SUMMARIZE_EVERY_USER_MSGS", "4"))
# ...and condense session summaries into a lifetime summary every K of them.
LIFETIME_EVERY_SESSION_SUMMARIES = int(os.getenv("LIFETIME_EVERY_SESSION_SUMMARIES", "2"))
# Episodic memory: facts per message and how many to retrieve per turn.
MAX_FACTS_PER_MESSAGE = 3
EPISODIC_TOP_K = int(os.getenv("EPISODIC_TOP_K", "3"))
# A new fact this similar to a stored one is treated as a duplicate.
EPISODE_DUPLICATE_SIMILARITY = 0.92

# Local model through the HW1 adapter (src/model_client.py) and the same
# embedding model used for retrieval in HW3/HW4.
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen3:1.7b")
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# --- HW6 Part 3: measurement ----------------------------------------------
SEED = SID4                      # passed to Ollama so runs are reproducible
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))   # Ollama's default 4096 could truncate N=30
# Tokenizer of the chat model, used to count tokens per prompt part.
TOKENIZER_NAME = os.getenv("TOKENIZER_NAME", "Qwen/Qwen3-1.7B")
# Every /api/chat request is appended here as one JSON line.
CHAT_LOG_PATH = os.getenv("CHAT_LOG_PATH", "reports/hw06/raw/chat_requests.jsonl")
# Compression policy: assistant turns in the short-term window are cut to
# their first sentence, at most this many words.
COMPRESS_MAX_WORDS = 25

# Calendar days for GET /api/aggregate are counted in this time zone.
AGGREGATE_TIMEZONE = os.getenv("AGGREGATE_TIMEZONE", "America/Los_Angeles")
