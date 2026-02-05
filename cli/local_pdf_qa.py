#!/usr/bin/env python3
"""
local_pdf_qa.py - CLI entrypoint for PDF Q&A

Usage:
  python cli/local_pdf_qa.py path/to/file.pdf "Your question here"

This is a thin wrapper that delegates to the agent orchestrator.
"""

import sys
import os
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import USE_ORCHESTRATOR, DEBUG
from agent.orchestrator import run_workflow


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 3:
        print("Usage: python local_pdf_qa.py path/to/file.pdf \"Your question here\"")
        sys.exit(2)

    pdf_path = sys.argv[1]
    question = sys.argv[2]

    if not os.path.exists(pdf_path):
        print("PDF file not found:", pdf_path)
        sys.exit(1)

    # Use orchestrator workflow
    try:
        result = run_workflow(question, pdf_path, use_streaming=True)
        print("\n=== ANSWER ===\n")
        print(result["answer"])
        print("\n=== SOURCES ===\n")
        for p in result.get("provenance", []):
            typ = p.get("type", "internal")
            src = p.get("source", "pdf")
            page = p.get("page")
            tool = p.get("tool")
            if typ == "internal":
                line = f"  internal | {src}"
                if page is not None:
                    line += f" | page={page}"
            else:
                line = f"  external | {src}"
                if tool:
                    line += f" | tool={tool}"
            print(line)
        print("\n=== CONFIDENCE ===\n")
        print(result.get("confidence", 0.0))
        if result.get("flags"):
            print("\n=== FLAGS ===\n")
            print(", ".join(result["flags"]))
        print("\n=== END ===\n")
    except Exception as e:
        print(f"Error during workflow execution: {e}")
        if DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
