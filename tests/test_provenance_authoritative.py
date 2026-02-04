"""Provenance must be system-enforced, never hallucinated by LLM."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestProvenanceAuthoritative(unittest.TestCase):
    def test_internal_only_query_has_no_external_and_no_labels_in_answer(self):
        """Internal-only flow should yield only internal provenance and no [INTERNAL]/[EXTERNAL] in answer."""
        from orchestrator import run_workflow

        with patch("orchestrator.classifier_agent", return_value={
            "internal_sufficient": True,
            "external_needed": False,
            "reason": "test",
        }), patch("orchestrator.retriever_agent", return_value=[
            {
                "text": "Internal fact about capital ratios.",
                "chunk_text": "chunk",
                "page": 5,
                "similarity": 0.9,
            }
        ]), patch("orchestrator.tool_agent", return_value=("", [])), patch(
            "orchestrator.ENABLE_TOOL_AGENT", False
        ), patch(
            "local_pdf_qa.load_memory_for_pdf", return_value=[]
        ), patch(
            "local_pdf_qa.find_relevant_memories_semantic", return_value=[]
        ), patch(
            "orchestrator.synthesizer_agent",
            return_value={"answer": "This is an internal-only answer about capital ratios."},
        ):
            result = run_workflow("test question", "dummy.pdf", use_streaming=False)

        answer = result.get("answer", "")
        provenance = result.get("provenance", [])

        # Answer text must not contain hallucinated provenance tags.
        self.assertNotIn("[INTERNAL]", answer)
        self.assertNotIn("[EXTERNAL]", answer)

        # Provenance must be present and authoritative, with only internal entries.
        self.assertTrue(len(provenance) >= 1)
        for p in provenance:
            self.assertEqual(p.get("type"), "internal")
            self.assertNotEqual(p.get("source", ""), "")


if __name__ == "__main__":
    unittest.main()

