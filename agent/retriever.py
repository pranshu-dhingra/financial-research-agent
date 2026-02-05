"""Chunk and memory retrieval."""

import os
from core import get_embedding
from config import DEBUG


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


def find_relevant_chunks_token(query: str, chunks: list, top_k: int = 3, threshold: float = 0.0):
    """
    Fast local token-overlap relevance. No API calls.
    Returns list of {chunk_text, idx, similarity} sorted by similarity.
    Similarity = |query_tokens ∩ chunk_tokens| / max(1, |query_tokens|), range 0-1.
    """
    if not chunks:
        return []
    q_tokens = set(w.lower() for w in query.split() if len(w) > 2)
    if not q_tokens:
        return []
    scored = []
    for i, chunk in enumerate(chunks):
        c_tokens = set(w.lower() for w in chunk.split() if len(w) > 2)
        overlap = len(q_tokens & c_tokens)
        sim = overlap / max(1, len(q_tokens))
        sim = max(0.0, min(1.0, sim))
        if sim >= threshold:
            scored.append({"chunk_text": chunk, "idx": i, "similarity": sim})
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


def find_relevant_memories_semantic(question, mem_list, top_k=5, threshold=0.7, pdf_path=None):
    """Semantic search via embeddings + Annoy. Falls back to token-overlap only if embeddings fail."""
    if not mem_list:
        return []
    q_vec = get_embedding(question)
    if q_vec is not None:
        index, id_map = _build_annoy_index(mem_list)
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


def _build_annoy_index(mem_list):
    """Build Annoy index from memories with embeddings. Returns (index, id_map) or (None, None)."""
    try:
        import annoy
        import numpy as np
    except ImportError:
        return None, None
    
    if not mem_list:
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
