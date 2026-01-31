#!/usr/bin/env python3
"""
local_pdf_qa.py
PDF Q&A with chunking, two-pass reasoning, streaming, and semantic memory
(embeddings + Annoy vector index).

Verification (per-PDF memory):
  Run twice on two different PDFs and verify:
  - memories/ contains two separate files.
  - Re-running same PDF appends to same file.

Usage:
  pip install -r requirements.txt
  python local_pdf_qa.py path/to/file.pdf "Your question here"

Environment variables:
  MODEL_ID (default: meta.llama3-3-70b-instruct-v1:0)
  EMBEDDING_MODEL_ID (default: amazon.titan-embed-text-v1)
  AWS_REGION (default: us-east-1)
  CHUNK_SIZE, CHUNK_OVERLAP, MAX_PAGES, MAX_CHUNKS
  DEBUG=1, SAVE_MEMORY=1, MAX_MEMORY_TO_LOAD
  ENABLE_TOOL_PLANNER=1 - augment with BFSI external search (see tools.py)
  USE_ORCHESTRATOR=1 - use multi-agent orchestrator (default)
"""

import sys
import os
import json
import math
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from PyPDF2 import PdfReader
import boto3

try:
    import annoy
    import numpy as np
    HAS_ANNOY = True
except ImportError:
    HAS_ANNOY = False

# --- Configuration ---
# Use inference profile ID (required for Llama 3.3 70B on-demand in us-east-1)
MODEL_ID = os.environ.get("MODEL_ID", "us.meta.llama3-3-70b-instruct-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1200))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 200))
MAX_PAGES = int(os.environ.get("MAX_PAGES", 20))
MAX_CHUNKS = int(os.environ.get("MAX_CHUNKS", 60))

LLAMA_MAX_GEN = int(os.environ.get("LLAMA_MAX_GEN", 800))
CLAUDE_MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", 800))

SAVE_MEMORY = os.environ.get("SAVE_MEMORY", "1") != "0"
MAX_MEMORY_TO_LOAD = int(os.environ.get("MAX_MEMORY_TO_LOAD", 5))

DEBUG = os.environ.get("DEBUG", "0") == "1"
ENABLE_TOOL_PLANNER = os.environ.get("ENABLE_TOOL_PLANNER", "0") == "1"
USE_ORCHESTRATOR = os.environ.get("USE_ORCHESTRATOR", "1") == "1"

MEMORY_DIR = Path("memories")
MEMORY_DIR.mkdir(exist_ok=True)


# --- Embeddings ---

def get_embedding(text, model_id=None, region=REGION):
    """Get L2-normalized embedding vector from Bedrock. Returns None on error."""
    if model_id is None:
        model_id = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
    if not text or not text.strip():
        return None
    try:
        client = boto3.client("bedrock-runtime", region_name=region)
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text}),
        )
        raw = response["body"].read().decode("utf-8")
        parsed = json.loads(raw)
        emb = parsed.get("embedding")
        if not emb or not isinstance(emb, list):
            return None
        if HAS_ANNOY:
            vec = np.array(emb, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec.tolist()
        vec = [float(x) for x in emb]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] get_embedding failed: {e}")
        return None


# --- Memory ---

def _pdf_memory_filename(pdf_path: str) -> str:
    """Deterministic memory filename: memories/memory_<basename>_<hash>.json"""
    abs_path = os.path.abspath(pdf_path)
    h = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:10]
    base = os.path.basename(abs_path)
    return str(MEMORY_DIR / f"memory_{base}_{h}.json")


def load_memory_for_pdf(pdf_path: str):
    """Load memory list for this PDF. Returns [] if file does not exist."""
    path = _pdf_memory_filename(pdf_path)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] load_memory_for_pdf failed: {e}")
        return []


def append_memory_for_pdf(entry, pdf_path: str):
    """Append entry to this PDF's memory file. Uses atomic write."""
    path = _pdf_memory_filename(pdf_path)
    mem = load_memory_for_pdf(pdf_path)
    mem.append(entry)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_all_memory_files():
    """List paths of all memory files in MEMORY_DIR."""
    if not MEMORY_DIR.exists():
        return []
    return sorted(str(p) for p in MEMORY_DIR.glob("memory_*.json"))


def build_annoy_index(mem_list):
    """Build Annoy index from memories with embeddings. Returns (index, id_map) or (None, None)."""
    if not HAS_ANNOY or not mem_list:
        return None, None
    d = None
    for m in mem_list:
        emb = m.get("embedding")
        if emb and isinstance(emb, list) and len(emb) > 0:
            d = len(emb)
            break
    if d is None:
        return None, None
    try:
        index = annoy.AnnoyIndex(d, "angular")
        id_map = {}
        for mem_idx, m in enumerate(mem_list):
            emb = m.get("embedding")
            if emb and isinstance(emb, list) and len(emb) == d:
                idx = index.get_n_items()
                index.add_item(idx, emb)
                id_map[idx] = mem_idx
        if index.get_n_items() == 0:
            return None, None
        index.build(10)
        return index, id_map
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] build_annoy_index failed: {e}")
        return None, None


def find_relevant_memories_semantic(question, mem_list, top_k=5, threshold=0.7, pdf_path=None):
    """Semantic search via embeddings + Annoy. Falls back to token-overlap only if embeddings fail."""
    if not mem_list:
        return []
    q_vec = get_embedding(question)
    if q_vec is not None:
        index, id_map = build_annoy_index(mem_list)
        if index is not None and id_map:
            try:
                ids, dists = index.get_nns_by_vector(q_vec, top_k, include_distances=True)
                results = []
                for aid, d in zip(ids, dists):
                    mem_idx = id_map.get(aid)
                    if mem_idx is not None:
                        cos_sim = max(0.0, min(1.0, 1.0 - (d * d) / 2.0))
                        if cos_sim >= threshold:
                            m = mem_list[mem_idx].copy()
                            m["_similarity"] = cos_sim
                            results.append(m)
                results.sort(key=lambda x: x.get("_similarity", 0), reverse=True)
                if results:
                    return results
            except Exception as e:
                if DEBUG:
                    print(f"[DEBUG] semantic search failed: {e}")
    # Fallback only when embeddings/index unavailable
    if DEBUG:
        print("[DEBUG] falling back to token-overlap")
    return _find_relevant_memories_token(question, pdf_path or "", mem_list, top_k)


def find_relevant_chunks(query: str, chunks: list, top_k: int = 10, threshold: float = 0.3):
    """
    Find chunks relevant to query using semantic similarity (embeddings).
    Returns list of {chunk_text, idx, similarity}.
    Limits embedding calls to query + min(15, len(chunks)) for efficiency.
    """
    if not chunks:
        return []
    q_vec = get_embedding(query)
    if q_vec is None:
        return []
    scored = []
    max_embed = min(len(chunks), 15)
    for i, chunk in enumerate(chunks[:max_embed]):
        c_vec = get_embedding(chunk[:2000])
        if c_vec is None:
            continue
        cos_sim = sum(a * b for a, b in zip(q_vec, c_vec))
        cos_sim = max(0.0, min(1.0, cos_sim))
        if cos_sim >= threshold:
            scored.append({"chunk_text": chunk, "idx": i, "similarity": cos_sim})
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


def _find_relevant_memories_token(question, pdf_path, mem_list, max_results):
    """Token-overlap relevance. Used only when semantic search fails."""
    if not mem_list:
        return []
    q_tokens = set(w.lower() for w in question.split() if len(w) > 2)
    scored = []
    for m in mem_list:
        s = 100 if (m.get("pdf_path") and os.path.basename(m.get("pdf_path")) == os.path.basename(pdf_path)) else 0
        mq = m.get("question", "")
        s += len(q_tokens & set(w.lower() for w in mq.split() if len(w) > 2))
        scored.append((s, m))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for s, m in scored if s > 0][:max_results]


# --- PDF / chunking ---

def extract_text_from_pdf(path, max_pages=MAX_PAGES):
    reader = PdfReader(path)
    texts = []
    for i in range(min(len(reader.pages), max_pages)):
        try:
            texts.append(reader.pages[i].extract_text() or "")
        except Exception:
            texts.append("")
    return "\n\n".join(texts)


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP, max_chunks=MAX_CHUNKS):
    if not text:
        return []
    chunks, start, L = [], 0, len(text)
    while start < L and len(chunks) < max_chunks:
        end = start + size
        chunks.append(text[start:end].strip())
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


# --- Bedrock: parsing (contract: {"generation": "..."}) ---

def _parse_generation(raw_str):
    """Extract plain text from Bedrock response. Contract: top-level {"generation": "..."}."""
    if not raw_str:
        return ""
    try:
        parsed = json.loads(raw_str)
        if isinstance(parsed, dict) and "generation" in parsed:
            gen = parsed["generation"]
            return str(gen) if gen else ""  # Do not strip - preserve leading/trailing spaces
    except json.JSONDecodeError:
        pass
    return ""


def _append_stream_piece(final_text, piece):
    """
    Append a streaming piece to accumulated text. Insert a space when joining
    two word boundaries that Bedrock token-by-token streaming may have split
    without a space. Conservative: only when second piece starts with uppercase
    (new word) or first ends with sentence punctuation, to avoid splitting
    subwords ("invigorate") or acronyms ("MSMEs").
    """
    if not piece:
        return final_text
    if not final_text:
        return piece
    last = final_text[-1]
    first = piece[0]
    attach_punct = ".,!?;:)\"'"
    need_space = (
        not last.isspace() and last not in attach_punct and
        not first.isspace() and first not in attach_punct and
        (first.isupper() or last in ".!?")
    )
    return final_text + (" " if need_space else "") + piece


# --- Bedrock: invoke ---

def _prepare_request(prompt):
    if "llama" in MODEL_ID.lower():
        return {"prompt": prompt, "max_gen_len": LLAMA_MAX_GEN, "temperature": 0.2, "top_p": 0.95}
    if "claude" in MODEL_ID.lower():
        return {"prompt": prompt, "max_tokens_to_sample": CLAUDE_MAX_TOKENS}
    return {"prompt": prompt}


def call_bedrock(prompt, model_id=MODEL_ID, region=REGION):
    """Synchronous Bedrock call. Returns plain text only."""
    client = boto3.client("bedrock-runtime", region_name=region)
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(_prepare_request(prompt)),
    )
    raw = response["body"].read().decode("utf-8")
    return _parse_generation(raw)


def call_bedrock_stream(prompt, model_id=MODEL_ID, region=REGION):
    """Streaming Bedrock call. Contract: event["chunk"]["bytes"] -> UTF-8 JSON with generation."""
    client = boto3.client("bedrock-runtime", region_name=region)
    if not hasattr(client, "invoke_model_with_response_stream"):
        return call_bedrock(prompt, model_id=model_id, region=region)
    response = client.invoke_model_with_response_stream(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(_prepare_request(prompt)),
    )
    final_text = ""
    for event in response.get("body", []):
        try:
            chunk = event.get("chunk", {})
            raw_bytes = chunk.get("bytes")
            if raw_bytes is None:
                continue
            decoded = raw_bytes.decode("utf-8") if isinstance(raw_bytes, bytes) else str(raw_bytes)
            piece = _parse_generation(decoded)
            if piece:
                print(piece, end="", flush=True)
                final_text = _append_stream_piece(final_text, piece)
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] stream event error: {e}")
    print()
    return final_text.strip()


# --- Prompts ---

def make_chunk_prompt(chunk, question, idx, total):
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are an expert analyst. Answer the question using ONLY the text in this chunk.\n\n"
        f"CHUNK {idx}/{total}:\n{chunk}\n\nQUESTION:\n{question}\n\n"
        "INSTRUCTIONS:\n"
        "- If the chunk does not contain information that answers the question, reply exactly: NOT RELEVANT\n"
        "- Otherwise: give a short partial answer (1-3 sentences) and one-line rationale.\n"
        "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    )


def make_synthesis_prompt(partials, question, prior_memory_text=None, external_context=None, external_provenance=None):
    joined = "\n\n".join(f"PARTIAL {i+1}: {p}" for i, p in enumerate(partials))
    mem = f"PAST INTERACTIONS:\n{prior_memory_text}\n\n" if prior_memory_text else ""
    ext = ""
    if external_context:
        ext = f"EXTERNAL CONTEXT (live data):\n{external_context}\n\n"
        if external_provenance:
            urls = [p.get("url", "") for p in external_provenance if p.get("url")]
            if urls:
                ext += f"EXTERNAL SOURCES: {', '.join(urls)}\n\n"
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are a senior researcher combining partial answers into one clear answer.\n\n"
        f"{mem}{ext}PARTIAL ANSWERS:\n{joined}\n\n"
        "INSTRUCTIONS:\n"
        "- Merge into one final answer. If partials disagree, explain uncertainty.\n"
        "- If none contain an answer, say 'Not found in document'.\n"
        "- Respect any length or format requested in the question (e.g. 'in 3 lines', 'briefly').\n\n"
        f"FINAL QUESTION:\n{question}\n\nFINAL ANSWER:\n"
        "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    )


# --- Main ---

def main():
    if len(sys.argv) < 3:
        print("Usage: python local_pdf_qa.py path/to/file.pdf \"Your question here\"")
        sys.exit(2)

    pdf_path = sys.argv[1]
    question = sys.argv[2]

    if not os.path.exists(pdf_path):
        print("PDF file not found:", pdf_path)
        sys.exit(1)

    if USE_ORCHESTRATOR:
        from orchestrator import run_workflow
        result = run_workflow(question, pdf_path, use_streaming=True)
        print("\n=== ANSWER ===\n")
        print(result["answer"])
        print("\n=== SOURCES ===\n")
        for p in result.get("provenance", []):
            typ = p.get("type", "internal")
            src = p.get("source", "pdf")
            page = p.get("page")
            tool = p.get("tool")
            line = f"  [{typ}] {src}"
            if page is not None:
                line += f" page={page}"
            if typ == "external" and tool:
                line += f" tool={tool}"
            print(line)
        print("\n=== CONFIDENCE ===\n")
        print(result.get("confidence", 0.0))
        if result.get("flags"):
            print("\n=== FLAGS ===\n")
            print(", ".join(result["flags"]))
        print("\n=== END ===\n")
        return

    memory = load_memory_for_pdf(pdf_path)
    if DEBUG:
        print(f"[DEBUG] using memory file: {_pdf_memory_filename(pdf_path)}")
    relevant = find_relevant_memories_semantic(
        question, memory, top_k=MAX_MEMORY_TO_LOAD, pdf_path=pdf_path
    )
    if relevant:
        print(f"Found {len(relevant)} relevant past interaction(s).")
    prior_mem_text = "\n".join(f"Q: {m.get('question')}\nA: {m.get('answer')}" for m in relevant) if relevant else None

    external_context = None
    external_provenance = []
    if ENABLE_TOOL_PLANNER:
        try:
            import tools
            plan = tools.tool_planner_agent(question, call_llm_fn=call_bedrock)
            providers = plan.get("recommended_providers", [])
            if providers:
                print("Tool planner: checking external sources...")
                external_context, external_provenance = tools.run_external_search(
                    question, call_llm_fn=call_bedrock
                )
                if external_context and external_context.strip():
                    print("External context retrieved.")
            elif DEBUG:
                print("[DEBUG] planner: answer likely internal, skipping external tools")
        except ImportError:
            pass
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] tool planner failed: {e}")

    print("Extracting text from PDF...")
    doc_text = extract_text_from_pdf(pdf_path)
    partials = []
    if not doc_text.strip():
        print("No text could be extracted from the PDF.")
        final_answer = "Not found in document"
    else:
        chunks = chunk_text(doc_text)
        print(f"Document split into {len(chunks)} chunks.")
        for i, chunk in enumerate(chunks, 1):
            print(f"Querying chunk {i}/{len(chunks)}...")
            try:
                resp = call_bedrock_stream(make_chunk_prompt(chunk, question, i, len(chunks)))
            except Exception as e:
                print(f"Error on chunk {i}: {e}")
                resp = call_bedrock(make_chunk_prompt(chunk, question, i, len(chunks)))
            resp_text = (resp or "").strip()
            if resp_text.upper().startswith("NOT RELEVANT"):
                continue
            partials.append(resp_text)

        if not partials:
            if external_context and external_context.strip():
                print("Synthesizing from external context...")
                final_answer = call_bedrock_stream(
                    make_synthesis_prompt(
                        [external_context], question, prior_mem_text,
                        external_context=None, external_provenance=external_provenance
                    )
                )
                if not (final_answer or final_answer.strip()):
                    final_answer = "Not found in document"
            else:
                final_answer = "Not found in document"
        else:
            print("Synthesizing final answer...")
            final_answer = call_bedrock_stream(
                make_synthesis_prompt(partials, question, prior_mem_text, external_context, external_provenance)
            )
            if not (final_answer or final_answer.strip()):
                final_answer = "Not found in document"

    print("\n=== FINAL ANSWER ===\n")
    print(final_answer)
    print("\n=== END ===\n")

    # Always save when SAVE_MEMORY=1 (never exit before this)
    if SAVE_MEMORY:
        embedding = get_embedding(final_answer)
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "pdf_path": os.path.abspath(pdf_path),
            "question": question,
            "answer": final_answer,
            "partials": partials,
            "model_id": MODEL_ID,
            "embedding": embedding,
        }
        append_memory_for_pdf(entry, pdf_path)


if __name__ == "__main__":
    main()
