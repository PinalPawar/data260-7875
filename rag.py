"""
HW4 Part 4: Grounded RAG question-answering + context engineering study,
over the grocery-recall corpus (39 docs, corpus/).

Reuses the same embedding approach (sentence-transformers/all-MiniLM-L6-v2 via
LlamaIndex) already proven working in HW3's retrieval_pipeline.py.

Three configs compared, all against retrieval from the same index:
  (A) no_rag             : question sent to the LLM with no context at all
  (B) basic_rag          : raw top-k retrieved chunk text pasted in as context,
                            no filtering
  (C) context_engineered : starts from a WIDER retrieval (k=5), then:
                              - drops chunks below a relevance-score floor
                                (irrelevant chunks)
                              - de-duplicates near-identical chunks (keeping
                                the higher-scored copy when two chunks say
                                almost the same thing, e.g. boilerplate
                                "at-risk populations" text repeated across
                                CDC pages)
                              - keeps at most 3 survivors, ordered by score
                              - labels each surviving chunk with a numbered
                                source tag [1], [2], [3]... and instructs the
                                model to cite those numbers and refuse with an
                                exact required sentence when the context is
                                insufficient

Six questions, one per required category (see QUESTIONS below):
  Q1 answer in one chunk | Q2 needs two chunks | Q3 similar info across docs
  Q4 ambiguous | Q5 not in the documents | Q6 unrelated (Q5/Q6 must refuse)

Generation uses a local Ollama server (http://localhost:11434), model name
from the OLLAMA_MODEL env var (default "qwen3" -- override if `ollama list`
shows a different tag, e.g. OLLAMA_MODEL=qwen3:1.7b).

Run:
    ollama list                            # confirm the exact model tag
    OLLAMA_MODEL=qwen3:1.7b python3 rag.py

Writes:
    reports/hw04/raw/rag_retrievals.json   -- top-k chunks printed/saved per
                                               question (text, source, chunk_id,
                                               score) -- item 2 of the spec
    reports/hw04/raw/rag_ksweep.json       -- retrieval-only sweep at k=1,3,5
    reports/hw04/raw/rag_eval.json         -- full 3-config x 6-question
                                               generations (k=3 for basic_rag,
                                               k=5-then-filtered for
                                               context_engineered)
    reports/hw04/RAG_EVAL.md               -- evaluation table + k-sweep summary
"""
import difflib
import json
import os
import time
from pathlib import Path

import requests
from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.node_parser import TokenTextSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

ROOT = Path(__file__).resolve().parent
CORPUS_DIR = ROOT / "corpus"
RAW_DIR = ROOT / "reports" / "hw04" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
K_BASIC = 3          # top_k for basic_rag (item 2/3 of the spec)
K_ENGINEERED = 5      # wider net for context_engineered, before filtering
RELEVANCE_FLOOR = 0.35   # score below this = "irrelevant" -- chosen from the
                          # k-sweep gap: in-domain chunks score ~0.55-0.72,
                          # out-of-domain ~0.10-0.15, so 0.35 cleanly separates
DUP_SIMILARITY = 0.60     # difflib ratio above this on chunk text = "duplicate"
MAX_ENGINEERED_CHUNKS = 3

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3")
OLLAMA_URL = "http://localhost:11434/api/generate"

REQUIRED_REFUSAL = "I cannot answer this question from the provided documents"

# Each question is tagged with the required test category and, where the
# answer IS in the corpus, the source file(s) that should be retrieved -- used
# to auto-score "correct retrieval" in the eval table.
QUESTIONS = [
    {
        "id": "Q1", "category": "one_chunk", "must_refuse": False,
        "question": "What pathogen was linked to the 2021 spinach recall?",
        "expected_sources": ["fda_outbreak_ecoli_spinach_2021.txt"],
    },
    {
        "id": "Q2", "category": "two_chunks", "must_refuse": False,
        "question": (
            "Name two infant formula products recalled due to Clostridium "
            "botulinum contamination, and the year each was recalled."
        ),
        "expected_sources": [
            "fda_recall_byheart_infant_formula_2025.txt",
            "fda_recall_nara_organics_infant_formula_2026.txt",
        ],
    },
    {
        "id": "Q3", "category": "similar_across_docs", "must_refuse": False,
        "question": "Which groups are considered highest-risk for severe Listeria infection?",
        "expected_sources": [
            "cdc_about_listeria.txt",
            "cdc_outbreak_deli_meats_listeria.txt",
        ],
    },
    {
        "id": "Q4", "category": "ambiguous", "must_refuse": False,
        "question": "What product was recalled in 2026 due to contamination?",
        # Deliberately many valid answers exist in the corpus (eggs, ground
        # beef, infant formula, soft cheese, cucumbers, berries...) -- there
        # is no single "expected_sources" list; correctness here means the
        # model acknowledges more than one recall rather than confidently
        # naming just one as if it were the only answer.
        "expected_sources": None,
    },
    {
        "id": "Q5", "category": "not_in_documents", "must_refuse": True,
        "question": "How much revenue did J.M. Smucker Company lose due to the 2022 peanut butter recall?",
        "expected_sources": [],  # in-domain topic, but the figure is nowhere in the corpus
    },
    {
        "id": "Q6", "category": "unrelated", "must_refuse": True,
        "question": "What is the current price of Tesla stock?",
        "expected_sources": [],
    },
]


def load_corpus():
    docs = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        raw = path.read_text(encoding="utf-8")
        docs.append(Document(text=raw, metadata={"file_name": path.name}))
    if not docs:
        raise SystemExit(f"No .txt files found in {CORPUS_DIR}")
    return docs


def build_index():
    embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    Settings.embed_model = embed_model
    docs = load_corpus()
    parser = TokenTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    nodes = parser.get_nodes_from_documents(docs)
    index = VectorStoreIndex(nodes, embed_model=embed_model)
    print(f"Loaded {len(docs)} corpus docs (>= 5 required) -> {len(nodes)} chunks "
          f"(chunk_size={CHUNK_SIZE}, chunk_overlap={CHUNK_OVERLAP})")
    return index


def retrieve(index, query, k):
    """Item 1/2 of the spec: each retrieved chunk keeps its full text,
    source name, and a chunk_id, plus the similarity score."""
    retriever = index.as_retriever(similarity_top_k=k)
    nodes = retriever.retrieve(query)
    return [
        {
            "chunk_id": n.node.node_id,
            "score": round(float(n.score), 4) if n.score is not None else None,
            "source_file": n.node.metadata.get("file_name", "unknown"),
            "text": n.node.text,
            "preview": " ".join(n.node.text.split())[:160],
        }
        for n in nodes
    ]


def print_chunks(label, chunks):
    """Item 2: print retrieved chunks with source and score BEFORE calling the LLM."""
    print(f"  [{label}] retrieved {len(chunks)} chunk(s):")
    for c in chunks:
        print(f"    - {c['source_file']}  score={c['score']}  chunk_id={c['chunk_id'][:8]}...")
        print(f"      \"{c['preview']}...\"")


def engineer_context(chunks):
    """Item 3(C): drop irrelevant + duplicate chunks, order by score, cap at
    MAX_ENGINEERED_CHUNKS survivors. Returns (survivors, dropped_log) where
    dropped_log records WHY each dropped chunk was dropped, for the report."""
    dropped_log = []

    # Step 1: drop irrelevant (below the relevance floor)
    relevant = []
    for c in sorted(chunks, key=lambda c: c["score"] or 0, reverse=True):
        if (c["score"] or 0) < RELEVANCE_FLOOR:
            dropped_log.append({"chunk_id": c["chunk_id"], "source_file": c["source_file"],
                                 "reason": f"irrelevant (score {c['score']} < {RELEVANCE_FLOOR})"})
        else:
            relevant.append(c)

    # Step 2: de-duplicate near-identical chunks (keep the higher-scored copy)
    survivors = []
    for c in relevant:
        is_dup = False
        for kept in survivors:
            ratio = difflib.SequenceMatcher(None, c["text"], kept["text"]).ratio()
            if ratio >= DUP_SIMILARITY:
                is_dup = True
                dropped_log.append({"chunk_id": c["chunk_id"], "source_file": c["source_file"],
                                     "reason": f"duplicate of {kept['source_file']} "
                                               f"(text similarity {ratio:.2f} >= {DUP_SIMILARITY})"})
                break
        if not is_dup:
            survivors.append(c)

    # Step 3: cap context budget
    if len(survivors) > MAX_ENGINEERED_CHUNKS:
        for c in survivors[MAX_ENGINEERED_CHUNKS:]:
            dropped_log.append({"chunk_id": c["chunk_id"], "source_file": c["source_file"],
                                 "reason": f"context budget (kept top {MAX_ENGINEERED_CHUNKS} only)"})
        survivors = survivors[:MAX_ENGINEERED_CHUNKS]

    return survivors, dropped_log


def call_ollama(prompt, max_tokens=400):
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "think": False,  # qwen3 is a "thinking" model; without this it
                              # burns the whole token budget on reasoning and
                              # returns an empty answer (see AI_USE.md)
            "options": {"num_predict": max_tokens},
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def build_prompt(config, question, chunks):
    if config == "no_rag":
        return f"Answer this question as best you can:\n\nQuestion: {question}\nAnswer:"

    if config == "basic_rag":
        context = "\n\n".join(c["text"] for c in chunks)
        return f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"

    if config == "context_engineered":
        # Number the SURVIVING sources (chunks already filtered/deduped by
        # engineer_context) and require the model to cite by that number.
        source_order = []
        for c in chunks:
            if c["source_file"] not in source_order:
                source_order.append(c["source_file"])
        numbered = {name: i + 1 for i, name in enumerate(source_order)}
        context = "\n\n".join(
            f"[{numbered[c['source_file']]}] {c['text']}" for c in chunks
        )
        legend = "; ".join(f"[{n}]={name}" for name, n in numbered.items())
        return (
            "You are a food-safety recall assistant. Answer ONLY using the numbered context "
            "below, and cite the source number(s) you used (e.g. [1] or [1][2]). If the "
            "context does not contain the answer, respond with EXACTLY this sentence and "
            f"nothing else: \"{REQUIRED_REFUSAL}\"\n\n"
            f"Sources: {legend}\n\nContext:\n{context}\n\nQuestion: {question}\nAnswer:"
        )
    raise ValueError(config)


def looks_like_refusal(answer):
    a = answer.lower()
    return REQUIRED_REFUSAL.lower() in a or any(p in a for p in [
        "don't have enough information", "do not have enough information",
        "cannot answer", "can't answer", "no information", "not contain the answer",
        "unable to answer",
    ])


def correct_retrieval(question_cfg, retrieved_sources):
    """Auto-scorable part of the eval table: did retrieval surface the
    expected source(s)? None (Q4, ambiguous) means "not auto-scored -- judged
    manually from the printed answer instead"."""
    expected = question_cfg["expected_sources"]
    if expected is None:
        return None
    if not expected:  # Q5/Q6: correct retrieval == nothing in-domain dominated
        return True
    return all(any(e in s for s in retrieved_sources) for e in expected)


def main():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Model: Ollama `{OLLAMA_MODEL}` | Building index...")
    index = build_index()

    # --- k-sweep: retrieval only, no LLM calls, fast (item 5) ---
    print("\n" + "=" * 78 + "\nK-SWEEP (retrieval only, k=1,3,5)\n" + "=" * 78)
    ksweep_results = []
    first_irrelevant_rank = {}  # question_id -> first rank whose score < RELEVANCE_FLOOR
    for q in QUESTIONS:
        for k in (1, 3, 5):
            chunks = retrieve(index, q["question"], k)
            print_chunks(f"{q['id']} k={k}", chunks)
            ksweep_results.append({"question_id": q["id"], "question": q["question"], "k": k,
                                    "chunks": [{kk: vv for kk, vv in c.items() if kk != "text"} for c in chunks]})
            if k == 5 and q["id"] not in first_irrelevant_rank:
                for rank, c in enumerate(chunks, start=1):
                    if (c["score"] or 0) < RELEVANCE_FLOOR:
                        first_irrelevant_rank[q["id"]] = rank
                        break
                else:
                    first_irrelevant_rank[q["id"]] = None
    with open(RAW_DIR / "rag_ksweep.json", "w") as f:
        json.dump(ksweep_results, f, indent=2)

    best_k_note = []
    for q in QUESTIONS:
        rows_by_k = {r["k"]: r["chunks"] for r in ksweep_results if r["question_id"] == q["id"]}
        top1_by_k = {k: (rows[0]["score"] if rows else None) for k, rows in rows_by_k.items()}
        note = (f"{q['id']}: top-1 score k=1:{top1_by_k.get(1)} k=3:{top1_by_k.get(3)} "
                f"k=5:{top1_by_k.get(5)}; irrelevant chunk first appears at rank "
                f"{first_irrelevant_rank.get(q['id'])} within k=5")
        best_k_note.append(note)
        print(note)

    # --- retrieval printout saved separately (item 2 deliverable) ---
    retrieval_printout = []
    for q in QUESTIONS:
        chunks = retrieve(index, q["question"], K_BASIC)
        retrieval_printout.append({"question_id": q["id"], "question": q["question"],
                                    "k": K_BASIC, "chunks": chunks})
    with open(RAW_DIR / "rag_retrievals.json", "w") as f:
        json.dump(retrieval_printout, f, indent=2)

    # --- 3-config evaluation ---
    print("\n" + "=" * 78 + "\n3-CONFIG EVALUATION\n" + "=" * 78)
    eval_rows = []
    for q in QUESTIONS:
        basic_chunks = retrieve(index, q["question"], K_BASIC)
        wide_chunks = retrieve(index, q["question"], K_ENGINEERED)
        engineered_chunks, dropped_log = engineer_context(wide_chunks)

        print(f"\n--- {q['id']} ({q['category']}): {q['question']}")
        print_chunks("basic_rag top-3", basic_chunks)
        print(f"  [context_engineered] wide retrieval k={K_ENGINEERED}, "
              f"{len(dropped_log)} chunk(s) dropped:")
        for d in dropped_log:
            print(f"    - dropped {d['source_file']}: {d['reason']}")
        print_chunks("context_engineered survivors", engineered_chunks)

        for config, chunks in [("no_rag", []), ("basic_rag", basic_chunks),
                                ("context_engineered", engineered_chunks)]:
            prompt = build_prompt(config, q["question"], chunks)
            t0 = time.perf_counter()
            answer = call_ollama(prompt)
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            refused = looks_like_refusal(answer)
            retrieved_sources = [c["source_file"] for c in chunks]
            print(f"\n  [{config}] latency={latency_ms}ms refused={refused}")
            print(f"  A: {answer[:400]}")
            eval_rows.append({
                "question_id": q["id"],
                "question": q["question"],
                "category": q["category"],
                "must_refuse": q["must_refuse"],
                "config": config,
                "answer": answer,
                "latency_ms": latency_ms,
                "refused": refused,
                "sources_used": retrieved_sources,
                "correct_retrieval": correct_retrieval(q, retrieved_sources) if config != "no_rag" else None,
                "dropped_chunks": dropped_log if config == "context_engineered" else None,
            })
    with open(RAW_DIR / "rag_eval.json", "w") as f:
        json.dump(eval_rows, f, indent=2)

    # --- Markdown report ---
    lines = [
        "# HW4 Part 4 - RAG Evaluation\n",
        f"Model: Ollama `{OLLAMA_MODEL}` | Chunking: TokenTextSplitter(chunk_size={CHUNK_SIZE}, "
        f"chunk_overlap={CHUNK_OVERLAP}) | Vector store: LlamaIndex in-memory VectorStoreIndex | "
        f"basic_rag k={K_BASIC} | context_engineered: retrieve k={K_ENGINEERED} then filter "
        f"(relevance floor {RELEVANCE_FLOOR}, dup threshold {DUP_SIMILARITY}) down to "
        f"<= {MAX_ENGINEERED_CHUNKS}\n",
        "## k-sweep summary\n",
    ]
    lines += [f"- {n}" for n in best_k_note]
    lines += [
        "\n## Evaluation table\n",
        "| Q | Category | Config | Refused? | Correct retrieval | Sources used |",
        "|---|---|---|---|---|---|",
    ]
    for r in eval_rows:
        cr = "n/a" if r["correct_retrieval"] is None else str(r["correct_retrieval"])
        srcs = ", ".join(r["sources_used"]) if r["sources_used"] else "(none, no_rag)"
        lines.append(f"| {r['question_id']} | {r['category']} | {r['config']} | {r['refused']} | {cr} | {srcs} |")
    with open(ROOT / "reports" / "hw04" / "RAG_EVAL.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    print("\nWrote reports/hw04/raw/rag_retrievals.json, rag_ksweep.json, rag_eval.json, "
          "reports/hw04/RAG_EVAL.md")


if __name__ == "__main__":
    main()
