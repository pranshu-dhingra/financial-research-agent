"""Test that tool planner prompt includes BFSI context and conceptual tools."""

import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools


class TestToolPlannerContext(unittest.TestCase):


    def test_load_tool_knowledge_base(self):
        """Ensure TOOL_KNOWLEDGE_BASE is loaded with BFSI categories."""
        kb = tools.load_tool_knowledge_base()
        self.assertIsInstance(kb, dict)
        self.assertIn("web_search", kb)
        self.assertIn("regulatory_filings", kb)
        self.assertIn("company_financials", kb)
        self.assertIn("macroeconomic", kb)
        self.assertIn("credit_ratings", kb)
        self.assertIn("financial_news", kb)
        for k, v in kb.items():
            self.assertIn("category", v)
            self.assertIn("purpose", v)
            self.assertIn("example_providers", v)

    def test_list_conceptual_tools(self):
        """Ensure conceptual tools are listed."""
        tools_list = tools.list_conceptual_tools()
        self.assertIn("web_search", tools_list)
        self.assertIn("company_financials", tools_list)

    def test_planner_prompt_includes_bfsi_context(self):
        """Ensure tool_planner_agent builds prompt with BFSI and conceptual tools."""
        kb = tools.load_tool_knowledge_base()
        categories = {v["category"] for v in kb.values()}
        self.assertIn("generic", categories)
        self.assertIn("regulatory", categories)
        self.assertIn("financials", categories)
        self.assertIn("macro", categories)
        self.assertIn("credit", categories)
        self.assertIn("news", categories)

    def test_planner_returns_valid_structure(self):
        """Ensure tool_planner_agent returns category, recommended_providers, reason."""
        def mock_llm(prompt):
            return '{"category": "financials", "recommended_providers": ["yahoo_finance"], "reason": "test"}'

        result = tools.tool_planner_agent("What is HDFC Bank CET1 ratio?", call_llm_fn=mock_llm)
        self.assertIn("category", result)
        self.assertIn("recommended_providers", result)
        self.assertIn("reason", result)
        self.assertIsInstance(result["recommended_providers"], list)


if __name__ == "__main__":
    unittest.main()
