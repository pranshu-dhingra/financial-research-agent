#!/usr/bin/env python3
"""
evaluation_queries.py - Curated query matrix for BFSI Research Agent E2E evaluation.

Covers: internal-only, external-only, hybrid (internal + external).
"""

EVAL_QUERIES = [
    # INTERNAL ONLY (answers fully in PDFs)
    {
        "pdf": "Barclays-PLC-Annual-Report-2024.pdf",
        "question": "What was Barclays total revenue in 2024?",
        "expected_type": "internal",
    },
    {
        "pdf": "BAC+2024+Annual+Report.pdf",
        "question": "What is Bank of America's CET1 capital ratio for 2024?",
        "expected_type": "internal",
    },
    {
        "pdf": "HSBC_250219-annual-report-and-accounts-2024.pdf",
        "question": "What were HSBC's total assets in 2024?",
        "expected_type": "internal",
    },
    # EXTERNAL ONLY (not in PDFs, must call tools)
    {
        "pdf": "Barclays-PLC-Annual-Report-2024.pdf",
        "question": "What is Barclays current market capitalization?",
        "expected_type": "external",
    },
    {
        "pdf": "BAC+2024+Annual+Report.pdf",
        "question": "What is Bank of America's latest credit rating?",
        "expected_type": "external",
    },
    {
        "pdf": "World_Bank_Group_Annual_Report_2025.pdf",
        "question": "What is the latest global GDP growth rate?",
        "expected_type": "external",
    },
    # HYBRID (internal + external)
    {
        "pdf": "HSBC_250219-annual-report-and-accounts-2024.pdf",
        "question": "How does HSBC's capital adequacy compare to the global banking average?",
        "expected_type": "hybrid",
    },
    {
        "pdf": "Barclays-PLC-Annual-Report-2024.pdf",
        "question": "Compare Barclays ROE with current industry average.",
        "expected_type": "hybrid",
    },
    {
        "pdf": "World_Bank_Group_Annual_Report_2025.pdf",
        "question": "How does global inflation in 2025 compare to major banks' outlook?",
        "expected_type": "hybrid",
    },
]
