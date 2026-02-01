"""Test tool call timeout and failure handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import patch


class TestToolTimeout(unittest.TestCase):
    def test_execute_external_tools_returns_structured_error_on_failure(self):
        """On tool failure, returns structured error result."""
        import tools

        with patch("tools.web_search_via_provider", side_effect=TimeoutError("timeout")):
            with patch("tools.get_provider_config", return_value={"category": "generic"}):
                with patch("tools.web_search_generic", side_effect=TimeoutError("timeout")):
                    results = tools.execute_external_tools(
                        ["serpapi"], "test query", "generic"
                    )
        self.assertTrue(len(results) >= 1)
        err = results[0]
        self.assertTrue(err.get("error"))
        self.assertEqual(err.get("text"), "Tool failed or unavailable")
        self.assertIn("tool", err)
        self.assertIn("category", err)

    def test_web_search_serpapi_uses_timeout(self):
        """SerpAPI request uses timeout=10."""
        import tools

        with patch("requests.get") as mock_get:
            resp = unittest.mock.MagicMock()
            resp.json.return_value = {"organic_results": []}
            resp.raise_for_status = lambda: None
            mock_get.return_value = resp
            tools.web_search_serpapi("test")
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args[1]
            self.assertEqual(call_kwargs.get("timeout"), 10)


if __name__ == "__main__":
    unittest.main()
