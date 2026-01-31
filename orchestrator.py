#!/usr/bin/env python3
"""
orchestrator.py - BFSI Research Orchestrator with Multi-Agent Workflow

Coordinates: Classifier -> Retriever -> Tool Agent -> Synthesizer -> Verifier
Epistemic contract: Query Classification, Source Attribution, Confidence Scoring
"""

import os
import uuid
from datetime import datetime

DEBUG = os.environ.get("DEBUG", "0") == "1"
INTERNAL_CONF_THRESHOLD = float(os.environ.get("INTERNAL_CONF_THRESHOLD", "0.75"))
ENABLE_TOOL_AGENT = os.environ.get("ENABLE_TOOL_PLANNER", "0") == "1"


def _ts():
    return datetime.utcnow().isoformat() + "Z"


def _call_llm():
    from local_pdf_qa import call_bedrock, call_bedrock_stream
    return call_bedrock, call_bedrock_stream


def classifier_agent(query: str, pdf_path: str) -> dict:
    """
    Decide if internal knowledge sufficient or external needed.
    Returns: {internal_sufficient, external_needed, reason}
    """
    from local_pdf_qa import extract_text_from_pdf, chunk_text, find_relevant_chunks

    doc_text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(doc_text)
    if not chunks:
        return {
            "internal_sufficient": False,
            "external_needed": True,
            "reason": "No chunks extracted from PDF",
        }
    relevant = find_relevant_chunks(query, chunks, top_k=5, threshold=0.3)
    max_sim = max((r["similarity"] for r in relevant), default=0.0)
    internal_sufficient = max_sim >= INTERNAL_CONF_THRESHOLD
    external_needed = not internal_sufficient
    reason = f"max_similarity={max_sim:.2f} vs threshold={INTERNAL_CONF_THRESHOLD}"
    return {
        "internal_sufficient": internal_sufficient,
        "external_needed": external_needed,
        "reason": reason,
    }


def retriever_agent(query: str, pdf_path: str, use_streaming: bool = True) -> list:
    """
    Retrieve relevant chunks and produce partial answers.
    Returns list of {text, chunk_text, page, similarity}
    """
    from local_pdf_qa import (
        extract_text_from_pdf,
        chunk_text,
        find_relevant_chunks,
        make_chunk_prompt,
    )

    doc_text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(doc_text)
    if not chunks:
        return []
    relevant = find_relevant_chunks(query, chunks, top_k=10, threshold=0.3)
    if not relevant:
        return []
    call_sync, call_stream = _call_llm()
    call_fn = call_stream if use_streaming else call_sync
    partials = []
    for r in relevant:
        idx = r["idx"]
        chunk = r["chunk_text"]
        sim = r["similarity"]
        prompt = make_chunk_prompt(chunk, query, idx + 1, len(chunks))
        try:
            resp = call_fn(prompt)
        except Exception:
            resp = call_sync(prompt)
        resp_text = (resp or "").strip()
        if resp_text.upper().startswith("NOT RELEVANT"):
            continue
        partials.append({
            "text": resp_text,
            "chunk_text": chunk[:500],
            "page": None,
            "similarity": sim,
        })
    return partials


def tool_agent(query: str, input_fn=None) -> tuple:
    """
    Execute external tools via Tool Planner.
    Returns (external_text, external_provenance_list)
    """
    try:
        import tools
        call_bedrock, _ = _call_llm()
        plan = tools.tool_planner_agent(query, call_llm_fn=call_bedrock)
        providers = plan.get("recommended_providers", [])
        if not providers:
            return "", []
        resolved = tools.resolve_tool_credentials(plan, input_fn=input_fn)
        ready = resolved.get("ready_providers", [])
        if not ready:
            return "", []
        category = plan.get("category", "generic")
        snippets = tools.execute_external_tools(ready, query, category)
        text_parts = [s.get("text", "") for s in snippets if s.get("text")]
        return "\n\n".join(text_parts), snippets
    except ImportError:
        return "", []
    except Exception as e:
        if DEBUG:
            print(f"[ORCHESTRATOR] tool_agent failed: {e}")
        return "", []


def synthesizer_agent(
    partials: list,
    external_snippets: list,
    prior_mem_text: str | None,
    question: str,
    use_streaming: bool = True,
) -> dict:
    """
    Merge internal partials + external evidence. Labels [INTERNAL]/[EXTERNAL].
    Returns: {answer, provenance}
    """
    from local_pdf_qa import call_bedrock, call_bedrock_stream

    if not partials and not external_snippets:
        return {
            "answer": "Insufficient evidence. No relevant internal or external sources found.",
            "provenance": [],
        }
    partial_texts = [p.get("text", p) if isinstance(p, dict) else str(p) for p in partials]
    if not partial_texts and external_snippets:
        partial_texts = [s.get("text", "") for s in external_snippets if s.get("text")]
    external_context = "\n\n".join(s.get("text", "") for s in external_snippets if s.get("text"))
    prompt = (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are synthesizing an investment research answer.\n"
        "Label every factual sentence as [INTERNAL] or [EXTERNAL].\n"
        "Cite page numbers or URLs where applicable.\n"
        "If evidence insufficient, say so. Do not invent facts.\n\n"
    )
    if prior_mem_text:
        prompt += f"PAST INTERACTIONS:\n{prior_mem_text}\n\n"
    if external_context:
        prompt += f"EXTERNAL CONTEXT:\n{external_context}\n\n"
    prompt += "PARTIAL ANSWERS:\n"
    for i, p in enumerate(partial_texts, 1):
        prompt += f"\nPARTIAL {i}: {p}"
    prompt += f"\n\nFINAL QUESTION:\n{question}\n\nFINAL ANSWER:\n"
    prompt += "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    call_sync, call_stream = _call_llm()
    call_fn = call_stream if use_streaming else call_sync
    try:
        answer = call_fn(prompt)
    except Exception:
        answer = call_sync(prompt)
    answer = (answer or "").strip()
    if not answer:
        answer = "Insufficient evidence. No relevant internal or external sources found."
    provenance = []
    for p in partials:
        if isinstance(p, dict):
            provenance.append({
                "type": "internal",
                "source": "pdf",
                "page": p.get("page"),
                "tool": None,
                "category": None,
                "text": p.get("text", "")[:500],
                "similarity": p.get("similarity"),
            })
    for s in external_snippets:
        provenance.append({
            "type": "external",
            "source": s.get("url", ""),
            "page": None,
            "tool": s.get("tool"),
            "category": s.get("category"),
            "text": s.get("text", "")[:500],
            "similarity": None,
        })
    return {"answer": answer, "provenance": provenance}


def verifier_agent(answer: str, provenance: list) -> dict:
    """
    Compute confidence score from internal similarity and external corroboration.
    Returns: {confidence, flags}
    """
    max_internal_sim = 0.0
    internal_count = 0
    external_count = 0
    for p in provenance:
        if p.get("type") == "internal":
            internal_count += 1
            sim = p.get("similarity")
            if sim is not None:
                max_internal_sim = max(max_internal_sim, sim)
        elif p.get("type") == "external":
            external_count += 1
    external_bonus = 0.3 if external_count > 0 else 0.0
    verifier_checks = 0.1
    if "insufficient" in answer.lower() or "not found" in answer.lower():
        verifier_checks = 0.0
    confidence = 0.6 * max_internal_sim + external_bonus + verifier_checks
    confidence = max(0.0, min(1.0, confidence))
    flags = []
    if internal_count == 0 and external_count == 0:
        flags.append("no_sources")
    if max_internal_sim < 0.5 and external_count == 0:
        flags.append("low_internal_confidence")
    return {"confidence": confidence, "flags": flags}


def run_workflow(query: str, pdf_path: str, use_streaming: bool = True) -> dict:
    """
    Central orchestrator: Classifier -> Retriever -> Tool (if needed) -> Synthesizer -> Verifier.
    Returns: {answer, confidence, provenance, trace}
    """
    trace = []
    call_bedrock, _ = _call_llm()

    cls = classifier_agent(query, pdf_path)
    trace.append({"agent": "classifier", "decision": cls.get("reason", ""), "timestamp": _ts()})
    if DEBUG:
        print(f"[ORCHESTRATOR] classifier: internal_sufficient={cls.get('internal_sufficient')}")

    partials = retriever_agent(query, pdf_path, use_streaming=use_streaming)
    trace.append({"agent": "retriever", "chunks": len(partials), "timestamp": _ts()})

    external_text = ""
    external_provenance = []
    tool_plan = None
    if ENABLE_TOOL_AGENT and cls.get("external_needed", True):
        try:
            import tools
            tool_plan = tools.tool_planner_agent(query, call_llm_fn=call_bedrock)
            providers = tool_plan.get("recommended_providers", [])
            if providers:
                trace.append({
                    "agent": "tool_planner",
                    "category": tool_plan.get("category"),
                    "providers": providers,
                    "timestamp": _ts(),
                })
                external_text, external_provenance = tool_agent(query)
        except Exception as e:
            if DEBUG:
                print(f"[ORCHESTRATOR] tool_planner failed: {e}")
    if tool_plan is None:
        trace.append({
            "agent": "tool_planner",
            "category": "skipped",
            "providers": [],
            "timestamp": _ts(),
        })

    from local_pdf_qa import load_memory_for_pdf, find_relevant_memories_semantic
    memory = load_memory_for_pdf(pdf_path)
    relevant_mem = find_relevant_memories_semantic(query, memory, top_k=5, pdf_path=pdf_path)
    prior_mem_text = None
    if relevant_mem:
        prior_mem_text = "\n".join(
            f"Q: {m.get('question')}\nA: {m.get('answer')}" for m in relevant_mem
        )

    synth_input_partials = partials
    if not partials and external_provenance:
        synth_input_partials = [{"text": s.get("text", "")} for s in external_provenance]
    synth = synthesizer_agent(
        synth_input_partials,
        external_provenance,
        prior_mem_text,
        query,
        use_streaming=use_streaming,
    )
    trace.append({"agent": "synthesizer", "notes": "merged internal + external", "timestamp": _ts()})

    ver = verifier_agent(synth["answer"], synth["provenance"])
    trace.append({"agent": "verifier", "confidence": ver["confidence"], "timestamp": _ts()})

    provenance = synth["provenance"]
    for p in provenance:
        p.setdefault("type", "internal")
        p.setdefault("source", "pdf")
        p.setdefault("page", None)
        p.setdefault("tool", None)
        p.setdefault("category", None)
        p.setdefault("text", "")
        p.setdefault("similarity", None)

    result = {
        "answer": synth["answer"],
        "confidence": ver["confidence"],
        "provenance": provenance,
        "trace": trace,
    }

    if os.environ.get("SAVE_MEMORY", "1") != "0":
        from local_pdf_qa import get_embedding, append_memory_for_pdf
        emb = get_embedding(synth["answer"])
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": _ts(),
            "pdf_path": os.path.abspath(pdf_path),
            "question": query,
            "answer": synth["answer"],
            "confidence": ver["confidence"],
            "provenance": provenance,
            "embedding": emb,
            "model_id": os.environ.get("MODEL_ID", "us.meta.llama3-3-70b-instruct-v1:0"),
        }
        append_memory_for_pdf(entry, pdf_path)

    return result
