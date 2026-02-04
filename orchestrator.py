#!/usr/bin/env python3
"""
orchestrator.py - BFSI Research Orchestrator with Multi-Agent Workflow

Coordinates: Classifier -> Retriever -> Tool Agent -> Synthesizer -> Verifier
Epistemic contract: Query Classification, Source Attribution, Confidence Scoring
"""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime

DEBUG = os.environ.get("DEBUG", "0") == "1"
INTERNAL_CONF_THRESHOLD = float(os.environ.get("INTERNAL_CONF_THRESHOLD", "0.70"))
ENABLE_TOOL_AGENT = os.environ.get("ENABLE_TOOL_PLANNER", "0") == "1"
ENABLE_RERANKER = os.environ.get("ENABLE_RERANKER", "0") == "1"

# Streaming defaults
DEFAULT_MAX_CHUNKS = 5
DEFAULT_TOOL_TIMEOUT = 10
DEFAULT_TOTAL_TIMEOUT = 20
MAX_TOTAL_TIME = 30  # Global watchdog: never exceed
FAILSAFE_ANSWER = "System could not retrieve sufficient evidence for this query."


def _ts():
    return datetime.utcnow().isoformat() + "Z"


def _call_llm():
    from local_pdf_qa import call_bedrock, call_bedrock_stream
    return call_bedrock, call_bedrock_stream


def classifier_agent(query: str, pdf_path: str) -> dict:
    """
    Fast local classifier. No LLM or embedding API calls.
    Uses token-overlap similarity only.
    Returns: {internal_sufficient, external_needed, reason}
    """
    from local_pdf_qa import extract_text_from_pdf, chunk_text, find_relevant_chunks_token

    doc_text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(doc_text)
    if not chunks:
        if DEBUG:
            print("[CLASSIFIER] No chunks → external required")
        return {
            "internal_sufficient": False,
            "external_needed": True,
            "reason": "No chunks extracted from PDF",
        }
    results = find_relevant_chunks_token(query, chunks, top_k=3)
    if not results:
        if DEBUG:
            print("[CLASSIFIER] max_similarity=0.00 → external required")
        return {
            "internal_sufficient": False,
            "external_needed": True,
            "reason": "No relevant internal chunks",
        }
    max_sim = max(r["similarity"] for r in results)
    internal_sufficient = max_sim >= INTERNAL_CONF_THRESHOLD
    external_needed = not internal_sufficient
    if internal_sufficient:
        if DEBUG:
            print(f"[CLASSIFIER] max_similarity={max_sim:.2f} → internal sufficient")
    else:
        if DEBUG:
            print(f"[CLASSIFIER] max_similarity={max_sim:.2f} → external required")
    return {
        "internal_sufficient": internal_sufficient,
        "external_needed": external_needed,
        "reason": f"max_similarity={max_sim:.2f} vs threshold={INTERNAL_CONF_THRESHOLD}",
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
    internal_facts: list,
    external_facts: list,
    memory_facts: list,
    question: str,
    use_streaming: bool = True,
    variation: str | None = None,
) -> dict:
    """
    Merge internal facts + external evidence + prior memory into one answer.
    LLM does NOT emit provenance labels; provenance is system-enforced by orchestrator.
    Returns: {"answer": ...}
    """
    from local_pdf_qa import call_bedrock, call_bedrock_stream

    if not internal_facts and not external_facts and not memory_facts:
        return {
            "answer": "Insufficient evidence. No relevant internal or external sources found.",
        }

    # Build structured sections for the prompt
    def _fmt_internal():
        lines = []
        for f in internal_facts:
            text = f.get("text", "") or ""
            page = f.get("page")
            sim = f.get("similarity")
            meta_parts = []
            if page is not None:
                meta_parts.append(f"page {page}")
            if sim is not None:
                try:
                    meta_parts.append(f"similarity {float(sim):.2f}")
                except (TypeError, ValueError):
                    pass
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"- {text}{meta}")
        return "\n".join(lines) if lines else "None."

    def _fmt_external():
        lines = []
        for f in external_facts:
            text = f.get("text", "") or ""
            url = f.get("url", "") or ""
            tool = f.get("tool")
            meta_parts = []
            if url:
                meta_parts.append(url)
            if tool:
                meta_parts.append(f"tool={tool}")
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"- {text}{meta}")
        return "\n".join(lines) if lines else "None."

    def _fmt_memory():
        lines = []
        for f in memory_facts:
            text = f.get("text", "") or ""
            ts = f.get("timestamp")
            meta = f" (timestamp {ts})" if ts else ""
            lines.append(f"- {text}{meta}")
        return "\n".join(lines) if lines else "None."

    internal_block = _fmt_internal()
    external_block = _fmt_external()
    memory_block = _fmt_memory()

    prompt = (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are synthesizing a financial research answer.\n"
        "Use ONLY the provided facts.\n"
        "Do NOT add any provenance labels.\n"
        "Do NOT write [INTERNAL] or [EXTERNAL].\n"
        "Just write the answer text.\n"
    )
    if variation:
        prompt += f"\n{variation}\n\n"
    else:
        prompt += "\n\n"
    prompt += "INTERNAL FACTS:\n"
    prompt += internal_block + "\n\n"
    prompt += "EXTERNAL FACTS:\n"
    prompt += external_block + "\n\n"
    prompt += "PRIOR MEMORY:\n"
    prompt += memory_block + "\n\n"
    prompt += f"QUESTION:\n{question}\n\nANSWER:\n"
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
    return {"answer": answer}


def synthesizer_agent_stream(
    internal_facts: list,
    external_facts: list,
    memory_facts: list,
    question: str,
    variation: str | None = None,
):
    """
    Generator: yields {"type":"token","text":piece} for each token from synthesis.
    Does not return; caller accumulates text and builds provenance from partials/external_snippets.
    """
    from local_pdf_qa import call_bedrock_stream_gen, call_bedrock

    if not internal_facts and not external_facts and not memory_facts:
        yield {"type": "token", "text": "Insufficient evidence. No relevant internal or external sources found."}
        return

    def _fmt_internal():
        lines = []
        for f in internal_facts:
            text = f.get("text", "") or ""
            page = f.get("page")
            sim = f.get("similarity")
            meta_parts = []
            if page is not None:
                meta_parts.append(f"page {page}")
            if sim is not None:
                try:
                    meta_parts.append(f"similarity {float(sim):.2f}")
                except (TypeError, ValueError):
                    pass
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"- {text}{meta}")
        return "\n".join(lines) if lines else "None."

    def _fmt_external():
        lines = []
        for f in external_facts:
            text = f.get("text", "") or ""
            url = f.get("url", "") or ""
            tool = f.get("tool")
            meta_parts = []
            if url:
                meta_parts.append(url)
            if tool:
                meta_parts.append(f"tool={tool}")
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"- {text}{meta}")
        return "\n".join(lines) if lines else "None."

    def _fmt_memory():
        lines = []
        for f in memory_facts:
            text = f.get("text", "") or ""
            ts = f.get("timestamp")
            meta = f" (timestamp {ts})" if ts else ""
            lines.append(f"- {text}{meta}")
        return "\n".join(lines) if lines else "None."

    internal_block = _fmt_internal()
    external_block = _fmt_external()
    memory_block = _fmt_memory()
    prompt = (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are synthesizing a financial research answer.\n"
        "Use ONLY the provided facts.\n"
        "Do NOT add any provenance labels.\n"
        "Do NOT write [INTERNAL] or [EXTERNAL].\n"
        "Just write the answer text.\n"
    )
    if variation:
        prompt += f"\n{variation}\n\n"
    else:
        prompt += "\n\n"
    prompt += "INTERNAL FACTS:\n"
    prompt += internal_block + "\n\n"
    prompt += "EXTERNAL FACTS:\n"
    prompt += external_block + "\n\n"
    prompt += "PRIOR MEMORY:\n"
    prompt += memory_block + "\n\n"
    prompt += f"QUESTION:\n{question}\n\nANSWER:\n"
    prompt += "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    try:
        for piece in call_bedrock_stream_gen(prompt):
            if piece:
                yield {"type": "token", "text": piece}
    except Exception:
        fallback = call_bedrock(prompt)
        if fallback:
            yield {"type": "token", "text": fallback}


def _verifier_agent(answer: str, provenance: list, partials: list, external_snippets: list) -> dict:
    """Use verifier.py for BFSI-aware confidence scoring."""
    try:
        from verifier import verifier_agent
        return verifier_agent(answer, provenance, partials, external_snippets)
    except ImportError:
        max_internal_sim = 0.0
        internal_count = sum(1 for p in provenance if p.get("type") == "internal")
        external_count = sum(1 for p in provenance if p.get("type") == "external")
        for p in provenance:
            if p.get("type") == "internal" and p.get("similarity") is not None:
                max_internal_sim = max(max_internal_sim, p["similarity"])
        confidence = 0.6 * max_internal_sim + (0.3 if external_count > 0 else 0) + 0.1
        return {"confidence": min(1.0, confidence), "flags": [], "explanation": ""}


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

    # Build structured fact lists for synthesizer
    internal_facts = []
    for p in partials:
        if isinstance(p, dict):
            internal_facts.append({
                "text": p.get("text", ""),
                "page": p.get("page"),
                "similarity": p.get("similarity"),
            })
    external_facts = []
    for s in external_provenance:
        external_facts.append({
            "text": s.get("text", ""),
            "url": s.get("url", ""),
            "tool": s.get("tool"),
            "category": s.get("category"),
        })
    memory_facts = []
    for m in relevant_mem or []:
        memory_facts.append({
            "text": f"Q: {m.get('question')}\nA: {m.get('answer')}",
            "timestamp": m.get("timestamp"),
        })

    if ENABLE_RERANKER and (synth_input_partials or external_provenance):
        try:
            from reranker import generate_candidate_answers, rank_candidates
            candidates = generate_candidate_answers(
                query, internal_facts, external_facts, memory_facts, n=3
            )
            best_answer = rank_candidates(
                query, candidates,
                provenance=[],
                partials=partials,
                external_snippets=external_provenance,
            )
            synth = {
                "answer": best_answer,
                "provenance": [],  # provenance will be built system-side below
            }
            trace.append({"agent": "synthesizer", "notes": "reranked from 3 candidates", "timestamp": _ts()})
        except ImportError:
            synth = synthesizer_agent(
                internal_facts,
                external_facts,
                memory_facts,
                query,
                use_streaming=use_streaming,
            )
            trace.append({"agent": "synthesizer", "notes": "merged internal + external", "timestamp": _ts()})
    else:
        synth = synthesizer_agent(
            internal_facts,
            external_facts,
            memory_facts,
            query,
            use_streaming=use_streaming,
        )
        trace.append({"agent": "synthesizer", "notes": "merged internal + external", "timestamp": _ts()})

    # System-level provenance injection (authoritative)
    provenance = []
    abs_pdf = os.path.abspath(pdf_path)
    for f in internal_facts:
        provenance.append({
            "type": "internal",
            "source": abs_pdf,
            "page": f.get("page"),
            "tool": None,
            "category": None,
            "text": (f.get("text", "") or "")[:500],
            "similarity": f.get("similarity"),
        })
    for f in external_facts:
        provenance.append({
            "type": "external",
            "source": f.get("url", ""),
            "page": None,
            "tool": f.get("tool"),
            "category": f.get("category"),
            "text": (f.get("text", "") or "")[:500],
            "similarity": None,
        })

    ver = _verifier_agent(
        synth["answer"], provenance, partials, external_provenance
    )
    trace.append({"agent": "verifier", "confidence": ver["confidence"], "timestamp": _ts()})

    flags = ver.get("flags", [])
    result = {
        "answer": synth["answer"],
        "confidence": ver["confidence"],
        "flags": flags,
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
            "flags": flags,
            "provenance": provenance,
            "embedding": emb,
            "model_id": os.environ.get("MODEL_ID", "us.meta.llama3-3-70b-instruct-v1:0"),
        }
        append_memory_for_pdf(entry, pdf_path)

    return result


def safe_stream(generator):
    """
    Wrap generator to guarantee exactly one 'final' event.
    If generator yields nothing or exits without final, emit failsafe final.
    """
    yielded = False
    final_emitted = False
    for event in generator:
        yielded = True
        yield event
        if event.get("type") == "final":
            final_emitted = True
    if not final_emitted:
        yield {
            "type": "final",
            "answer": FAILSAFE_ANSWER,
            "confidence": 0.0,
            "provenance": [],
            "flags": [],
            "trace": [{"agent": "system", "status": "error", "error": "empty generator"}],
            "tool_calls": [],
        }


def _run_with_timeout(fn, timeout_sec, *args, **kwargs):
    """Run fn in thread with timeout. Returns result or raises FuturesTimeoutError."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn, *args, **kwargs)
        return future.result(timeout=timeout_sec)


def _append_trace(trace: list, agent: str, status: str, latency: float):
    """Mandatory trace instrumentation: agent, status, latency, timestamp."""
    trace.append({
        "agent": agent,
        "status": status,
        "latency": round(latency, 3),
        "timestamp": _ts(),
    })


def run_workflow_stream(
    query: str,
    pdf_path: str,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    timeout_sec: int = DEFAULT_TOTAL_TIMEOUT,
):
    """
    Generator: yields structured events for Streamlit-compatible streaming.
    ALWAYS emits exactly one 'final' event (via finally block).
    Events: {"type":"log","message":"..."} | {"type":"token","text":"..."} | {"type":"final",...} | {"type":"error","message":"..."}
    """
    tool_timeout = min(DEFAULT_TOOL_TIMEOUT, timeout_sec - 10)
    step_timeout = max(10, (timeout_sec - tool_timeout) // 4)
    retriever_timeout = min(45, max(step_timeout, timeout_sec - 15))
    budget = min(MAX_TOTAL_TIME, timeout_sec)
    trace = []
    tool_calls = []
    final_answer = FAILSAFE_ANSWER
    confidence = 0.0
    provenance = []
    verifier_flags = []
    classifier_done = False
    retriever_done = False
    tool_done = False
    synth_done = False
    verifier_done = False
    partials = []
    external_provenance = []
    prior_mem_text = None

    def _check_timeout():
        if time.time() - t0 > budget:
            raise TimeoutError("Global timeout")

    try:
        t0 = time.time()
        yield {"type": "log", "message": "Classifying query..."}
        t_classifier = time.time()
        _check_timeout()
        cls = classifier_agent(query, pdf_path)
        classifier_done = True
        _append_trace(trace, "classifier", "ok", time.time() - t_classifier)

        yield {"type": "log", "message": "Retrieving internal chunks..."}
        t_retriever = time.time()
        _check_timeout()
        try:
            partials = _run_with_timeout(
                retriever_agent, retriever_timeout, query, pdf_path,
                **{"use_streaming": False}
            )
            partials = partials[:max_chunks] if partials else []
        except FuturesTimeoutError:
            yield {"type": "error", "message": "System timed out (retriever)"}
            _append_trace(trace, "retriever", "timeout", time.time() - t_retriever)
        else:
            retriever_done = True
            _append_trace(trace, "retriever", "ok", time.time() - t_retriever)

        if classifier_done and ENABLE_TOOL_AGENT and cls.get("external_needed", True):
            yield {"type": "log", "message": "Calling external tools..."}
            t_tool = time.time()
            _check_timeout()
            try:
                import tools
                tool_plan = _run_with_timeout(
                    lambda: tools.tool_planner_agent(query, call_llm_fn=_call_llm()[0]),
                    step_timeout
                )
                _append_trace(trace, "tool_planner", "ok", time.time() - t_tool)
                providers = tool_plan.get("recommended_providers", [])
                if providers:
                    resolved = tools.resolve_tool_credentials(tool_plan, input_fn=lambda: "SKIP")
                    ready = resolved.get("ready_providers", [])
                    tool_calls.extend(ready)
                    if ready:
                        t_exec = time.time()
                        _check_timeout()
                        try:
                            external_text, external_provenance = _run_with_timeout(
                                tool_agent, tool_timeout, query
                            )
                            tool_done = True
                        except FuturesTimeoutError:
                            external_provenance = []
                        _append_trace(trace, "tool_agent", "ok" if tool_done else "timeout", time.time() - t_exec)
            except (FuturesTimeoutError, Exception):
                _append_trace(trace, "tool_planner", "error", time.time() - t_tool)

        from local_pdf_qa import load_memory_for_pdf, find_relevant_memories_semantic
        memory = load_memory_for_pdf(pdf_path)
        relevant_mem = find_relevant_memories_semantic(query, memory, top_k=5, pdf_path=pdf_path)

        # Build structured fact lists for synthesizer
        internal_facts = []
        for p in partials:
            if isinstance(p, dict):
                internal_facts.append({
                    "text": p.get("text", ""),
                    "page": p.get("page"),
                    "similarity": p.get("similarity"),
                })
        external_facts = []
        for s in external_provenance:
            if s.get("error"):
                continue
            external_facts.append({
                "text": s.get("text", ""),
                "url": s.get("url", ""),
                "tool": s.get("tool"),
                "category": s.get("category"),
            })
        memory_facts = []
        for m in relevant_mem or []:
            memory_facts.append({
                "text": f"Q: {m.get('question')}\nA: {m.get('answer')}",
                "timestamp": m.get("timestamp"),
            })

        yield {"type": "log", "message": "Synthesizing answer..."}
        t_synth = time.time()
        _check_timeout()
        answer_acc = ""
        for ev in synthesizer_agent_stream(
            internal_facts, external_facts, memory_facts, query
        ):
            if ev.get("type") == "token":
                answer_acc += ev.get("text", "")
                yield ev
        # System-level provenance injection for streaming path
        provenance = []
        abs_pdf = os.path.abspath(pdf_path)
        for f in internal_facts:
            provenance.append({
                "type": "internal",
                "source": abs_pdf,
                "page": f.get("page"),
                "tool": None,
                "category": None,
                "text": (f.get("text", "") or "")[:500],
                "similarity": f.get("similarity"),
            })
        for f in external_facts:
            provenance.append({
                "type": "external",
                "source": f.get("url", ""),
                "page": None,
                "tool": f.get("tool"),
                "category": f.get("category"),
                "text": (f.get("text", "") or "")[:500],
                "similarity": None,
            })
        synth_done = True
        final_answer = answer_acc.strip() or "Insufficient evidence. No relevant internal or external sources found."
        _append_trace(trace, "synthesizer", "ok", time.time() - t_synth)

        yield {"type": "log", "message": "Verifying answer..."}
        t_verifier = time.time()
        ver = _verifier_agent(final_answer, provenance, partials, external_provenance)
        verifier_done = True
        confidence = ver["confidence"]
        verifier_flags = ver.get("flags", [])
        _append_trace(trace, "verifier", "ok", time.time() - t_verifier)

        yield {"type": "log", "message": "Saving to memory..."}
        t_memory = time.time()
        if os.environ.get("SAVE_MEMORY", "1") != "0":
            try:
                from local_pdf_qa import get_embedding, append_memory_for_pdf
                emb = get_embedding(final_answer)
                entry = {
                    "id": str(uuid.uuid4()),
                    "timestamp": _ts(),
                    "pdf_path": os.path.abspath(pdf_path),
                    "question": query,
                    "answer": final_answer,
                    "confidence": confidence,
                    "flags": verifier_flags,
                    "provenance": provenance,
                    "embedding": emb,
                    "model_id": os.environ.get("MODEL_ID", "us.meta.llama3-3-70b-instruct-v1:0"),
                }
                append_memory_for_pdf(entry, pdf_path)
            except Exception:
                pass
        _append_trace(trace, "memory", "ok", time.time() - t_memory)
        trace.append({"agent": "total", "status": "ok", "latency": round(time.time() - t0, 3), "timestamp": _ts()})

    except TimeoutError as e:
        yield {"type": "error", "message": str(e)}
        final_answer = FAILSAFE_ANSWER
        confidence = 0.0
        provenance = []
        verifier_flags = []
    except Exception as e:
        yield {"type": "error", "message": str(e)}
        final_answer = FAILSAFE_ANSWER
        confidence = 0.0
        provenance = []
        verifier_flags = []
    yield {
        "type": "final",
        "answer": final_answer,
        "confidence": confidence,
        "provenance": provenance,
        "flags": verifier_flags,
        "trace": trace,
        "tool_calls": tool_calls,
    }
