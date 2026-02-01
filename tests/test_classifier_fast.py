"""Test fast classifier: no API calls, runtime < 0.1 seconds."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestClassifierFast(unittest.TestCase):
    def test_classifier_internal_sufficient_high_similarity(self):
        """When token overlap is high, classifier returns internal_sufficient=True."""
        from orchestrator import classifier_agent

        with self.subTest("high overlap"):
            # Create temp PDF path - we'll mock extract/chunk
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                pdf_path = f.name
            try:
                from unittest.mock import patch
                # Chunks that share many tokens with query "budget allocation fiscal year"
                chunks = [
                    "The budget allocation for the fiscal year 2024 shows significant increases.",
                    "Fiscal year planning involves budget allocation decisions.",
                ]
                with patch("local_pdf_qa.extract_text_from_pdf", return_value=" ".join(chunks)):
                    with patch("local_pdf_qa.chunk_text", return_value=chunks):
                        t0 = time.perf_counter()
                        result = classifier_agent("budget allocation fiscal year", pdf_path)
                        elapsed = time.perf_counter() - t0
                self.assertLess(elapsed, 0.1, f"Classifier took {elapsed:.3f}s, must be < 0.1s")
                self.assertIn("internal_sufficient", result)
                self.assertIn("external_needed", result)
                self.assertIn("reason", result)
            finally:
                os.unlink(pdf_path)

    def test_classifier_external_needed_low_similarity(self):
        """When token overlap is low, classifier returns external_needed=True."""
        from orchestrator import classifier_agent

        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            from unittest.mock import patch
            # Chunks with no overlap with query "quantum computing algorithms"
            chunks = ["The budget was approved. Tax rates increased."]
            with patch("local_pdf_qa.extract_text_from_pdf", return_value=" ".join(chunks)):
                with patch("local_pdf_qa.chunk_text", return_value=chunks):
                    t0 = time.perf_counter()
                    result = classifier_agent("quantum computing algorithms", pdf_path)
                    elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 0.1, f"Classifier took {elapsed:.3f}s, must be < 0.1s")
            self.assertFalse(result["internal_sufficient"])
            self.assertTrue(result["external_needed"])
        finally:
            os.unlink(pdf_path)

    def test_classifier_no_chunks(self):
        """When no chunks, returns external_needed=True."""
        from orchestrator import classifier_agent

        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            from unittest.mock import patch
            with patch("local_pdf_qa.extract_text_from_pdf", return_value=""):
                with patch("local_pdf_qa.chunk_text", return_value=[]):
                    t0 = time.perf_counter()
                    result = classifier_agent("any query", pdf_path)
                    elapsed = time.perf_counter() - t0
            self.assertLess(elapsed, 0.1)
            self.assertFalse(result["internal_sufficient"])
            self.assertTrue(result["external_needed"])
        finally:
            os.unlink(pdf_path)

    def test_find_relevant_chunks_token_runtime(self):
        """find_relevant_chunks_token completes in < 0.1 seconds."""
        from local_pdf_qa import find_relevant_chunks_token

        chunks = [f"chunk {i} with some sample text for testing" for i in range(50)]
        query = "sample text testing"
        t0 = time.perf_counter()
        results = find_relevant_chunks_token(query, chunks, top_k=3)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.1, f"find_relevant_chunks_token took {elapsed:.3f}s")
        self.assertIsInstance(results, list)
        for r in results:
            self.assertIn("chunk_text", r)
            self.assertIn("idx", r)
            self.assertIn("similarity", r)


if __name__ == "__main__":
    unittest.main()
