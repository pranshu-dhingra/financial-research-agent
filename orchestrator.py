#!/usr/bin/env python3
"""
orchestrator.py - BFSI Research Assistant Orchestrator

Coordinates the full RAG workflow with partial external completion.
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add current dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_pdf_qa import (
    load_memory_for_pdf,
    find_relevant_memories_semantic,
    extract_text_from_pdf,
    chunk_text,
    call_bedrock_stream,
    make_chunk_prompt,
    make_synthesis_prompt,
    make_partial_completion_synthesis_prompt,
    is_answer_incomplete,
    extract_missing_slots,
    get_embedding,
    append_memory_for_pdf,
)
from verifier import verifier_agent
import uuid

DEBUG = os.environ.get("DEBUG", "0") == "1"
ENABLE_TOOL_PLANNER = os.environ.get("ENABLE_TOOL_PLANNER", "0") == "1"
SAVE_MEMORY = os.environ.get("SAVE_MEMORY", "1") != "0"
MAX_MEMORY_TO_LOAD = int(os.environ.get("MAX_MEMORY_TO_LOAD", 5))


def is_internal_partial(partials, answer_text, provenance):
    """
    Returns True if internal evidence is partial.
    - Some chunks relevant but key fields missing
    - Answer contains "not provided", "no information", "cannot compare"
    - Retriever similarity exists but < 0.8
    """
    if not partials:
        return True
    
    answer_lower = answer_text.lower()
    partial_phrases = ["not provided", "no information available", "cannot compare", "not found"]
    if any(phrase in answer_lower for phrase in partial_phrases):
        return True
    
    # Check similarity
    similarities = [p.get("similarity", 0.0) for p in provenance if p.get("type") == "internal"]
    if similarities and max(similarities) < 0.8:
        return True
    
    return False


def missing_entities_detected(query, partials):
    """
    Returns True if query mentions entities not present in internal chunks.
    """
    import re
    query_entities = set(re.findall(r'\b[A-Z][a-z]+\b', query))  # Simple proper nouns
    partials_text = " ".join(partials).lower()
    missing = [e for e in query_entities if e.lower() not in partials_text]
    return len(missing) > 0


def run_workflow(question: str, pdf_path: str, use_streaming: bool = True) -> dict:
    """
    Full workflow: internal RAG + partial external completion + verification.
    
    Args:
        question: User query
        pdf_path: Path to PDF file
        use_streaming: Whether to use streaming (currently not actively used)
    
    Returns:
        dict with keys:
        - answer: Final answer string
        - provenance: List of source items with type, source, text, similarity
        - confidence: Confidence score 0.0-1.0
        - flags: List of flag strings (e.g., "PARTIAL_EXTERNAL_COMPLETION")
    """
    provenance = []
    
    # Load memory
    memory = load_memory_for_pdf(pdf_path)
    relevant = find_relevant_memories_semantic(
        question, memory, top_k=MAX_MEMORY_TO_LOAD, pdf_path=pdf_path
    )
    prior_mem_text = "\n".join(f"Q: {m.get('question')}\nA: {m.get('answer')}" for m in relevant) if relevant else None
    
    # Add memory to provenance
    for m in relevant:
        provenance.append({
            "type": "internal",
            "source": os.path.basename(pdf_path),
            "page": m.get("page"),
            "text": m.get("answer", ""),
            "similarity": m.get("_similarity", 0.0),
        })
    
    # Extract PDF and get partials
    doc_text = extract_text_from_pdf(pdf_path)
    partials = []
    if doc_text.strip():
        chunks = chunk_text(doc_text)
        for i, chunk in enumerate(chunks, 1):
            try:
                resp = call_bedrock_stream(make_chunk_prompt(chunk, question, i, len(chunks)))
            except Exception as e:
                if DEBUG:
                    print(f"[DEBUG] chunk {i} failed: {e}")
                continue
            resp_text = (resp or "").strip()
            if resp_text.upper().startswith("NOT RELEVANT"):
                continue
            partials.append(resp_text)
            # Add chunk provenance
            provenance.append({
                "type": "internal",
                "source": os.path.basename(pdf_path),
                "page": i,  # Approximate
                "text": resp_text,
            })
    
    if not partials:
        # No internal evidence, force external lookup via SerpAPI
        external_context = None
        external_provenance = []
        if os.environ.get("ENABLE_TOOL_PLANNER", "0") == "1":
            try:
                import tools
                print(f"[DEBUG] No internal evidence, calling SerpAPI directly for: {question}")
                # Call SerpAPI directly without planner (bypass planner's conservative logic)
                external_context, external_provenance = tools.run_external_search_forced(
                    question, call_llm_fn=call_bedrock_stream
                )
                if external_context and external_context.strip():
                    print("External data retrieved.")
                    # Synthesize from external only
                    final_answer = call_bedrock_stream(
                        make_synthesis_prompt([external_context], question, prior_mem_text, external_context=None, external_provenance=external_provenance)
                    )
                    if final_answer and final_answer.strip():
                        # Add external provenance
                        for p in external_provenance:
                            provenance.append(p)
                        # Verify
                        verification = verifier_agent(final_answer, provenance, [], external_provenance)
                        # Ensure confidence >= 0.6 for external-only
                        verification["confidence"] = max(verification["confidence"], 0.6)
                        return {
                            "answer": final_answer,
                            "provenance": provenance,
                            "confidence": verification["confidence"],
                            "flags": verification["flags"],
                        }
            except Exception as e:
                print(f"[DEBUG] external lookup failed: {e}")
                import traceback
                traceback.print_exc()
        # Fallback
        return {
            "answer": "Not found in document",
            "provenance": provenance,
            "confidence": 0.0,
            "flags": ["NO_INTERNAL_EVIDENCE"],
        }
    
    # Synthesize internal answer
    internal_answer = call_bedrock_stream(
        make_synthesis_prompt(partials, question, prior_mem_text, external_context=None, external_provenance=None)
    )
    if not (internal_answer or internal_answer.strip()):
        internal_answer = "Not found in document"
    
    # Check for incompleteness
    internal_partial = is_internal_partial(partials, internal_answer, provenance)
    missing_entities = missing_entities_detected(question, partials)
    print(f"[DEBUG] internal_partial: {internal_partial}, missing_entities: {missing_entities}, ENABLE_TOOL_PLANNER: {ENABLE_TOOL_PLANNER}")
    
    external_context = None
    external_provenance = []
    
    if (internal_partial or missing_entities) and os.environ.get("ENABLE_TOOL_PLANNER", "0") == "1":
        try:
            import tools
            print(f"[DEBUG] Calling SerpAPI for original query: {question}")
            plan = tools.tool_planner_agent(question, call_llm_fn=call_bedrock_stream)
            providers = plan.get("recommended_providers", [])
            print(f"[DEBUG] Recommended providers: {providers}")
            if providers:
                print("Fetching external data...")
                external_context, external_provenance = tools.run_external_search(
                    question, call_llm_fn=call_bedrock_stream
                )
                if external_context and external_context.strip():
                    print("External data retrieved.")
                    # Re-synthesize with external
                    final_answer = call_bedrock_stream(
                        make_partial_completion_synthesis_prompt(
                            partials, [external_context], question, prior_mem_text
                        )
                    )
                    if final_answer and final_answer.strip():
                        internal_answer = final_answer
                    # Add external provenance
                    for p in external_provenance:
                        provenance.append(p)
        except Exception as e:
            print(f"[DEBUG] external augmentation failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Verify and get confidence
    flags = []
    if internal_partial or missing_entities:
        flags.append("PARTIAL_EXTERNAL_COMPLETION")
    
    verification = verifier_agent(internal_answer, provenance, partials, external_provenance, flags_override=flags)
    
    # Save to memory
    if SAVE_MEMORY:
        embedding = get_embedding(internal_answer)
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "pdf_path": os.path.abspath(pdf_path),
            "question": question,
            "answer": internal_answer,
            "partials": partials,
            "model_id": "orchestrator",
            "embedding": embedding,
        }
        append_memory_for_pdf(entry, pdf_path)
    
    return {
        "answer": internal_answer,
        "provenance": provenance,
        "confidence": verification["confidence"],
        "flags": verification["flags"],
    }


def run_workflow_stream(question: str, pdf_path: str) -> str:
    """Streaming version for UI consumption."""
    result = run_workflow(question, pdf_path, use_streaming=True)
    return result