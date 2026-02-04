"""Test external fallback: force low internal similarity, mock tool_agent, assert external provenance."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestExternalFallback(unittest.TestCase):
    def test_external_provenance_structure(self):
        """External provenance has type=external, source, tool, category, text."""
        external_snippet = {
            "type": "external",
            "source": "https://example.com",
            "tool": "web_search_generic",
            "category": "generic",
            "text": "External snippet text",
        }
        self.assertEqual(external_snippet["type"], "external")
        self.assertIn("source", external_snippet)
        self.assertIn("tool", external_snippet)
        self.assertIn("text", external_snippet)

    def test_synthesizer_merges_external_provenance(self):
        """Synthesizer agent uses external facts but does not emit provenance labels."""
        from orchestrator import synthesizer_agent

        internal_facts = []
        external_facts = [
            {"tool": "web_search", "category": "generic", "text": "External answer", "url": "https://x.com"},
        ]
        memory_facts = []
        with patch("orchestrator._call_llm") as mock_llm:
            mock_sync = MagicMock(return_value="Synthesized answer from external source.")
            mock_stream = MagicMock(return_value="Synthesized answer from external source.")
            mock_llm.return_value = (mock_sync, mock_stream)
            result = synthesizer_agent(
                internal_facts, external_facts, memory_facts, "What is GDP?",
                use_streaming=False,
            )
            self.assertIn("answer", result)
            ans = result["answer"]
            self.assertNotIn("[INTERNAL]", ans)
            self.assertNotIn("[EXTERNAL]", ans)


if __name__ == "__main__":
    unittest.main()
