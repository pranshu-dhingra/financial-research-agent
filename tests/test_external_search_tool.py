"""Test external search tool: SerpAPI and DuckDuckGo fallback."""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestExternalSearchTool(unittest.TestCase):
    def test_web_search_serpapi_returns_list_with_url_and_text(self):
        """Mock SerpAPI response; assert web_search_serpapi returns list with url + text."""
        import tools

        mock_response = {
            "organic_results": [
                {"title": "Test Title 1", "snippet": "Snippet 1", "link": "https://example.com/1"},
                {"title": "Test Title 2", "snippet": "Snippet 2", "link": "https://example.com/2"},
            ]
        }

        def mock_get(url, params=None, timeout=None, headers=None):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = mock_response
            return resp

        with patch("tools._resolve_credentials", return_value={"api_key": "test_key"}):
            with patch("requests.get", side_effect=mock_get):
                result = tools.web_search_serpapi("test query", top_k=5)

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        for item in result:
            self.assertIn("text", item)
            self.assertIn("url", item)
            self.assertIn("title", item)
            self.assertIsInstance(item["text"], str)
            self.assertIsInstance(item["url"], str)

    def test_web_search_serpapi_empty_credentials_returns_empty_list(self):
        """When no credentials, web_search_serpapi returns empty list."""
        import tools

        with patch("tools._resolve_credentials", return_value=None):
            result = tools.web_search_serpapi("test query")
        self.assertEqual(result, [])

    def test_web_search_via_provider_serpapi_with_creds(self):
        """web_search_via_provider with serpapi and credentials returns text and url."""
        import tools

        mock_response = {
            "organic_results": [
                {"title": "A", "snippet": "B", "link": "https://x.com"},
            ]
        }

        def mock_get(url, params=None, timeout=None, headers=None):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = mock_response
            return resp

        with patch("tools._resolve_credentials", return_value={"api_key": "key"}):
            with patch("requests.get", side_effect=mock_get):
                result = tools.web_search_via_provider("query", "serpapi")

        self.assertIn("text", result)
        self.assertIn("url", result)
        self.assertIn("A", result["text"])
        self.assertIn("B", result["text"])

    def test_web_search_via_provider_serpapi_no_creds_returns_error(self):
        """web_search_via_provider with serpapi and no credentials returns error dict."""
        import tools

        with patch("tools._resolve_credentials", return_value=None):
            result = tools.web_search_via_provider("query", "serpapi")

        self.assertIn("text", result)
        self.assertIn("Missing credentials", result["text"])


if __name__ == "__main__":
    unittest.main()
