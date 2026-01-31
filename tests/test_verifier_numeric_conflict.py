"""Test verifier detects numeric contradiction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestVerifierNumericConflict(unittest.TestCase):
    def test_numeric_contradiction_flag(self):
        """Provide fake provenance with two conflicting numbers -> NUMERIC_CONTRADICTION in flags."""
        from verifier import verifier_agent

        answer = "The CET1 ratio is 12.5% according to one source."
        provenance = [
            {"type": "internal", "text": "CET1 ratio: 12.5%", "similarity": 0.8},
            {"type": "external", "text": "CET1 ratio: 15.3%", "category": "financials"},
        ]
        result = verifier_agent(answer, provenance, [], [])
        self.assertIn("NUMERIC_CONTRADICTION", result["flags"])


if __name__ == "__main__":
    unittest.main()
