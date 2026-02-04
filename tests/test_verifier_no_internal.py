"""Test verifier when only external snippets - confidence < 0.5."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestVerifierNoInternal(unittest.TestCase):
    def test_only_external_low_confidence(self):
        """Only external snippets -> confidence < 0.5."""
        from verifier import verifier_agent

        answer = "GDP growth is 7.2% according to external sources."
        provenance = [
            {"type": "external", "text": "GDP 7.2%", "category": "generic", "tool": "web_search"},
        ]
        result = verifier_agent(answer, provenance, [], [])
        self.assertLess(result["confidence"], 0.5)
        # We no longer emit NO_INTERNAL_EVIDENCE; low confidence plus ONLY_GENERIC_WEB flag is sufficient.


if __name__ == "__main__":
    unittest.main()
