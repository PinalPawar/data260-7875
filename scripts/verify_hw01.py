#!/usr/bin/env python3
"""
Self-check script for DATA-260 HW1.
Run: python3 scripts/verify_hw01.py
Writes results to reports/hw01/verification.json and prints a summary.
Checks are static/file-based (no Docker/Ollama required to run this script).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    "index.html", "DOMAIN_SCHEMA.md", "Dockerfile", "nginx.conf",
    "agents_demo.py", "hw1_client.py", "AGENT.md", "src/model_client.py",
    "reports/hw01/METRICS.md", "reports/hw01/RUN_LOG.txt",
    "reports/hw01/cases/nondeterminism_input.json",
    "reports/hw01/raw/nondeterminism_raw.json",
    "reports/hw01/AI_USE.md",
]
for rel in required_files:
    exists = os.path.isfile(p(rel))
    check(f"file_exists:{rel}", exists)

# --- index.html checks (Part 1 HTML/JS) ---
try:
    html = read(p("index.html"))
    check("html_has_autofocus", "autofocus" in html)
    check("html_required_field_count_gte_4", len(re.findall(r"\brequired\b", html)) >= 4,
          f"found {len(re.findall(chr(92)+'brequired'+chr(92)+'b', html))} 'required' attributes")
    check("html_has_checkbox", 'type="checkbox"' in html)
    option_count = len(re.findall(r"<option value=\"\w", html))
    check("html_has_4_category_options", option_count == 4, f"found {option_count} non-placeholder options")
    check("html_has_script_tag", "<script" in html)
    check("html_title_starts_HW1", "<title>HW1-" in html)
except FileNotFoundError:
    check("html_readable", False)

# --- JS behavior checks (validation, JSON, destructuring, spread, closure) ---
try:
    check("js_has_25char_validation", "25" in html and "length" in html)
    check("js_has_checkbox_validation", "agreeTerms" in html and "checked" in html)
    check("js_has_json_stringify", "JSON.stringify" in html)
    check("js_has_destructuring", re.search(r"const\s*\{[^}]+\}\s*=", html) is not None)
    check("js_has_spread_operator", "..." in html)
    check("js_has_closure_counter", "createCounter" in html or "closure" in html.lower())
except NameError:
    pass

# --- Dockerfile / nginx checks ---
try:
    dockerfile = read(p("Dockerfile"))
    check("dockerfile_from_nginx", "nginx" in dockerfile.lower())
    check("dockerfile_exposes_8675", "8675" in dockerfile)
except FileNotFoundError:
    check("dockerfile_readable", False)

try:
    nginx_conf = read(p("nginx.conf"))
    check("nginx_listens_8675", "8675" in nginx_conf)
except FileNotFoundError:
    check("nginx_conf_readable", False)

# --- agents_demo.py checks (Part 2) ---
try:
    agents_src = read(p("agents_demo.py")).lower()
    check("agents_has_planner", "planner" in agents_src)
    check("agents_has_reviewer", "reviewer" in agents_src)
    check("agents_has_finalizer", "finalizer" in agents_src or "finaliz" in agents_src)
    check("agents_uses_json_output", "json" in agents_src)
except FileNotFoundError:
    check("agents_demo_readable", False)

# --- model_client.py checks (Part 4) ---
try:
    model_client_src = read(p("src/model_client.py"))
    check("model_client_defines_complete", re.search(r"def\s+complete\s*\(", model_client_src) is not None)
    check("model_client_accepts_messages_tools", "messages" in model_client_src and "tools" in model_client_src)
except FileNotFoundError:
    check("model_client_readable", False)

# --- AGENT.md checks ---
try:
    agent_md = read(p("AGENT.md")).lower()
    check("agentmd_requests_bullets", "bullet" in agent_md)
except FileNotFoundError:
    check("agent_md_readable", False)

# --- Part 3 non-determinism data checks ---
try:
    fixed_input = json.load(open(p("reports/hw01/cases/nondeterminism_input.json")))
    check("nondeterminism_input_has_title_content", "title" in fixed_input and "content" in fixed_input)
except Exception as e:
    check("nondeterminism_input_valid_json", False, str(e))

try:
    raw = json.load(open(p("reports/hw01/raw/nondeterminism_raw.json")))
    check("nondeterminism_raw_is_list", isinstance(raw, list))
    check("nondeterminism_raw_has_40_runs", len(raw) == 40, f"found {len(raw)} runs")
    n_07 = sum(1 for r in raw if abs(r.get("temperature", -1) - 0.7) < 1e-6)
    n_00 = sum(1 for r in raw if abs(r.get("temperature", -1) - 0.0) < 1e-6)
    check("nondeterminism_raw_20_runs_temp_0.7", n_07 == 20, f"found {n_07}")
    check("nondeterminism_raw_20_runs_temp_0.0", n_00 == 20, f"found {n_00}")
    check("nondeterminism_raw_has_tags_and_latency", all(("tags" in r and "latency_ms" in r) for r in raw))
except Exception as e:
    check("nondeterminism_raw_valid_json", False, str(e))

# --- METRICS.md / RUN_LOG.txt non-empty ---
try:
    metrics = read(p("reports/hw01/METRICS.md"))
    check("metrics_md_non_empty", len(metrics.strip()) > 0)
    check("metrics_md_has_distinct_tag_sets", "distinct tag set" in metrics.lower())
except FileNotFoundError:
    check("metrics_md_readable", False)

try:
    run_log = read(p("reports/hw01/RUN_LOG.txt"))
    check("run_log_non_empty", len(run_log.strip()) > 0)
except FileNotFoundError:
    check("run_log_readable", False)

# --- Summary ---
passed = sum(1 for c in checks if c["passed"])
total = len(checks)
result = {
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "script": "scripts/verify_hw01.py",
    "summary": {"passed": passed, "total": total, "all_passed": passed == total},
    "checks": checks,
}

out_path = p("reports", "hw01", "verification.json")
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
