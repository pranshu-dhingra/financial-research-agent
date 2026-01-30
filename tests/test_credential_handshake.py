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
    def test_resolve_handshake_web_search_generic_returns_ok(self):
        """web_search_generic has no credentials required - should return ok."""
        status = tools.resolve_credential_handshake("web_search_generic", "generic", [])
        self.assertEqual(status, "ok")

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


if __name__ == "__main__":
    unittest.main()
