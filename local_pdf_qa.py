#!/usr/bin/env python3
"""
local_pdf_qa.py
An improved PDF Q&A script that adds chunking (with overlap), a two-pass
reasoning flow, streaming support (separate function), and semantic memory
using embeddings (Bedrock) + Annoy vector index for relevance search.

Usage:
  1) Install additional dependencies: pip install -r requirements_add.txt
  2) Set MODEL_ID and EMBEDDING_MODEL_ID (or rely on defaults). Optionally set AWS_REGION.
  3) python local_pdf_qa.py path/to/file.pdf "Your question here"

Environment variables (optional):
  MODEL_ID (default: meta.llama3-3-70b-instruct-v1:0)
  EMBEDDING_MODEL_ID (default: amazon.titan-embed-text-v1)
  AWS_REGION (default: us-east-1)
  CHUNK_SIZE, CHUNK_OVERLAP, MAX_PAGES, MAX_CHUNKS
  DEBUG=1 to enable debug prints
  SAVE_MEMORY=1 (default) to enable saving memory to memory.json
  MEMORY_FILE to override default memory filename

Notes:
 - Keep your AWS credentials configured (aws configure) so boto3 can read them.
 - The streaming call uses `invoke_model_with_response_stream` when available.
 - Semantic memory uses Annoy for approximate nearest neighbor search.
 - Falls back to token-overlap relevance if embeddings/Annoy unavailable.
 - Memory entries include embeddings for semantic search; older entries without
   embeddings are skipped in vector index but still loaded.
"""

import sys
import os
import json
import math
import uuid
from datetime import datetime
from PyPDF2 import PdfReader
import boto3

# Additional dependencies for semantic memory (install via: pip install -r requirements_add.txt)
try:
    import annoy
    import numpy as np
    HAS_ANNOY = True
except ImportError:
    HAS_ANNOY = False
    # DEBUG will be checked later when needed

# --- Configuration ---
MODEL_ID = os.environ.get("MODEL_ID", "meta.llama3-3-70b-instruct-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
PROFILE = os.environ.get("AWS_PROFILE", None)  # optional

# Chunking parameters (tune these)
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1200))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 200))
MAX_PAGES = int(os.environ.get("MAX_PAGES", 20))
MAX_CHUNKS = int(os.environ.get("MAX_CHUNKS", 60))  # safety cap to avoid floods

# Model generation defaults (tune by model)
LLAMA_MAX_GEN = int(os.environ.get("LLAMA_MAX_GEN", 800))
CLAUDE_MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", 800))

# Memory
SAVE_MEMORY = os.environ.get("SAVE_MEMORY", "1") != "0"
MEMORY_FILE = os.environ.get("MEMORY_FILE", "memory.json")
MAX_MEMORY_TO_LOAD = int(os.environ.get("MAX_MEMORY_TO_LOAD", 5))

# Debugging
DEBUG = os.environ.get("DEBUG", "0") == "1"


# --- Helpers: embeddings ---

def get_embedding(text, model_id=None, region=REGION):
    """
    Get embedding vector for text using Bedrock embedding model.
    Returns L2-normalized vector (list of floats) or None on error.
    """
    if model_id is None:
        model_id = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
    
    if not text or not text.strip():
        if DEBUG:
            print("[DEBUG] get_embedding: empty text provided")
        return None
    
    try:
        client = boto3.client("bedrock-runtime", region_name=region)
        # Amazon Titan embedding model expects {"inputText": text}
        # Note: Some embedding models may use different request shapes; adjust if needed
        request_body = json.dumps({"inputText": text})
        
        response = client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=request_body
        )
        
        raw_str = _read_response_body(response)
        parsed = json.loads(raw_str)
        
        # Extract embedding vector - Titan returns {"embedding": [floats]}
        embedding = None
        if isinstance(parsed, dict):
            if "embedding" in parsed:
                embedding = parsed["embedding"]
            elif "vector" in parsed:
                embedding = parsed["vector"]
            else:
                # Try to find first list of numbers
                for key, value in parsed.items():
                    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], (int, float)):
                        embedding = value
                        break
        
        if embedding is None:
            if DEBUG:
                print(f"[DEBUG] get_embedding: could not extract embedding from response: {parsed}")
            return None
        
        # Convert to list of floats and L2 normalize
        if not HAS_ANNOY:
            # Manual normalization without numpy
            vec = [float(x) for x in embedding]
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
            return vec
        
        vec = np.array(embedding, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()
        
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] get_embedding failed: {e}")
        return None


# --- Helpers: file / memory ---

def load_memory(memory_file=MEMORY_FILE):
    if not os.path.exists(memory_file):
        return []
    try:
        with open(memory_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] failed to load memory file {memory_file}: {e}")
        return []


def append_memory(entry, memory_file=MEMORY_FILE):
    mem = load_memory(memory_file)
    mem.append(entry)
    try:
        with open(memory_file, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
        if DEBUG:
            print(f"[DEBUG] memory appended: {entry.get('id')}")
    except Exception as e:
        print(f"Warning: failed to write memory file: {e}")


def build_annoy_index(mem_list):
    """
    Build Annoy index from memory entries that have embeddings.
    Returns (index, id_map) where id_map maps Annoy idx to memory list index.
    Returns (None, None) if no embeddings found or Annoy unavailable.
    """
    if not HAS_ANNOY or not mem_list:
        return None, None
    
    # Find first entry with embedding to detect dimension
    d = None
    for m in mem_list:
        emb = m.get("embedding")
        if emb and isinstance(emb, list) and len(emb) > 0:
            d = len(emb)
            break
    
    if d is None:
        if DEBUG:
            print("[DEBUG] build_annoy_index: no embeddings found in memory")
        return None, None
    
    try:
        index = annoy.AnnoyIndex(d, 'angular')
        id_map = {}  # maps Annoy idx -> memory list index
        
        for mem_idx, m in enumerate(mem_list):
            emb = m.get("embedding")
            if emb and isinstance(emb, list) and len(emb) == d:
                annoy_idx = index.get_n_items()
                index.add_item(annoy_idx, emb)
                id_map[annoy_idx] = mem_idx
        
        if index.get_n_items() == 0:
            return None, None
        
        index.build(n_trees=10)
        return index, id_map
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] build_annoy_index failed: {e}")
        return None, None


def find_relevant_memories_semantic(question, mem_list, top_k=5, threshold=0.7, pdf_path=None):
    """
    Semantic search using embeddings and Annoy index.
    Falls back to token-overlap if embeddings/index unavailable.
    Returns list of memory entries with similarity scores.
    """
    if not mem_list:
        return []
    
    # Try semantic search first
    if HAS_ANNOY:
        q_vec = get_embedding(question)
        if q_vec is not None:
            index, id_map = build_annoy_index(mem_list)
            if index is not None and id_map:
                try:
                    # Get nearest neighbors (Annoy uses angular distance)
                    annoy_ids, distances = index.get_nns_by_vector(q_vec, top_k, include_distances=True)
                    
                    # Convert angular distance to cosine similarity
                    # For normalized vectors, angular distance d relates to cosine: cos = 1 - d^2/2
                    results = []
                    for annoy_idx, dist in zip(annoy_ids, distances):
                        mem_idx = id_map.get(annoy_idx)
                        if mem_idx is not None:
                            # Angular distance to cosine similarity
                            cos_sim = 1.0 - (dist * dist) / 2.0
                            # Clamp to [0, 1] for safety
                            cos_sim = max(0.0, min(1.0, cos_sim))
                            if cos_sim >= threshold:
                                mem_entry = mem_list[mem_idx].copy()
                                mem_entry["_similarity"] = cos_sim
                                results.append(mem_entry)
                    
                    # Sort by similarity descending
                    results.sort(key=lambda x: x.get("_similarity", 0), reverse=True)
                    if results:
                        if DEBUG:
                            print(f"[DEBUG] semantic search found {len(results)} relevant memories")
                        return results
                except Exception as e:
                    if DEBUG:
                        print(f"[DEBUG] semantic search error, falling back: {e}")
    
    # Fallback to token-overlap method
    if DEBUG:
        print("[DEBUG] falling back to token-overlap relevance search")
    return find_relevant_memories(question, pdf_path or "", mem_list, max_results=top_k)


def find_relevant_memories(question, pdf_path, mem_list, max_results=MAX_MEMORY_TO_LOAD):
    """
    Lightweight relevance: prefer exact same pdf path matches first; then simple
    token-overlap between question and memory.question; return up to max_results.
    """
    if not mem_list:
        return []

    # normalize
    q_tokens = set([w.lower() for w in question.split() if len(w) > 2])
    scored = []
    for m in mem_list:
        score = 0
        # exact pdf match strong signal
        if m.get("pdf_path") and os.path.basename(m.get("pdf_path")) == os.path.basename(pdf_path):
            score += 100
        # token overlap
        mq = m.get("question", "")
        mq_tokens = set([w.lower() for w in mq.split() if len(w) > 2])
        overlap = len(q_tokens & mq_tokens)
        score += overlap
        scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [m for s, m in scored if s > 0]
    return results[:max_results]


# --- Helpers: text extraction / chunking ---

def extract_text_from_pdf(path, max_pages=MAX_PAGES):
    reader = PdfReader(path)
    texts = []
    num_pages = min(len(reader.pages), max_pages)
    for i in range(num_pages):
        try:
            page = reader.pages[i]
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
    return "".join(texts)


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP, max_chunks=MAX_CHUNKS):
    if not text:
        return []
    chunks = []
    start = 0
    L = len(text)
    while start < L and len(chunks) < max_chunks:
        end = start + size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        # step forward but keep overlap
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


# --- Helpers: Bedrock request/response parsing ---

def _prepare_native_request(prompt):
    if "llama" in MODEL_ID.lower():
        return {
            "prompt": prompt,
            "max_gen_len": LLAMA_MAX_GEN,
            "temperature": 0.2,
            "top_p": 0.95
        }
    elif "claude" in MODEL_ID.lower():
        return {
            "prompt": prompt,
            "max_tokens_to_sample": CLAUDE_MAX_TOKENS
        }
    else:
        return {"prompt": prompt}


def _read_response_body(response):
    raw_body = response.get("body")
    if hasattr(raw_body, "read"):
        raw_str = raw_body.read().decode("utf-8")
    elif isinstance(raw_body, (bytes, bytearray)):
        raw_str = raw_body.decode("utf-8")
    else:
        raw_str = str(raw_body)
    return raw_str


def _parse_model_text(raw_str):
    """
    Parse model response and extract plain text, handling JSON-wrapped responses.
    Always returns plain text string (not JSON).
    """
    if not raw_str:
        return ""
    
    # Try to parse as JSON
    try:
        parsed = json.loads(raw_str)
    except Exception:
        # Not JSON, return as-is (already plain text)
        return raw_str.strip()

    if isinstance(parsed, dict):
        # Check for "generation" field (common in some models)
        if "generation" in parsed:
            gen = parsed["generation"]
            if isinstance(gen, str):
                return gen.strip()
            elif isinstance(gen, dict):
                if "content" in gen:
                    return str(gen["content"]).strip()
                if "candidates" in gen and isinstance(gen["candidates"], list):
                    texts = [c.get("content", "") if isinstance(c, dict) else str(c) for c in gen["candidates"]]
                    return "\n".join([t.strip() for t in texts if t]).strip()
            elif isinstance(gen, list):
                texts = []
                for item in gen:
                    if isinstance(item, dict):
                        texts.append(item.get("content", ""))
                    else:
                        texts.append(str(item))
                return "\n".join([t.strip() for t in texts if t]).strip()
        
        # Check for "output" field
        if "output" in parsed:
            out = parsed["output"]
            if isinstance(out, str):
                return out.strip()
            if isinstance(out, dict):
                return (out.get("text") or out.get("content") or "").strip()
            if isinstance(out, list):
                return "\n".join([str(x).strip() for x in out]).strip()
        
        # Check common text fields (only return if value is non-empty)
        for key in ["text", "content", "answer", "response"]:
            if key in parsed:
                val = parsed[key]
                if isinstance(val, str) and val.strip():
                    return val.strip()
                elif isinstance(val, (dict, list)):
                    # Nested structure, try to extract text
                    continue
        
        # If still a dict and we haven't found text, return empty or first string value
        for val in parsed.values():
            if isinstance(val, str) and val.strip():
                return val.strip()
    
    elif isinstance(parsed, str):
        return parsed.strip()
    elif isinstance(parsed, list):
        # List of strings or objects
        texts = [str(x).strip() for x in parsed if x]
        return "\n".join(texts).strip()
    
    # Fallback: return empty string rather than JSON dump
    return ""


def call_bedrock(prompt, model_id=MODEL_ID, region=REGION):
    """
    Synchronous (non-streaming) call to Bedrock. Returns clean plain text (not JSON).
    """
    client = boto3.client("bedrock-runtime", region_name=region)
    native_req = _prepare_native_request(prompt)
    request_body = json.dumps(native_req)

    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=request_body
    )

    raw_str = _read_response_body(response)
    if DEBUG:
        print(f"\n[DEBUG] raw model response:\n{raw_str}\n")

    parsed_text = _parse_model_text(raw_str)
    # Ensure we return clean text, strip any remaining whitespace
    return parsed_text.strip() if parsed_text else ""


def call_bedrock_stream(prompt, model_id=MODEL_ID, region=REGION):
    """
    Streaming call to Bedrock. Returns full collected clean text after streaming.
    Extracts model-generated text from JSON-wrapped chunks and prints tokens live.
    """
    client = boto3.client("bedrock-runtime", region_name=region)
    native_req = _prepare_native_request(prompt)
    request_body = json.dumps(native_req)

    # Fallback: if streaming not available, use non-streaming
    if not hasattr(client, "invoke_model_with_response_stream"):
        if DEBUG:
            print("[DEBUG] streaming API not available on client; falling back to invoke_model")
        return call_bedrock(prompt, model_id=model_id, region=region)

    response = client.invoke_model_with_response_stream(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=request_body
    )

    stream = response.get("body")
    final_text = ""
    json_chunks = []  # Collect JSON chunks for parsing if needed

    # The stream yields events that may contain nested JSON; we try to robustly extract
    # textual tokens. This implementation extracts text from JSON-wrapped responses.
    try:
        for event in stream:
            try:
                if isinstance(event, (bytes, bytearray)):
                    decoded = event.decode("utf-8")
                    json_chunks.append(decoded)
                    # Try to parse immediately
                    try:
                        parsed = json.loads(decoded)
                        text_piece = _parse_model_text(decoded)
                        if text_piece:
                            print(text_piece, end="", flush=True)
                            final_text += text_piece
                    except Exception:
                        # Not JSON, might be raw text
                        if decoded.strip():
                            print(decoded, end="", flush=True)
                            final_text += decoded
                    continue
                elif isinstance(event, dict):
                    parsed = event
                else:
                    # Unknown type, stringify
                    chunk_text = str(event)
                    if chunk_text.strip():
                        print(chunk_text, end="", flush=True)
                        final_text += chunk_text
                    continue

                # Attempt to extract textual content from parsed event
                text_piece = None
                
                # Check for nested chunk structure
                if "chunk" in parsed and isinstance(parsed["chunk"], dict):
                    c = parsed["chunk"]
                    if "bytes" in c:
                        try:
                            decoded_bytes = c["bytes"].decode("utf-8")
                            text_piece = _parse_model_text(decoded_bytes)
                        except Exception:
                            pass
                
                # Check for "generation" field in parsed event
                if not text_piece and "generation" in parsed:
                    gen = parsed["generation"]
                    if isinstance(gen, str):
                        text_piece = gen
                    elif isinstance(gen, dict) and "content" in gen:
                        text_piece = gen["content"]
                
                # Fallback to common text fields
                if not text_piece:
                    for key in ["text", "content", "body", "data"]:
                        if key in parsed and isinstance(parsed[key], str) and parsed[key].strip():
                            text_piece = parsed[key]
                            break
                
                # If still no text, try parsing the whole event as JSON string
                if not text_piece:
                    try:
                        event_str = json.dumps(parsed)
                        text_piece = _parse_model_text(event_str)
                    except Exception:
                        pass

                if text_piece and text_piece.strip():
                    print(text_piece, end="", flush=True)
                    final_text += text_piece
                    
            except Exception as e:
                if DEBUG:
                    print(f"[DEBUG] error processing stream event: {e}")
                continue
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] streaming loop terminated with error: {e}")

    print()  # newline after stream
    
    # Final cleanup: if we collected JSON chunks, try parsing the concatenated result
    if not final_text.strip() and json_chunks:
        try:
            combined = "".join(json_chunks)
            final_text = _parse_model_text(combined)
        except Exception:
            pass
    
    return final_text.strip() if final_text else ""


# --- Prompt utilities ---

def make_chunk_prompt(chunk, question, idx, total):
    prompt = (
        "<|begin_of_text|>"
        "<|start_header_id|>user<|end_header_id|>
"
        "You are an expert analyst. Answer the question using ONLY the text in this chunk.

"
        f"CHUNK {idx}/{total}:
{chunk}

"
        "QUESTION:
"
        f"{question}

"
        "INSTRUCTIONS:
"
        "- If the chunk does not contain information that answers the question, reply exactly: NOT RELEVANT
"
        "- Otherwise: give a short partial answer (1-3 sentences) and one-line rationale pointing to the chunk.
"
        "<|eot_id|>
"
        "<|start_header_id|>assistant<|end_header_id|>"
    )
    return prompt


def make_synthesis_prompt(partials, question, prior_memory_text=None):
    joined = "

".join([f"PARTIAL {i+1}: {p}" for i, p in enumerate(partials)])
    mem_section = ""
    if prior_memory_text:
        mem_section = f"PAST INTERACTIONS:
{prior_memory_text}

"
    prompt = (
        "<|begin_of_text|>"
        "<|start_header_id|>user<|end_header_id|>
"
        "You are a senior researcher tasked with combining partial answers into a single clear answer.

"
        f"{mem_section}"
        "PARTIAL ANSWERS:
"
        f"{joined}

"
        "INSTRUCTIONS:
"
        "- Merge the partials into one final answer. If the partials disagree, explain uncertainty.
"
        "- If none of the partials contain an answer, say 'Not found in document'.

"
        "FINAL QUESTION:
"
        f"{question}

"
        "FINAL ANSWER:
"
        "<|eot_id|>
"
        "<|start_header_id|>assistant<|end_header_id|>"
    )
    return prompt


# --- Main flow ---

def main():
    if len(sys.argv) < 3:
        print("Usage: python local_pdf_qa.py path/to/file.pdf \"Your question here\"")
        sys.exit(2)

    pdf_path = sys.argv[1]
    question = sys.argv[2]

    if not os.path.exists(pdf_path):
        print("PDF file not found:", pdf_path)
        sys.exit(1)

    # Load memory and check for relevant prior Q&As using semantic search
    memory = load_memory()
    relevant = find_relevant_memories_semantic(question, memory, top_k=MAX_MEMORY_TO_LOAD, pdf_path=pdf_path)
    if relevant:
        print(f"Found {len(relevant)} relevant past interaction(s). They will be included in synthesis.")
    prior_mem_text = "\n".join([f"Q: {m.get('question')}\nA: {m.get('answer')}" for m in relevant]) if relevant else None

    print("Extracting text from PDF (first few pages)...")
    doc_text = extract_text_from_pdf(pdf_path)

    if not doc_text.strip():
        print("No text could be extracted from the PDF. Try a different file or run OCR first.")
        sys.exit(1)

    chunks = chunk_text(doc_text)
    total = len(chunks)
    print(f"Document split into {total} chunks (CHUNK_SIZE={CHUNK_SIZE}, OVERLAP={CHUNK_OVERLAP}).")

    partials = []
    for i, chunk in enumerate(chunks, start=1):
        print(f"Querying chunk {i}/{total}...")
        prompt = make_chunk_prompt(chunk, question, i, total)
        try:
            # Use streaming where available to show progressive output for each chunk
            resp = call_bedrock_stream(prompt)
        except Exception as e:
            print(f"Error calling model on chunk {i}: {e}")
            try:
                resp = call_bedrock(prompt)
            except Exception as e2:
                print(f"Fallback error on chunk {i}: {e2}")
                continue

        resp_text = resp.strip() if isinstance(resp, str) else str(resp)
        if DEBUG:
            print(f"[DEBUG] chunk {i} response:
{resp_text}
")

        if resp_text.upper().strip().startswith("NOT RELEVANT"):
            if DEBUG:
                print(f"Chunk {i} marked not relevant.")
            continue

        partials.append(resp_text)


    if not partials:
        print("No relevant information found across chunks.")
        final_answer = "Not found in document"
    else:
        print("Synthesizing final answer from partials...")
        synth_prompt = make_synthesis_prompt(partials, question, prior_mem_text)
        # stream the final synthesis
        final_answer = call_bedrock_stream(synth_prompt)
        if not final_answer or not final_answer.strip():
            final_answer = "Not found in document"

    print("
=== FINAL ANSWER ===
")
    print(final_answer)
    print("
=== END ===
")

    # Save to memory (append) - always save if SAVE_MEMORY is enabled
    if SAVE_MEMORY:
        # Compute embedding for the final answer
        embedding = get_embedding(final_answer)
        if embedding is None and DEBUG:
            print("[DEBUG] failed to generate embedding for memory entry; entry will be saved without embedding")
        
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "pdf_path": os.path.abspath(pdf_path),
            "question": question,
            "answer": final_answer,
            "partials": partials,
            "model_id": MODEL_ID,
            "embedding": embedding  # None if embedding generation failed
        }
        append_memory(entry)
        if DEBUG:
            emb_status = f"with embedding (dim={len(embedding)})" if embedding else "without embedding"
            print(f"[DEBUG] saved memory entry with id {entry['id']} {emb_status}")


if __name__ == "__main__":
    main()
