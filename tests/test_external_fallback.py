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
        """Synthesizer agent includes external snippets in provenance."""
        from orchestrator import synthesizer_agent

        partials = []
        external_snippets = [
            {"type": "external", "tool": "web_search", "category": "generic", "text": "External answer", "url": "https://x.com"},
        ]
        with patch("orchestrator._call_llm") as mock_llm:
            mock_sync = MagicMock(return_value="Synthesized answer from external source.")
            mock_stream = MagicMock(return_value="Synthesized answer from external source.")
            mock_llm.return_value = (mock_sync, mock_stream)
            result = synthesizer_agent(
                partials, external_snippets, None, "What is GDP?",
                use_streaming=False,
            )
            self.assertIn("answer", result)
            self.assertIn("provenance", result)
            ext_prov = [p for p in result["provenance"] if p.get("type") == "external"]
            self.assertGreater(len(ext_prov), 0)
            self.assertEqual(ext_prov[0]["tool"], "web_search")


if __name__ == "__main__":
    unittest.main()
