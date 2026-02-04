#!/usr/bin/env python3
"""
test_partial_external_fallback.py

Test partial external augmentation.
"""

import os
import sys
from pathlib import Path

# Set environment before importing
os.environ["ENABLE_TOOL_PLANNER"] = "1"
os.environ["DEBUG"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator import run_workflow

def test_partial_external_fallback():
    """Test that partial internal evidence triggers external augmentation."""
    
    pdf_path = "uploads/BAC_2024_Annual_Report.pdf"
    question = "What is the current market capitalization of Bank of America and how does it compare to its revenue in 2024?"
    
    result = run_workflow(question, pdf_path)
    
    # Assertions
    answer = result["answer"]
    provenance = result["provenance"]
    confidence = result["confidence"]
    flags = result["flags"]
    
    # Check internal facts include revenue
    internal_provenance = [p for p in provenance if p.get("type") == "internal"]
    assert len(internal_provenance) > 0, "Should have internal provenance"
    
    # Check external facts include market cap (assuming SerpAPI finds it)
    external_provenance = [p for p in provenance if p.get("type") == "external"]
    assert len(external_provenance) > 0, "Should have external provenance for missing market cap"
    
    # Check provenance contains both
    assert "internal" in [p.get("type") for p in provenance], "Should have internal sources"
    assert "external" in [p.get("type") for p in provenance], "Should have external sources"
    
    # Check confidence >= 0.6
    assert confidence >= 0.6, f"Confidence should be >= 0.6, got {confidence}"
    
    print("Test passed!")

if __name__ == "__main__":
    test_partial_external_fallback()