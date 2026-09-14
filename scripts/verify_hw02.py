
#!/usr/bin/env python3
"""
Self-check script for DATA-260 HW2.
Run: python3 scripts/verify_hw02.py
Writes results to reports/hw02/verification.json and prints a summary.
Checks are static/file-based (no Docker/Ollama required to run this script),
same approach as scripts/verify_hw01.py.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
 
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
 
# --- Section 0 config values (fixed, from SID4 = 7875) ---
SID4 = "7875"
SEED = 7875
VERIFY_SEED = 267875
MODEL_USED = "qwen3:1.7b (documented substitute for qwen3:8b)"
# Fill this in with the real tagged commit hash from GitHub once you've
# created the release/tag for this submission.
COMMIT_HASH = "TODO_PASTE_TAGGED_COMMIT_HASH_HERE"
 
def p(*parts):
    return os.path.join(ROOT, *parts)
 
checks = []
 
def check(name, condition, detail=""):
    checks.append({"name": name, "passed": bool(condition), "detail": detail})
 
def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
 
# --- Required files exist ---
required_files = [
    "index.html", "main.py", "graph_agent.py", "schema_agent.py",
    "run_experiment1.py", "run_experiment2.py", "run_experiment3.py",
    "natural_retry_test.py", "agents_demo.py", "src/model_client.py",
    "reports/hw02/METRICS.md", "reports/hw02/RUN_LOG.txt",
    "reports/hw02/AI_USE.md",
    "reports/hw02/cases/schema_input.json",
    "reports/hw02/cases/adversarial_input.json",
    "reports/hw02/cases/adversarial_input_v2.json",
    "reports/hw02/cases/adversarial_input_v3.json",
    "reports/hw02/raw/experiment1_raw.json",
    "reports/hw02/raw/experiment2_raw.json",
    "reports/hw02/raw/natural_retry_example.txt",
]
for rel in required_files:
    exists = os.path.isfile(p(rel))
    check(f"file_exists:{rel}", exists)
 
# --- Part 1: index.html responsive / state checks ---
try:
    html = read(p("index.html"))
    check("html_has_viewport_meta", "width=device-width" in html)
    check("html_has_render_notices_function", "renderNotices" in html)
except FileNotFoundError:
    check("html_readable", False)
 
# --- Part 2: main.py FastAPI checks ---
try:
    main_src = read(p("main.py"))
    check("main_defines_fastapi_app", "FastAPI(" in main_src)
    check("main_runs_on_port_base_8675", "8675" in main_src)
    check("main_has_add_route", "@app.post" in main_src)
    check("main_has_update_route", "@app.put" in main_src)
    check("main_has_delete_highest_route", "@app.delete" in main_src and "highest" in main_src)
    check("main_has_search_route", "@app.get(\"/api/notices\"" in main_src and "q:" in main_src)
except FileNotFoundError:
    check("main_py_readable", False)
 
# --- Part 3: graph_agent.py (supervisor pattern) checks ---
try:
    graph_src = read(p("graph_agent.py"))
    check("graph_defines_planner_node", "def planner_node(" in graph_src)
    check("graph_defines_reviewer_node", "def reviewer_node(" in graph_src)
    check("graph_defines_supervisor_node", "def supervisor_node(" in graph_src)
    check("graph_defines_router_logic", "def router_logic(" in graph_src)
    check("graph_defines_build_graph", "def build_graph(" in graph_src)
    check("graph_planner_clears_stale_feedback", '"reviewer_feedback": None' in graph_src,
          "planner_node must reset reviewer_feedback on every new proposal (the bug fixed during testing)")
    check("graph_uses_model_client_complete", "from src.model_client import complete" in graph_src)
except FileNotFoundError:
    check("graph_agent_py_readable", False)
 
# --- Part 4: schema_agent.py (Pydantic schema + retry loop) checks ---
try:
    schema_src = read(p("schema_agent.py"))
    check("schema_defines_output_schema", "class PlannerOutputSchema" in schema_src)
    check("schema_checks_exactly_3_tags", "exactly 3 tags" in schema_src)
    check("schema_checks_tag_length_3_30", "3-30 characters" in schema_src)
    check("schema_checks_summary_25_words", "25 words" in schema_src)
    check("schema_defines_validate_output", "def validate_output(" in schema_src)
    check("schema_defines_planner_node_v2", "def planner_node_v2(" in schema_src)
    check("schema_defines_validator_node", "def validator_node(" in schema_src)
    check("schema_defines_router_logic_v2", "def router_logic_v2(" in schema_src)
    check("schema_defines_build_graph_v2", "def build_graph_v2(" in schema_src)
except FileNotFoundError:
    check("schema_agent_py_readable", False)
 
# --- Experiment 1: 30 runs, each result has exactly 3 tags where present ---
try:
    exp1 = json.load(open(p("reports/hw02/raw/experiment1_raw.json")))
    check("experiment1_raw_is_list", isinstance(exp1, list))
    check("experiment1_raw_has_30_runs", len(exp1) == 30, f"found {len(exp1)} runs")
except Exception as e:
    check("experiment1_raw_valid_json", False, str(e))
 
# --- Experiment 2: 20 runs x 2 ceilings = 40 total ---
try:
    exp2 = json.load(open(p("reports/hw02/raw/experiment2_raw.json")))
    check("experiment2_raw_is_list", isinstance(exp2, list))
    check("experiment2_raw_has_40_runs", len(exp2) == 40, f"found {len(exp2)} runs")
except Exception as e:
    check("experiment2_raw_valid_json", False, str(e))
 
# --- Experiment 3, Attempt 3: the real, unforced retry-and-recover ---
try:
    natural_retry = read(p("reports/hw02/raw/natural_retry_example.txt"))
    check("natural_retry_log_non_empty", len(natural_retry.strip()) > 0)
    check("natural_retry_shows_validation_failure", "3-30 characters long, got 2" in natural_retry)
    check("natural_retry_shows_successful_recovery", '"turn_count": 2' in natural_retry)
except FileNotFoundError:
    check("natural_retry_example_readable", False)
 
# --- METRICS.md / RUN_LOG.txt / AI_USE.md non-empty ---
for rel in ["reports/hw02/METRICS.md", "reports/hw02/RUN_LOG.txt", "reports/hw02/AI_USE.md"]:
    try:
        content = read(p(rel))
        check(f"non_empty:{rel}", len(content.strip()) > 0)
    except FileNotFoundError:
        check(f"readable:{rel}", False)
 
# --- Summary ---
passed = sum(1 for c in checks if c["passed"])
total = len(checks)
result = {
    "homework": "HW2",
    "sid4": SID4,
    "commit_hash": COMMIT_HASH,
    "model_used": MODEL_USED,
    "seed": SEED,
    "verify_seed": VERIFY_SEED,
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "script": "scripts/verify_hw02.py",
    "summary": {"passed": passed, "total": total, "all_passed": passed == total},
    "checks": checks,
}
 
out_path = p("reports", "hw02", "verification.json")
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
