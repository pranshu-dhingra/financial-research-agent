"""Test graceful failure: no internal, no tools -> insufficient evidence, confidence < 0.4."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestGracefulFailure(unittest.TestCase):
    def test_verifier_low_confidence_when_no_sources(self):
        """Verifier returns confidence < 0.4 when no internal or external sources."""
        from orchestrator import verifier_agent

        answer = "Insufficient evidence. No relevant internal or external sources found."
        provenance = []
        result = verifier_agent(answer, provenance)
        self.assertLess(result["confidence"], 0.4)
        self.assertIn("no_sources", result["flags"])

    def test_verifier_insufficient_answer_lowers_confidence(self):
        """Answer containing 'insufficient' lowers verifier checks score."""
        from orchestrator import verifier_agent

        answer = "Insufficient evidence to answer."
        provenance = [{"type": "internal", "similarity": 0.3}]
        result = verifier_agent(answer, provenance)
        self.assertLess(result["confidence"], 0.5)

    def test_synthesizer_insufficient_when_empty_inputs(self):
        """Synthesizer returns insufficient evidence when no partials and no external."""
        from orchestrator import synthesizer_agent

        result = synthesizer_agent([], [], None, "test?", use_streaming=False)
        self.assertIn("answer", result)
        self.assertIn("insufficient", result["answer"].lower())


if __name__ == "__main__":
    unittest.main()
