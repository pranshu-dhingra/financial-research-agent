#!/usr/bin/env python3
"""
test_external_only_fallback.py

Test external-only fallback.
"""

import os
import sys
from pathlib import Path

# Set environment before importing
os.environ["ENABLE_TOOL_PLANNER"] = "1"
os.environ["DEBUG"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator import run_workflow

def test_external_only_fallback():
    """Test that no internal evidence triggers external-only lookup."""
    
    pdf_path = "uploads/BAC_2024_Annual_Report.pdf"
    question = "Tell me the total loss absorbing capacity and long-term debt of BAC."
    
    result = run_workflow(question, pdf_path)
    
    # Assertions
    answer = result["answer"]
    provenance = result["provenance"]
    confidence = result["confidence"]
    flags = result["flags"]
    
    # Check SerpAPI is called (external provenance exists)
    external_provenance = [p for p in provenance if p.get("type") == "external"]
    assert len(external_provenance) > 0, "Should have external provenance"
    
    # Check answer not empty
    assert answer and answer.strip(), "Answer should not be empty"
    
    # Check confidence >= 0.6
    assert confidence >= 0.6, f"Confidence should be >= 0.6, got {confidence}"
    
    print("Test passed!")

if __name__ == "__main__":
    test_external_only_fallback()