"""Test reranker selects highest scored candidate."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestRerankerSelection(unittest.TestCase):
    def test_rank_candidates_selects_best(self):
        """Provide 3 dummy candidates, mock verifier scores, assert highest scored selected."""
        from reranker import rank_candidates

        def mock_verifier(answer, provenance, partials, external_snippets):
            scores = {"A": 0.9, "B": 0.5, "C": 0.7}
            return {"confidence": scores.get(answer, 0.5)}

        candidates = ["A", "B", "C"]
        result = rank_candidates(
            "test query",
            candidates,
            provenance=[],
            partials=[],
            external_snippets=[],
            verifier_fn=mock_verifier,
            get_embedding_fn=lambda x: [0.1] * 256,
        )
        self.assertEqual(result, "A")

    def test_rank_candidates_single_returns_same(self):
        """Single candidate returns as-is."""
        from reranker import rank_candidates

        result = rank_candidates("q", ["only one"], provenance=[], partials=[], external_snippets=[])
        self.assertEqual(result, "only one")


if __name__ == "__main__":
    unittest.main()
