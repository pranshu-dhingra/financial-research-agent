"""Test safe_stream guarantees final when generator is empty or incomplete."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest


class TestEmptyGenerator(unittest.TestCase):
    def test_safe_stream_empty_generator_emits_final(self):
        """Empty generator yields failsafe final."""
        from orchestrator import safe_stream, FAILSAFE_ANSWER

        def empty_gen():
            return
            yield  # unreachable

        events = list(safe_stream(empty_gen()))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "final")
        self.assertEqual(events[0]["answer"], FAILSAFE_ANSWER)
        self.assertEqual(events[0]["confidence"], 0.0)

    def test_safe_stream_no_final_emits_failsafe_final(self):
        """Generator that yields log/token but no final gets failsafe final appended."""
        from orchestrator import safe_stream, FAILSAFE_ANSWER

        def incomplete_gen():
            yield {"type": "log", "message": "working"}
            yield {"type": "token", "text": "partial"}

        events = list(safe_stream(incomplete_gen()))
        finals = [e for e in events if e.get("type") == "final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["answer"], FAILSAFE_ANSWER)

    def test_safe_stream_with_final_passes_through(self):
        """Generator that yields final passes it through without appending."""
        from orchestrator import safe_stream

        def complete_gen():
            yield {"type": "log", "message": "done"}
            yield {"type": "final", "answer": "Real answer", "confidence": 0.9, "provenance": []}

        events = list(safe_stream(complete_gen()))
        finals = [e for e in events if e.get("type") == "final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["answer"], "Real answer")


if __name__ == "__main__":
    unittest.main()
