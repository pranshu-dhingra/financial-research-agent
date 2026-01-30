"""Test credential handshake when provider is missing or unconfigured."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools
import unittest


class TestCredentialHandshake(unittest.TestCase):
    def test_resolve_tool_credentials_web_search_generic_in_ready(self):
        """web_search_generic has no credentials required - should be in ready_providers."""
        plan = {"category": "generic", "recommended_providers": ["web_search_generic"], "reason": "test"}
        result = tools.resolve_tool_credentials(plan)
        self.assertIn("web_search_generic", result["ready_providers"])

    def test_resolve_tool_credentials_skip_fallback(self):
        """Mock input() returning SKIP - ensure fallback to web_search_generic."""
        plan = {"category": "macroeconomic", "recommended_providers": ["world_bank"], "reason": "test"}

        def mock_input():
            return "SKIP"

        result = tools.resolve_tool_credentials(plan, input_fn=mock_input)
        self.assertIn("web_search_generic", result["ready_providers"])
        self.assertIn("world_bank", result["skipped"])

    def test_get_provider_config_missing(self):
        """Unconfigured provider returns None."""
        config = tools.get_provider_config("nonexistent_provider_xyz")
        self.assertIsNone(config)

    def test_list_configured_providers(self):
        """Configured providers include serpapi and web_search_generic."""
        providers = tools.list_configured_providers()
        self.assertIn("serpapi", providers)
        self.assertIn("web_search_generic", providers)

    def test_register_and_get_credentials(self):
        """register_credentials stores and get_credentials retrieves."""
        with tempfile.TemporaryDirectory() as tmp:
            cred_path = Path(tmp) / ".tool_credentials.json"
            with patch.object(tools, "CREDENTIALS_STORE_PATH", cred_path):
                tools.register_credentials("test_provider", {"api_key": "test123"})
                creds = tools.get_credentials("test_provider")
                self.assertIsNotNone(creds)
                self.assertEqual(creds.get("api_key"), "test123")

    def test_web_search_generic_returns_dict(self):
        """web_search_generic returns dict with text and url keys."""
        result = tools.web_search_generic("test query")
        self.assertIsInstance(result, dict)
        self.assertIn("text", result)
        self.assertIn("url", result)

    def test_web_search_via_provider_unconfigured(self):
        """web_search_via_provider returns error for unconfigured provider."""
        result = tools.web_search_via_provider("test", "nonexistent_xyz")
        self.assertIn("text", result)
        self.assertTrue(
            "not configured" in result["text"].lower() or "missing" in result["text"].lower()
        )

    def test_execute_external_tools_provenance(self):
        """execute_external_tools returns provenance-tagged snippets."""
        snippets = tools.execute_external_tools(
            ["web_search_generic"], "test query", "generic"
        )
        self.assertIsInstance(snippets, list)
        for s in snippets:
            self.assertEqual(s.get("type"), "external")
            self.assertIn("tool", s)
            self.assertIn("category", s)
            self.assertIn("url", s)
            self.assertIn("text", s)
            self.assertIn("fetched_at", s)


if __name__ == "__main__":
    unittest.main()
