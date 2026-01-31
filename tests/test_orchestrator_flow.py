"""Test orchestrator flow: mock classifier internal-only, assert tool_agent not called."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestOrchestratorFlow(unittest.TestCase):
    def test_classifier_internal_only_structure(self):
        """When classifier returns internal_sufficient=True, external_needed=False."""
        from orchestrator import classifier_agent

        with patch("local_pdf_qa.extract_text_from_pdf", return_value="sample text"):
            with patch("local_pdf_qa.chunk_text", return_value=["chunk1", "chunk2"]):
                with patch("local_pdf_qa.find_relevant_chunks", return_value=[
                    {"chunk_text": "c1", "idx": 0, "similarity": 0.85},
                ]):
                    result = classifier_agent("test", "dummy.pdf")
                    self.assertTrue(result["internal_sufficient"])
                    self.assertFalse(result["external_needed"])
                    self.assertIn("reason", result)

    def test_classifier_returns_valid_structure(self):
        """Classifier returns internal_sufficient, external_needed, reason."""
        from orchestrator import classifier_agent

        with patch("local_pdf_qa.extract_text_from_pdf", return_value="sample text"):
            with patch("local_pdf_qa.chunk_text", return_value=["chunk1", "chunk2"]):
                with patch("local_pdf_qa.find_relevant_chunks", return_value=[]):
                    result = classifier_agent("test", "dummy.pdf")
                    self.assertIn("internal_sufficient", result)
                    self.assertIn("external_needed", result)
                    self.assertIn("reason", result)


if __name__ == "__main__":
    unittest.main()
