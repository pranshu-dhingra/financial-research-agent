#!/usr/bin/env python3
"""
evaluation_report.py - BFSI Research Agent Evaluation Report Generator

Generates: console table, JSON, Markdown with per-query metrics.
"""

import json
from pathlib import Path


def _format_provenance(provenance: list) -> tuple[list[str], list[str]]:
    """Extract internal (with page) and external (with URL) sources."""
    internal = []
    external = []
    for p in provenance or []:
        t = p.get("type", "")
        src = p.get("source", "")
        page = p.get("page")
        url = p.get("url", src) if t == "external" else ""
        snippet = (p.get("text", "") or "")[:100] + "..."
        if t == "internal":
            internal.append(f"  - {src}" + (f" (page {page})" if page else "") + f": {snippet}")
        elif t == "external":
            external.append(f"  - {url or src}: {snippet}")
    return internal, external


def print_console_table(results: list):
    """Print console table summary of evaluation results."""
    print("\n--- Per-Query Summary ---")
    for i, r in enumerate(results, 1):
        pdf = r.get("pdf", "")[:30]
        q = (r.get("question", "") or "")[:40] + "..."
        lat = r.get("latency_seconds", 0)
        conf = r.get("confidence", 0)
        valid = "PASS" if r.get("validation_passed") else "FAIL"
        err = r.get("error", "")
        status = err[:30] if err else valid
        print(f"  {i}. {pdf} | {lat:.1f}s | conf={conf:.2f} | {status}")


def generate_report(results: list, json_path: str = "evaluation_results.json", md_path: str = "evaluation_results.md"):
    """
    Generate evaluation report: console table, JSON file, Markdown file.
    """
    print_console_table(results)

    root = Path(__file__).resolve().parent

    json_file = root / json_path
    md_file = root / md_path

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    lines = [
        "# BFSI Research Agent Evaluation Report",
        "",
        "## Summary",
        "",
        f"- Total queries: {len(results)}",
        f"- Passed: {sum(1 for r in results if r.get('validation_passed'))}",
        f"- Errors: {sum(1 for r in results if r.get('error'))}",
        "",
        "## Per-Query Results",
        "",
    ]

    for i, r in enumerate(results, 1):
        lines.append(f"### Query {i}: {r.get('pdf', '')}")
        lines.append("")
        lines.append(f"- **Question:** {r.get('question', '')}")
        lines.append(f"- **Expected type:** {r.get('expected_type', '')}")
        lines.append(f"- **Validation passed:** {r.get('validation_passed', False)}")
        if r.get("error"):
            lines.append(f"- **Error:** {r['error']}")
        else:
            lines.append(f"- **Answer:** {r.get('answer', '')[:500]}...")
            lines.append(f"- **Confidence:** {r.get('confidence', 0):.2f}")
            lines.append(f"- **Latency:** {r.get('latency_seconds', 0):.2f} sec")
            lines.append(f"- **Streaming token count:** {r.get('streamed_tokens', 0)}")
            lines.append(f"- **Tool planner decision:** {r.get('tool_calls', [])}")
            lines.append(f"- **Verifier flags:** {r.get('verifier_flags', [])}")

            internal, external = _format_provenance(r.get("provenance", []))
            lines.append("- **Internal sources:**")
            for s in internal[:5]:
                lines.append(s)
            if len(internal) > 5:
                lines.append(f"  - ... and {len(internal) - 5} more")
            lines.append("- **External sources:**")
            for s in external[:5]:
                lines.append(s)
            if len(external) > 5:
                lines.append(f"  - ... and {len(external) - 5} more")

            trace = r.get("trace", [])
            if trace:
                lines.append("- **Per-stage latency:**")
                for t in trace:
                    stage = t.get("stage", "")
                    lat = t.get("latency_seconds", 0)
                    lines.append(f"  - {stage}: {lat}s")

        lines.append("")

    with open(md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
