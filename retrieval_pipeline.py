"""
DATA260 HW3, Part 2: compare Token / Semantic / Sentence-window chunking with
LlamaIndex, retrieval-only (no answer generation).

What this does, in order:
  1. Loads every .txt file in corpus/ as one LlamaIndex Document (each file
     keeps its filename in metadata, so later we can check whether a
     retrieved chunk actually came from the question's expected source file).
  2. For each of the 3 chunking techniques: splits the corpus into nodes,
     builds an in-memory VectorStoreIndex (LlamaIndex's default
     SimpleVectorStore -- nothing leaves this machine), then for each of the
     6 questions in questions.yaml, retrieves the top-k nodes and prints +
     saves a rank/store_score/cosine_sim/chunk_len/preview table.
  3. Saves every row as machine-readable data to reports/hw03/raw/, plus a
     small chunk_stats.json (chunk counts / avg length per technique) that
     scripts/summarize_metrics.py turns into METRICS.md.

Run:
    pip install -r requirements.txt
    python3 retrieval_pipeline.py 2>&1 | tee reports/hw03/RUN_LOG.txt

The first run downloads the ~90MB embedding model from Hugging Face the
first time it's used (needs a normal internet connection) and caches it
locally after that.
"""
import csv
import json
import time
from pathlib import Path

import numpy as np
import yaml
from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.node_parser import (
    SemanticSplitterNodeParser,
    SentenceWindowNodeParser,
    TokenTextSplitter,
)

ROOT = Path(__file__).resolve().parent
CORPUS_DIR = ROOT / "corpus"
RAW_DIR = ROOT / "reports" / "hw03" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
K = 5  # top-k retrieved per query
TECHNIQUES = ["token", "semantic", "sentence_window"]


def get_embed_model():
    """
    Kept as its own function (instead of inlined in main()) so it's the one
    place to swap in a different embedding model, and so a test harness can
    monkeypatch it with a fake, network-free embedder.
    """
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    return HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)


def load_corpus():
    """
    Each corpus file starts with a small citation header:
        Source: <url>
        Accessed: <date>
        Title: <title>
        <blank line>
        <actual body text>
    We strip that header out of the text that gets chunked/embedded (so
    chunks contain real content, not repeated boilerplate), but keep it in
    node metadata for traceability back to SOURCES.md.
    """
    docs = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        raw = path.read_text(encoding="utf-8")
        meta = {"file_name": path.name}
        body = raw
        lines = raw.split("\n")
        if len(lines) >= 3 and lines[0].startswith("Source:") and lines[1].startswith("Accessed:"):
            meta["source_url"] = lines[0][len("Source:"):].strip()
            meta["accessed"] = lines[1][len("Accessed:"):].strip()
            if lines[2].startswith("Title:"):
                meta["title"] = lines[2][len("Title:"):].strip()
            # body starts after the header + the blank line separating it
            rest = lines[3:]
            while rest and rest[0].strip() == "":
                rest = rest[1:]
            body = "\n".join(rest)
        docs.append(Document(text=body, metadata=meta))
    if not docs:
        raise SystemExit(f"No .txt files found in {CORPUS_DIR} -- run scripts/fetch_corpus.py first.")
    return docs


def cosine(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12
    return float(np.dot(a, b) / denom)


def build_nodes(technique, docs, embed_model):
    if technique == "token":
        # Fixed-size chunking: cut every chunk_size tokens, with some overlap
        # so a sentence that straddles a boundary isn't lost entirely.
        parser = TokenTextSplitter(chunk_size=256, chunk_overlap=32)
    elif technique == "semantic":
        # Cuts where consecutive sentence embeddings differ the most (a
        # "meaning" boundary) instead of a fixed size.
        parser = SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=embed_model,
        )
    elif technique == "sentence_window":
        # Each node is ONE sentence (for precise embedding), but the
        # surrounding `window_size` sentences on each side are stashed in
        # node.metadata["window"] so we don't lose context.
        parser = SentenceWindowNodeParser.from_defaults(
            window_size=3,
            window_metadata_key="window",
            original_text_metadata_key="original_text",
        )
    else:
        raise ValueError(technique)
    return parser.get_nodes_from_documents(docs)


def node_text_for_embedding(technique, node):
    """The text that technique actually embeds/searches over."""
    if technique == "sentence_window":
        return node.metadata.get("window", node.text)
    return node.text


def chunk_len(technique, node):
    return len(node_text_for_embedding(technique, node))


def preview(technique, node, n=160):
    txt = " ".join(node_text_for_embedding(technique, node).split())
    return txt[:n]


def run_one_query(technique, index, embed_model, query, k=K):
    query_embedding = embed_model.get_query_embedding(query)

    retriever = index.as_retriever(similarity_top_k=k)
    t0 = time.perf_counter()
    retrieved = retriever.retrieve(query)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    rows = []
    doc_embeddings = []
    for rank, r in enumerate(retrieved, start=1):
        node = r.node
        store_score = r.score  # similarity score the vector store itself returned

        # Required by the assignment: explicitly (re)compute the chunk's
        # embedding and its cosine similarity to the query, rather than just
        # trusting the store's own score. With SimpleVectorStore's default
        # (cosine) metric these should end up ~equal -- a nice sanity check
        # to point out in the report.
        text_for_embedding = node_text_for_embedding(technique, node)
        doc_embedding = embed_model.get_text_embedding(text_for_embedding)
        doc_embeddings.append(doc_embedding)
        cosine_sim = cosine(query_embedding, doc_embedding)

        rows.append(
            {
                "rank": rank,
                "store_score": round(float(store_score), 6) if store_score is not None else None,
                "cosine_sim": round(cosine_sim, 6),
                "chunk_len": chunk_len(technique, node),
                "preview": preview(technique, node),
                "source_file": node.metadata.get("file_name", "unknown"),
            }
        )

    doc_matrix = np.vstack(doc_embeddings) if doc_embeddings else np.zeros((0, len(query_embedding)))
    return {
        "query_embedding_dim": len(query_embedding),
        "query_embedding_first8": [round(v, 6) for v in query_embedding[:8]],
        "query_vector_shape": (1, len(query_embedding)),
        "doc_matrix_shape": tuple(doc_matrix.shape),
        "latency_ms": round(latency_ms, 3),
        "rows": rows,
    }


def main():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Loading embedding model: {EMBED_MODEL_NAME}")
    embed_model = get_embed_model()
    Settings.embed_model = embed_model  # SemanticSplitterNodeParser reads this too

    docs = load_corpus()
    total_chars = sum(len(d.text) for d in docs)
    print(f"Loaded {len(docs)} corpus documents from {CORPUS_DIR} ({total_chars/1024:.1f} KB total)")

    questions = yaml.safe_load((ROOT / "questions.yaml").read_text())["questions"]
    print(f"Loaded {len(questions)} questions from questions.yaml\n")

    all_rows = []
    chunk_stats = {}

    for technique in TECHNIQUES:
        print(f"{'=' * 78}\nTECHNIQUE: {technique}\n{'=' * 78}")
        nodes = build_nodes(technique, docs, embed_model)
        index = VectorStoreIndex(nodes, embed_model=embed_model)  # in-memory SimpleVectorStore

        lengths = [chunk_len(technique, n) for n in nodes]
        avg_len = sum(lengths) / len(lengths) if lengths else 0.0
        chunk_stats[technique] = {"num_chunks": len(nodes), "avg_chunk_len": round(avg_len, 1)}
        print(f"Chunks produced: {len(nodes)}   avg chunk length: {avg_len:.1f} chars\n")

        for q in questions:
            print(f"--- [{technique}] {q['id']}: {q['question']}")
            result = run_one_query(technique, index, embed_model, q["question"], k=K)
            print(
                f"    query embedding dim={result['query_embedding_dim']} "
                f"first8={result['query_embedding_first8']}"
            )
            print(
                f"    query vector shape={result['query_vector_shape']} "
                f"stacked doc vectors shape={result['doc_matrix_shape']} "
                f"retrieval latency={result['latency_ms']} ms"
            )
            print(f"    {'rank':<5}{'store_score':<13}{'cosine_sim':<12}{'chunk_len':<10}{'source_file':<45}preview")
            for r in result["rows"]:
                print(
                    f"    {r['rank']:<5}{r['store_score']:<13}{r['cosine_sim']:<12}"
                    f"{r['chunk_len']:<10}{r['source_file']:<45}{r['preview']}"
                )
                all_rows.append(
                    {
                        "technique": technique,
                        "question_id": q["id"],
                        "question": q["question"],
                        "expected_source_file": q.get("expected_source_file"),
                        **r,
                        "latency_ms": result["latency_ms"],
                    }
                )
            print()

    csv_path = RAW_DIR / "retrieval_results.csv"
    jsonl_path = RAW_DIR / "retrieval_results.jsonl"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row) + "\n")
    with open(RAW_DIR / "chunk_stats.json", "w", encoding="utf-8") as f:
        json.dump(chunk_stats, f, indent=2)

    print(f"Saved {len(all_rows)} rows -> {csv_path.relative_to(ROOT)}")
    print(f"Saved {len(all_rows)} rows -> {jsonl_path.relative_to(ROOT)}")
    print(f"Saved chunk stats -> {(RAW_DIR / 'chunk_stats.json').relative_to(ROOT)}")
    print("\nNext: python3 scripts/summarize_metrics.py   (builds reports/hw03/METRICS.md)")


if __name__ == "__main__":
    main()
