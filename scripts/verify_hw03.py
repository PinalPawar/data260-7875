#!/usr/bin/env python3
"""
Self-check script for DATA-260 HW3.
Run: python3 scripts/verify_hw03.py
Writes results to reports/hw03/verification.json and prints a summary.
Checks are static/file-based (no server or embedding model needs to be
running to run this script), same approach as scripts/verify_hw01.py and
scripts/verify_hw02.py.
"""
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Section 0 config values (fixed, from SID4 = 7875) ---
SID4 = "7875"
PORT_BASE = 8675
PREFIX = "s7875"
SEED = 7875
VERIFY_SEED = 267875
DOMAIN_ID = 3  # Grocery supply and recall notices
MODEL_USED = "sentence-transformers/all-MiniLM-L6-v2 (HuggingFace embedding model, Part 2)"
# Fill this in with the real tagged commit hash from GitHub once you've
# created the hw3 tag for this submission.
COMMIT_HASH = "TODO_PASTE_TAGGED_COMMIT_HASH_HERE"


def p(*parts):
    return os.path.join(ROOT, *parts)


checks = []


def check(name, condition, detail=""):
    checks.append({"name": name, "passed": bool(condition), "detail": detail})


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# --- Required files exist ------------------------------------------------
required_files = [
    "main.py",
    "routers/auth.py",
    "templates/home.html",
    "templates/login.html",
    "templates/dashboard.html",
    "retrieval_pipeline.py",
    "questions.yaml",
    "SOURCES.md",
    "CORPUS_MANIFEST.json",
    "scripts/fetch_corpus.py",
    "scripts/summarize_metrics.py",
    "reports/hw03/METRICS.md",
    "reports/hw03/RUN_LOG.txt",
    "reports/hw03/AI_USE.md",
    "reports/hw03/raw/retrieval_results.csv",
    "reports/hw03/raw/retrieval_results.jsonl",
    "reports/hw03/raw/chunk_stats.json",
]
for rel in required_files:
    exists = os.path.isfile(p(rel))
    check(f"file_exists:{rel}", exists)

# --- Part 1: auth.py / session checks ------------------------------------
try:
    auth_src = read(p("routers/auth.py"))
    check("auth_has_home_route", '@router.get("/")' in auth_src)
    check("auth_has_login_get_route", '@router.get("/login")' in auth_src)
    check("auth_has_login_post_route", '@router.post("/login")' in auth_src)
    check("auth_has_dashboard_route", '@router.get("/dashboard")' in auth_src)
    check("auth_has_logout_route", '@router.get("/logout")' in auth_src)
    check("auth_has_idle_timeout", "IDLE_TIMEOUT_SECONDS" in auth_src)
    check("auth_has_revocation_list", "REVOKED_SIDS" in auth_src, "server-side blocklist proving logout/expiry can't be replayed")
except FileNotFoundError:
    check("auth_py_readable", False)

try:
    main_src = read(p("main.py"))
    check("main_has_session_middleware", "SessionMiddleware" in main_src)
    check("main_session_is_https_only", "https_only=True" in main_src)
    check("main_session_is_same_site", "same_site=" in main_src)
    check("main_includes_auth_router", "include_router(auth_router)" in main_src)
    check("main_keeps_existing_notices_api", '@app.get("/api/notices"' in main_src, "must extend, not replace, the existing codebase")
except FileNotFoundError:
    check("main_py_readable", False)

# --- Part 2: retrieval_pipeline.py checks ---------------------------------
try:
    pipe_src = read(p("retrieval_pipeline.py"))
    check("pipeline_uses_token_splitter", "TokenTextSplitter" in pipe_src)
    check("pipeline_uses_semantic_splitter", "SemanticSplitterNodeParser" in pipe_src)
    check("pipeline_uses_sentence_window", "SentenceWindowNodeParser" in pipe_src)
    check("pipeline_uses_vector_store_index", "VectorStoreIndex" in pipe_src)
    check("pipeline_uses_huggingface_embedding", "HuggingFaceEmbedding" in pipe_src)
    check("pipeline_computes_cosine_explicitly", "def cosine(" in pipe_src)
    check("pipeline_measures_latency", "latency_ms" in pipe_src)
    check("pipeline_saves_csv", ".csv" in pipe_src)
    check("pipeline_saves_jsonl", ".jsonl" in pipe_src)
except FileNotFoundError:
    check("retrieval_pipeline_py_readable", False)

# --- questions.yaml: 5+ questions, >=2 single-source-dependent -----------
try:
    import yaml

    qdata = yaml.safe_load(read(p("questions.yaml")))["questions"]
    check("questions_at_least_5", len(qdata) >= 5, f"found {len(qdata)}")
    single_source = [q for q in qdata if q.get("single_source_dependent")]
    check("questions_at_least_2_single_source", len(single_source) >= 2, f"found {len(single_source)}")
    check("questions_have_expected_answers", all(q.get("expected_answer") for q in qdata))
except Exception as e:
    check("questions_yaml_valid", False, str(e))

# --- corpus size >= 200KB -------------------------------------------------
try:
    manifest = json.loads(read(p("CORPUS_MANIFEST.json")))
    total_bytes = sum(m["byte_size"] for m in manifest)
    check("corpus_at_least_200kb", total_bytes >= 200 * 1024, f"found {total_bytes} bytes ({total_bytes/1024:.1f} KB)")
    check("corpus_manifest_has_hashes", all("sha256" in m for m in manifest))
except Exception as e:
    check("corpus_manifest_valid", False, str(e))

# --- raw retrieval results: 3 techniques x 6 questions x k=5 rows --------
try:
    rows = [json.loads(line) for line in read(p("reports/hw03/raw/retrieval_results.jsonl")).splitlines() if line.strip()]
    techniques_seen = {r["technique"] for r in rows}
    check("raw_results_has_3_techniques", techniques_seen == {"token", "semantic", "sentence_window"}, f"found {techniques_seen}")
    check("raw_results_non_empty", len(rows) > 0)
except FileNotFoundError:
    check("raw_results_readable", False)
except Exception as e:
    check("raw_results_valid", False, str(e))

# --- METRICS.md / RUN_LOG.txt / AI_USE.md non-empty ----------------------
for rel in ["reports/hw03/METRICS.md", "reports/hw03/RUN_LOG.txt", "reports/hw03/AI_USE.md"]:
    try:
        content = read(p(rel))
        check(f"non_empty:{rel}", len(content.strip()) > 0)
    except FileNotFoundError:
        check(f"readable:{rel}", False)

# --- Summary ---------------------------------------------------------------
passed = sum(1 for c in checks if c["passed"])
total = len(checks)
result = {
    "homework": "HW3",
    "sid4": SID4,
    "port_base": PORT_BASE,
    "prefix": PREFIX,
    "domain_id": DOMAIN_ID,
    "commit_hash": COMMIT_HASH,
    "model_used": MODEL_USED,
    "seed": SEED,
    "verify_seed": VERIFY_SEED,
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "script": "scripts/verify_hw03.py",
    "summary": {"passed": passed, "total": total, "all_passed": passed == total},
    "checks": checks,
}

out_path = p("reports", "hw03", "verification.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)

print(f"Verification: {passed}/{total} checks passed.")
failed = [c for c in checks if not c["passed"]]
if failed:
    print("FAILED checks:")
    for c in failed:
        print(f"  - {c['name']}  {c['detail']}")
else:
    print("All checks passed.")
print(f"Wrote {out_path}")
sys.exit(0 if passed == total else 1)
