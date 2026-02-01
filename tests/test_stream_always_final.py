"""Test that run_workflow_stream always emits exactly one 'final' event."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import patch, MagicMock


class TestStreamAlwaysFinal(unittest.TestCase):
    def test_run_workflow_stream_emits_final(self):
        """Every run produces exactly one final event."""
        from orchestrator import run_workflow_stream

        with patch("orchestrator.classifier_agent", return_value={
            "internal_sufficient": True, "external_needed": False, "reason": "test"
        }):
            with patch("orchestrator.retriever_agent", return_value=[
                {"text": "partial", "chunk_text": "c", "page": None, "similarity": 0.8}
            ]):
                with patch("orchestrator.synthesizer_agent_stream") as mock_synth:
                    mock_synth.return_value = iter([{"type": "token", "text": "Answer"}])
                    with patch("orchestrator._verifier_agent", return_value={
                        "confidence": 0.9, "flags": [], "explanation": ""
                    }):
                        with patch("local_pdf_qa.load_memory_for_pdf", return_value=[]):
                            with patch("local_pdf_qa.find_relevant_memories_semantic", return_value=[]):
                                events = list(run_workflow_stream("test", __file__.replace(".py", ".pdf")))
        finals = [e for e in events if e.get("type") == "final"]
        self.assertEqual(len(finals), 1, f"Expected 1 final, got {len(finals)}: {events}")
        self.assertIn("answer", finals[0])
        self.assertIn("confidence", finals[0])
        self.assertIn("provenance", finals[0])

    def test_run_workflow_stream_on_exception_emits_final(self):
        """On exception, final is still emitted (via finally block)."""
        from orchestrator import run_workflow_stream

        with patch("orchestrator.classifier_agent", side_effect=RuntimeError("boom")):
            events = list(run_workflow_stream("test", __file__.replace(".py", ".pdf")))
        finals = [e for e in events if e.get("type") == "final"]
        self.assertEqual(len(finals), 1)
        self.assertIn("System could not retrieve", finals[0].get("answer", ""))


if __name__ == "__main__":
    unittest.main()
