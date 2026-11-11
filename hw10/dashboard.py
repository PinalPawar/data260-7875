"""HW10 Part 1: Streamlit operations dashboard for the HW8/HW9 RecallHelper pipeline.

    streamlit run hw10/dashboard.py --server.port 8676

Pages (sidebar): Summary (1.1), Evaluation (1.2), Trace lookup (1.3). Read-only: everything
comes from my own logs in reports/hw10/raw/ (spans.jsonl, requests.jsonl, eval_results.jsonl,
part3_judge_*.json/csv, part4_latency_summary.json, trace_examples.json) plus a live count of
cache entries from Redis.
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import hw10cfg as cfg  # noqa: E402
from trace_analysis import journey, load_jsonl, percentile  # noqa: E402

st.set_page_config(page_title="s7875 RecallHelper ops", layout="wide")
WINDOWS = {"Last 1 hour": timedelta(hours=1), "Last 24 hours": timedelta(days=1),
           "Last 7 days": timedelta(days=7), "All time": None}


@st.cache_data(ttl=10, show_spinner=False)
def load_file(path: str, mtime: float) -> list[dict]:
    """JSONL rows; cached per (path, mtime) so reruns do not re-parse unchanged files."""
    return load_jsonl(Path(path))


def rows(path: Path) -> list[dict]:
    """Cached load keyed on the file's modification time."""
    return load_file(str(path), path.stat().st_mtime if path.exists() else 0.0)


@st.cache_data(ttl=30, show_spinner=False)
def load_json(path: str, mtime: float) -> dict | None:
    """A JSON file (None if missing)."""
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def jfile(path: Path) -> dict | None:
    """Cached JSON load keyed on mtime."""
    return load_json(str(path), path.stat().st_mtime if path.exists() else 0.0)


@st.cache_resource(show_spinner=False)
def redis_client():
    """One Redis connection for the whole app session (expensive, reusable resource)."""
    try:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True,
                                 socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:  # noqa: BLE001 - dashboard must still render without Redis
        return None


def header() -> str:
    """Sidebar: identity, page picker, refresh."""
    st.sidebar.markdown(f"**{cfg.STUDENT_NAME}** · SID4 {cfg.SID4} · PREFIX `{cfg.PREFIX}`")
    page = st.sidebar.radio("Page", ["Summary", "Evaluation", "Trace lookup"])
    if st.sidebar.button("Refresh data"):
        st.cache_data.clear()
    st.sidebar.caption(f"Data folder: reports/hw10/raw/ · loaded {time.strftime('%H:%M:%S')}")
    return page


def in_window(reqs: list[dict], win: timedelta | None) -> list[dict]:
    """Requests whose ts falls inside the chosen window."""
    if win is None:
        return reqs
    cut = datetime.now().astimezone() - win
    return [r for r in reqs if datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%S%z") >= cut]


def summary_page() -> None:
    """Part 1.1: request count, cache hit/miss, error rate, latency - each with its source."""
    st.title("Summary")
    wname = st.selectbox("Time window", list(WINDOWS), index=3)
    reqs = in_window(rows(cfg.REQUESTS), WINDOWS[wname])
    src = ("Source: `reports/hw10/raw/requests.jsonl` (one row per request, written by "
           f"`hw10/ingress.py`). Window: **{wname}**")
    if reqs:
        src += f" - {len(reqs)} rows from {reqs[0]['ts']} to {reqs[-1]['ts']}."
    if not reqs:
        st.info("No requests in this window yet.")
        return
    hits = [r for r in reqs if r["is_cached"]]
    miss = [r for r in reqs if not r["is_cached"]]
    errs = [r for r in reqs if r["status"] != "ok"]
    c = st.columns(4)
    c[0].metric("Recent requests", len(reqs))
    c[1].metric("Cache hit rate", f"{100 * len(hits) / len(reqs):.1f}%",
                help="hits / all requests")
    c[2].metric("Error rate", f"{100 * len(errs) / len(reqs):.1f}%",
                help="status != ok (dead-lettered or timed out) / all requests")
    c[3].metric("Cache entries (live Redis)", _cache_entries())
    st.caption(src)
    c = st.columns(2)
    c[0].markdown(f"**Cache hits: {len(hits)}**  |  **Cache misses: {len(miss)}**")
    c[0].altair_chart(alt.Chart(pd.DataFrame({"path": ["cache hit", "cache miss"],
                                              "requests": [len(hits), len(miss)]}))
                      .mark_bar().encode(x="path", y="requests",
                                         color=alt.Color("path", scale=alt.Scale(
                                             range=["#2e7d32", "#1565c0"]), legend=None)),
                      use_container_width=True)
    c[1].markdown("**End-to-end latency (ms)** - hits and misses kept separate")
    lat = pd.DataFrame([_lat("cache hit", hits), _lat("cache miss (ok)",
                                                      [r for r in miss if r["status"] == "ok"])])
    c[1].dataframe(lat, hide_index=True, use_container_width=True)
    c[1].caption("e2e_ms = ingress start to response (misses include the evaluator when it "
                 f"ran). {src}")
    _stage_table()
    with st.expander(f"Errors in this window ({len(errs)})"):
        cols = ["ts", "trace_id", "failed_stage", "error"]
        st.dataframe(pd.DataFrame([{k: r.get(k) for k in cols} for r in errs], columns=cols),
                     hide_index=True, use_container_width=True)


def _lat(name: str, rs: list[dict]) -> dict:
    """p50/p95/mean of e2e_ms for a group of requests."""
    xs = [r["e2e_ms"] for r in rs]
    return {"path": name, "n": len(xs), "p50": percentile(xs, 50), "p95": percentile(xs, 95),
            "mean": round(sum(xs) / len(xs), 1) if xs else None}


def _cache_entries() -> str:
    """Number of semantic-cache entries in Redis (or 'n/a' when Redis is down)."""
    r = redis_client()
    if r is None:
        return "n/a"
    return str(sum(1 for _ in r.scan_iter(f"{cfg.PREFIX}:{cfg.CACHE_NAMESPACE}:entry:*")))


def _stage_table() -> None:
    """Part 4.3 table (50 confirmed cache misses), if the experiment has run."""
    tab = jfile(cfg.LATENCY_SUMMARY)
    st.subheader("Stage latency - 50 confirmed cache misses (Part 4.3)")
    if not tab:
        st.info("Run `python hw10/latency_experiment.py` to fill this table.")
        return
    df = pd.DataFrame(tab["rows"]).rename(columns={"stage": "Stage", "p50_ms": "p50 (ms)",
                                                   "p95_ms": "p95 (ms)",
                                                   "pct_of_e2e": "% of cache-miss e2e"})
    st.dataframe(df, hide_index=True, use_container_width=True)
    e, h = tab["end_to_end"], tab["cache_hit_e2e"]
    st.markdown(f"Cache-miss end-to-end p50 **{e['p50_ms']} ms**, p95 **{e['p95_ms']} ms** "
                f"(n={tab['n_traces']}). Dominant: **{tab['dominant']}**. "
                f"Cache-hit end-to-end (separate metric): p50 **{h['p50_ms']} ms**, "
                f"p95 **{h['p95_ms']} ms** (n={h['n']}).")
    st.caption("Source: `reports/hw10/raw/part4_latency_summary.json`, computed from "
               "`spans.jsonl` by `hw10/latency_experiment.py`. Window: the 50-request run.")


def eval_frame(evals: list[dict]) -> pd.DataFrame:
    """One row per evaluated trace: scores by pipeline stage + improvement."""
    out = []
    for e in evals:
        sc = e.get("scores") or {}
        imp = sc.get("improvement") or {}
        out.append({"trace_id": e["trace_id"], "evaluated_at": e["evaluated_at"],
                    "status": e["status"], "question": (e["inputs"] or {}).get("question"),
                    "Planner: plan quality": (sc.get("plan_quality") or {}).get("score_1_5"),
                    "Writer: helpfulness": (sc.get("writer_helpfulness") or {}).get("score_1_5"),
                    "Reviewer final: helpfulness": imp.get("final_score"),
                    "Draft (same metric)": imp.get("draft_score"),
                    "Final - draft": imp.get("difference"),
                    "reviewer verdict": (e["inputs"] or {}).get("final_status")})
    return pd.DataFrame(out)


def evaluation_page() -> None:
    """Part 1.2: Part 2 scores by stage and case, Part 3 judge validation, interpretation."""
    st.title("Evaluation")
    evals = rows(cfg.EVAL_RESULTS)
    st.subheader("Part 2 - pipeline evaluation (GEval, local judge, 1-5)")
    if not evals:
        st.info("No evaluations yet - run `python hw10/ingress.py --examples`.")
    else:
        df = eval_frame(evals)
        st.caption(f"Source: `reports/hw10/raw/eval_results.jsonl` ({len(df)} evaluated traces). "
                   f"Judge: {evals[-1]['judge']['judge_model']}.")
        stage_cols = ["Planner: plan quality", "Writer: helpfulness",
                      "Reviewer final: helpfulness"]
        means = df[stage_cols].mean().round(2).reset_index()
        means.columns = ["stage", "mean score"]
        c = st.columns([1, 2])
        c[0].dataframe(means, hide_index=True, use_container_width=True)
        c[1].altair_chart(alt.Chart(means).mark_bar().encode(
            x=alt.X("mean score", scale=alt.Scale(domain=[0, 5])),
            y=alt.Y("stage", sort=None, axis=alt.Axis(labelLimit=260))),
            use_container_width=True)
        st.dataframe(df, hide_index=True, use_container_width=True)
        _eval_detail(evals)
    _judge_validation()
    st.subheader("Interpretation - Planner, Writer and Reviewer coordination")
    if cfg.INTERPRETATION.exists():
        st.markdown(cfg.INTERPRETATION.read_text())
    else:
        st.info("Write reports/hw10/interpretation.md after reading the results.")


def _eval_detail(evals: list[dict]) -> None:
    """Pick one evaluated trace and show inputs, scores and reasons."""
    ids = [e["trace_id"] for e in evals]
    pick = st.selectbox("Show details for trace", ids, index=len(ids) - 1)
    e = next(x for x in evals if x["trace_id"] == pick)
    inp, sc = e["inputs"], e.get("scores") or {}
    st.markdown(f"**Question:** {inp.get('question')}")
    st.markdown("**Plan:**\n" + "\n".join(f"- {p}" for p in inp.get("plan") or []))
    st.markdown(f"**Draft:** {inp.get('draft')}")
    st.markdown(f"**Final ({inp.get('final_status')}):** {inp.get('final_answer')}  \n"
                f"_Reviewer:_ {inp.get('review')}")
    for k in ("plan_quality", "writer_helpfulness", "final_helpfulness"):
        v = sc.get(k) or {}
        st.markdown(f"- **{k}** = {v.get('score_1_5')} - {v.get('reason')}")
    imp = sc.get("improvement") or {}
    st.markdown(f"- **final vs draft**: draft {imp.get('draft_score')}, final "
                f"{imp.get('final_score')}, difference {imp.get('difference')} - "
                f"{imp.get('interpretation')}")


def _judge_validation() -> None:
    """Part 3 numbers + raw per-case data."""
    st.subheader("Part 3 - judge validation against my human labels")
    s = jfile(cfg.JUDGE_SUMMARY)
    if not s:
        st.info("Run `python hw10/validate_judge.py` after committing the frozen files.")
        return
    h, rep = s["headline"], s["repeatability"]
    c = st.columns(4)
    c[0].metric("Spearman rho (run 1)", h["spearman"])
    c[1].metric("Mean |human - judge|", h["mean_abs_diff"])
    c[2].metric("Cases changed over 3 runs", f"{rep['cases_changed']}/{rep['cases']}")
    c[3].metric("Max |change|", rep["max_abs_change"])
    st.caption(f"n = {s['n_cases']} frozen drafts, frozen in commit "
               f"`{s['frozen']['commit'][:10]}` ({s['frozen']['committed_at']}); "
               f"mean pairwise change {rep['pairwise_mean_abs_change']}. Source: "
               "`reports/hw10/raw/part3_judge_summary.json`, `part3_judge_runs.csv`.")
    st.dataframe(pd.DataFrame(s["per_run"]), hide_index=True, use_container_width=True)
    if cfg.JUDGE_RUNS.exists():
        raw = pd.read_csv(cfg.JUDGE_RUNS)
        c = st.columns([1, 1])
        c[0].altair_chart(alt.Chart(raw).mark_circle(size=90, opacity=0.6).encode(
            x=alt.X("human_label:Q", scale=alt.Scale(domain=[0.5, 5.5])),
            y=alt.Y("judge_run1:Q", scale=alt.Scale(domain=[0.5, 5.5])),
            tooltip=["case_id", "human_label", "judge_run1", "question"]),
            use_container_width=True)
        c[1].dataframe(raw.drop(columns=["reason_run1"]), hide_index=True,
                       use_container_width=True, height=330)


def path_of(spans: list[dict]) -> str:
    """'CACHE HIT', 'CACHE MISS' or 'FAILED (stage)' for one journey."""
    look = next((s for s in spans if s["stage"] == "cache_lookup"), None)
    bad = [s for s in spans if s["status"] != "ok" and s["stage"] not in ("request",)]
    if bad:
        return f"FAILED at {bad[0]['stage']}"
    if look and look["attrs"].get("result") == "hit":
        return "CACHE HIT"
    return "CACHE MISS"


def trace_page() -> None:
    """Part 1.3: full journey of one trace_id in stage order."""
    st.title("Trace lookup")
    ex = jfile(cfg.TRACE_EXAMPLES) or {}
    c = st.columns(3)
    for col, key, label in zip(c, ("cache_hit", "cache_miss", "failed"),
                               ("Example: cache hit", "Example: cache miss", "Example: failed")):
        if ex.get(key) and col.button(label, use_container_width=True):
            st.session_state["tid"] = ex[key]
    tid = st.text_input("trace_id (= HW8 correlation_id)", key="tid").strip()
    if not tid:
        st.caption("Paste a trace_id, or click an example. Source: `reports/hw10/raw/spans.jsonl`.")
        return
    spans = journey(rows(cfg.SPANS), tid)
    if not spans:
        st.error("No spans for this trace_id.")
        return
    path = path_of(spans)
    color = {"CACHE HIT": "green", "CACHE MISS": "blue"}.get(path, "red")
    st.markdown(f"### :{color}[{path}]")
    _journey_table(spans)
    _gantt(spans)
    req = next((r for r in rows(cfg.REQUESTS) if r["trace_id"] == tid), None)
    if req:
        st.markdown(f"**Question:** {req['question']}")
        st.markdown(f"**Answer ({req.get('final_status')}):** {req.get('answer')}")
        if req.get("error"):
            st.error(f"Failing stage: **{req.get('failed_stage')}** - {req['error']}")


def _journey_table(spans: list[dict]) -> None:
    """Stage, start, end, duration, status, error; errors highlighted."""
    df = pd.DataFrame([{"#": i, "stage": s["stage"], "start": s["start"][11:23],
                        "end": s["end"][11:23], "duration_ms": s["duration_ms"],
                        "status": s["status"], "error": s["error"] or "",
                        "process": s["process"],
                        "detail": ", ".join(f"{k}={v}" for k, v in s["attrs"].items()
                                            if k in ("result", "similarity", "attempt",
                                                     "matched_query", "failed_stage",
                                                     "status_detail", "path"))}
                       for i, s in enumerate(spans)])

    def tint(row: pd.Series) -> list[str]:
        if row["status"] != "ok":
            return ["background-color: #ffcdd2; color: #000"] * len(row)
        if row["stage"] == "cache_lookup":
            hit = "result=hit" in row["detail"]
            return [f"background-color: {'#c8e6c9' if hit else '#bbdefb'}; color: #000"] * len(row)
        return [""] * len(row)

    st.dataframe(df.style.apply(tint, axis=1), hide_index=True, use_container_width=True)
    st.caption("Times are local (America/Los_Angeles). Green = cache-hit lookup, blue = "
               "cache-miss lookup, red = failed stage. Source: `reports/hw10/raw/spans.jsonl`.")


def _gantt(spans: list[dict]) -> None:
    """Timeline of the journey (offsets from the request start)."""
    t0 = min(s["start_ms"] for s in spans)
    df = pd.DataFrame([{"stage": f"{i:02d} {s['stage']}", "from_ms": s["start_ms"] - t0,
                        "to_ms": max(s["end_ms"] - t0, s["start_ms"] - t0 + 1),
                        "status": s["status"]} for i, s in enumerate(spans)])
    st.altair_chart(alt.Chart(df).mark_bar().encode(
        x=alt.X("from_ms:Q", title="ms since request start"), x2="to_ms:Q",
        y=alt.Y("stage:N", sort=None, title=None),
        color=alt.Color("status:N", scale=alt.Scale(domain=["ok", "error"],
                                                    range=["#1565c0", "#c62828"]))),
        use_container_width=True)


def main() -> None:
    """Route to the chosen page."""
    page = header()
    {"Summary": summary_page, "Evaluation": evaluation_page, "Trace lookup": trace_page}[page]()


main()
