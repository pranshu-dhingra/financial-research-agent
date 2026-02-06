#!/usr/bin/env python3
"""
run_evaluation.py - BFSI Research Agent End-to-End Evaluation Harness

Runs curated queries, captures streaming, provenance, confidence, and metrics.
Produces structured evaluation report.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.evaluation_queries import EVAL_QUERIES
from evaluation.evaluation_report import generate_report


def resolve_pdf_path(pdf_name: str) -> str | None:
    """Resolve PDF name to full path. Searches project root and uploads/."""
    root = Path(__file__).resolve().parent.parent
    candidates = list(root.glob("*.pdf")) + list((root / "uploads").glob("*.pdf"))
    for p in candidates:
        if p.name == pdf_name:
            return str(p)
    return None


def run_single_query(query_spec: dict, timeout_sec: int = 30) -> dict:
    """
    Run one evaluation query via run_workflow_stream wrapped in safe_stream.
    Consumes stream via safe_stream; asserts final event exists.
    Never waits indefinitely.
    """
    from orchestrator import run_workflow_stream, safe_stream

    pdf_name = query_spec.get("pdf", "")
    question = query_spec.get("question", "")
    expected_type = query_spec.get("expected_type", "internal")

    pdf_path = resolve_pdf_path(pdf_name)
    if not pdf_path:
        return {
            "pdf": pdf_name,
            "question": question,
            "expected_type": expected_type,
            "error": f"PDF not found: {pdf_name}",
            "validation_passed": False,
        }

    streamed_tokens = []
    final_event = None
    all_events = []
    internal_sources = 0
    external_sources = 0
    confidence = 0.0
    verifier_flags = []
    provenance = []
    trace = []
    tool_calls = []

    t_start = time.time()
    try:
        stream = safe_stream(
            run_workflow_stream(
                question, pdf_path, max_chunks=5, timeout_sec=min(timeout_sec, 25)
            )
        )
        for event in stream:
            if time.time() - t_start > timeout_sec:
                break
            all_events.append(event)
            if event.get("type") == "token":
                streamed_tokens.append(event.get("text", ""))
            elif event.get("type") == "final":
                final_event = event
                break
            elif event.get("type") == "error":
                pass  # Continue to consume; safe_stream guarantees final
    except Exception as e:
        return {
            "pdf": pdf_name,
            "question": question,
            "expected_type": expected_type,
            "error": str(e),
            "latency_seconds": round(time.time() - t_start, 2),
            "validation_passed": False,
        }

    latency_seconds = round(time.time() - t_start, 2)

    if not final_event:
        return {
            "pdf": pdf_name,
            "question": question,
            "expected_type": expected_type,
            "error": "No final event (timeout or stream incomplete)",
            "latency_seconds": latency_seconds,
            "streamed_tokens": len(streamed_tokens),
            "validation_passed": False,
        }

    answer = final_event.get("answer", "")
    confidence = final_event.get("confidence", 0.0)
    provenance = final_event.get("provenance", [])
    verifier_flags = final_event.get("flags", [])
    trace = final_event.get("trace", [])
    tool_calls = final_event.get("tool_calls", [])

    for p in provenance:
        if p.get("type") == "internal":
            internal_sources += 1
        elif p.get("type") == "external":
            external_sources += 1

    validation_passed = True
    if expected_type == "internal":
        if external_sources != 0:
            validation_passed = False
    elif expected_type == "external":
        if internal_sources != 0:
            validation_passed = False
    elif expected_type == "hybrid":
        if internal_sources <= 0 or external_sources <= 0:
            validation_passed = False

    return {
        "pdf": pdf_name,
        "question": question,
        "expected_type": expected_type,
        "answer": answer,
        "latency_seconds": latency_seconds,
        "streamed_tokens": len(streamed_tokens),
        "internal_sources": internal_sources,
        "external_sources": external_sources,
        "confidence": confidence,
        "verifier_flags": verifier_flags,
        "tool_calls": tool_calls,
        "provenance": provenance,
        "trace": trace,
        "validation_passed": validation_passed,
        "error": None,
    }


def main():
    print("=== BFSI Research Agent Evaluation ===\n")

    results = []
    for i, q in enumerate(EVAL_QUERIES):
        print(f"[{i + 1}/{len(EVAL_QUERIES)}] {q['pdf']}: {q['question'][:50]}...")
        r = run_single_query(q, timeout_sec=30)
        results.append(r)
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
        else:
            print(f"  Latency: {r.get('latency_seconds', 0):.1f}s | Confidence: {r.get('confidence', 0):.2f} | Valid: {r.get('validation_passed', False)}")

    valid = [r for r in results if not r.get("error")]
    n_valid = len(valid)
    n_total = len(results)

    if n_valid > 0:
        avg_latency = sum(r.get("latency_seconds", 0) for r in valid) / n_valid
        avg_confidence = sum(r.get("confidence", 0) for r in valid) / n_valid
        external_used = sum(1 for r in valid if r.get("external_sources", 0) > 0)
        external_pct = 100 * external_used / n_valid
    else:
        avg_latency = 0
        avg_confidence = 0
        external_pct = 0

    print("\n--- Summary ---")
    print(f"Total queries: {n_total}")
    print(f"Avg latency: {avg_latency:.1f} sec")
    print(f"Avg confidence: {avg_confidence:.2f}")
    print(f"External tool usage: {external_pct:.0f}%")

    generate_report(results, "evaluation_results.json", "evaluation_results.md")

    validation_passed_count = sum(1 for r in results if r.get("validation_passed"))
    print(f"\nValidation passed: {validation_passed_count}/{n_total}")

    return 0 if n_valid == n_total and validation_passed_count == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
