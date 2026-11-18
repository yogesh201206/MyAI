"""
tests/test_ollama_context_budget.py — Context budget tests for local Ollama models.

Covers:
  1. Simple Java OOP prompt fits within local context budget.
  2. Long conversation history is trimmed safely; latest message preserved.
  3. Latest user message is never discarded.
  4. Output token reservation is respected (input budget < total context window).
  5. System prompt is not duplicated in the message list.
  6. Local mode (ollama: prefix) never invokes OmniRoute send_chat.
  7. Oversized single message triggers exceeds_essential without crash.
  8. Cloud model context budget is unchanged by local fixes.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/home/yoges/myai")
os.environ.setdefault("PYTHONPATH", "/home/yoges/myai")

import config


class TestOllamaContextBudget(unittest.TestCase):

    def setUp(self):
        # Ensure OLLAMA constants are present (they may differ if config was
        # partially loaded before our fix landed).
        config.OLLAMA_NUM_CTX = 8192
        config.OLLAMA_NUM_PREDICT = 2048
        config.OLLAMA_MAX_INPUT_TOKENS = int((8192 - 2048) * 0.95)  # 5,832

    # ------------------------------------------------------------------
    # 1. Simple Java OOP prompt fits in budget
    # ------------------------------------------------------------------
    def test_01_java_oop_prompt_fits_local_budget(self):
        """A simple Java OOP question must fit in the Ollama input budget."""
        from core.context_budget import (
            estimate_messages_tokens,
            get_model_context_budget,
            prepare_budgeted_messages,
        )

        budget = get_model_context_budget("ollama:qwen3:4b")
        self.assertGreater(budget, 0)
        # Budget must be less than the total context window (output is reserved)
        self.assertLess(budget, config.OLLAMA_NUM_CTX)

        local_sys = getattr(config, "LOCAL_SYSTEM_PROMPT", config.SYSTEM_PROMPT).strip()
        messages = [
            {"role": "system", "content": local_sys},
            {"role": "user", "content": "Explain Java OOP concepts with simple examples."},
        ]
        total_tokens = estimate_messages_tokens(messages)
        self.assertLessEqual(
            total_tokens,
            budget,
            f"Java OOP prompt ({total_tokens} tokens) must fit in budget ({budget} tokens)",
        )

        budgeted, was_pruned, stats = prepare_budgeted_messages(messages, "ollama:qwen3:4b")
        self.assertFalse(stats.get("exceeds_essential"),
                         "Simple prompt must not trigger exceeds_essential")
        self.assertFalse(was_pruned)

    # ------------------------------------------------------------------
    # 2. Long conversation history is trimmed; latest message preserved
    # ------------------------------------------------------------------
    def test_02_long_history_trimmed_latest_preserved(self):
        """Old conversation turns are pruned; the most recent user message survives."""
        from core.context_budget import prepare_budgeted_messages, get_model_context_budget

        budget = get_model_context_budget("ollama:qwen3:4b")
        local_sys = getattr(config, "LOCAL_SYSTEM_PROMPT", config.SYSTEM_PROMPT).strip()
        messages = [{"role": "system", "content": local_sys}]

        # Build enough turns to exceed the budget (~60 tokens each × 2 sides × 60 = 7,200 tokens)
        for i in range(60):
            messages.append({"role": "user",    "content": f"Old question {i}: " + ("x " * 100)})
            messages.append({"role": "assistant","content": f"Old answer {i}: "   + ("y " * 100)})

        last_question = "Explain Java OOP concepts with simple examples."
        messages.append({"role": "user", "content": last_question})

        budgeted, was_pruned, stats = prepare_budgeted_messages(messages, "ollama:qwen3:4b")

        # Must have pruned some old turns
        self.assertTrue(was_pruned, "Long history should trigger pruning")
        # Final tokens must be within budget
        self.assertLessEqual(stats["final_tokens"], budget)
        # Latest user message must survive
        self.assertEqual(budgeted[-1]["content"], last_question,
                         "Latest user message must always be the last message")
        # System prompt must survive
        self.assertEqual(budgeted[0]["role"], "system")

    # ------------------------------------------------------------------
    # 3. Latest user message is never discarded
    # ------------------------------------------------------------------
    def test_03_latest_user_message_always_preserved(self):
        """prepare_budgeted_messages must never drop the final user message."""
        from core.context_budget import prepare_budgeted_messages

        local_sys = getattr(config, "LOCAL_SYSTEM_PROMPT", config.SYSTEM_PROMPT).strip()
        final_msg = "What is polymorphism?"
        messages = [
            {"role": "system",    "content": local_sys},
            {"role": "user",      "content": "Tell me about OOP: " + ("a " * 1000)},
            {"role": "assistant", "content": "OOP answer: "          + ("b " * 1000)},
            {"role": "user",      "content": final_msg},
        ]

        budgeted, _, _ = prepare_budgeted_messages(messages, "ollama:qwen3:4b")
        last_user = next(
            (m for m in reversed(budgeted) if m["role"] == "user"), None
        )
        self.assertIsNotNone(last_user, "There must be at least one user message")
        self.assertIn(final_msg, last_user["content"])

    # ------------------------------------------------------------------
    # 4. Output token reservation respected
    # ------------------------------------------------------------------
    def test_04_output_token_reservation_respected(self):
        """Ollama input budget must be strictly less than the total context window."""
        from core.context_budget import get_model_context_budget

        budget = get_model_context_budget("ollama:qwen3:4b")
        total_ctx = config.OLLAMA_NUM_CTX
        reserved_output = config.OLLAMA_NUM_PREDICT

        # Input budget < total context (output tokens reserved)
        self.assertLess(budget, total_ctx,
                        "Input budget must be less than the total context window")
        # Input budget must leave room for at least the configured output
        self.assertLessEqual(budget, total_ctx - reserved_output,
                             "Budget must not exceed total_ctx - num_predict")

    # ------------------------------------------------------------------
    # 5. System prompt appears exactly once in messages
    # ------------------------------------------------------------------
    def test_05_system_prompt_not_duplicated(self):
        """The system prompt must appear exactly once in the constructed messages."""
        from core.context_budget import prepare_budgeted_messages

        local_sys = getattr(config, "LOCAL_SYSTEM_PROMPT", config.SYSTEM_PROMPT).strip()
        messages = [
            {"role": "system", "content": local_sys},
            {"role": "user",   "content": "Hello"},
        ]

        budgeted, _, _ = prepare_budgeted_messages(messages, "ollama:qwen3:4b")
        sys_messages = [m for m in budgeted if m["role"] == "system"
                        and m["content"] == local_sys]
        self.assertEqual(len(sys_messages), 1, "System prompt must appear exactly once")

    # ------------------------------------------------------------------
    # 6. Local model never invokes OmniRoute
    # ------------------------------------------------------------------
    def test_06_local_model_never_calls_omniroute(self):
        """When model_id starts with 'ollama:', OmniRoute send_chat must not be called."""
        from app import _dispatch_send_chat

        messages = [{"role": "user", "content": "Hello"}]

        with patch("api.ollama.send_chat") as mock_local, \
             patch("api.omniroute.send_chat") as mock_cloud:
            mock_local.return_value = {
                "answer": "Hi from Ollama",
                "actual_model": "ollama:qwen3:4b",
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
                "response_time": 0.1,
            }
            _dispatch_send_chat(messages, "ollama:qwen3:4b")
            mock_local.assert_called_once()
            mock_cloud.assert_not_called()

    # ------------------------------------------------------------------
    # 7. Oversized single message triggers exceeds_essential safely
    # ------------------------------------------------------------------
    def test_07_oversized_message_exceeds_essential_no_crash(self):
        """A message larger than the entire budget sets exceeds_essential without crashing."""
        from core.context_budget import prepare_budgeted_messages, get_model_context_budget

        budget = get_model_context_budget("ollama:qwen3:4b")
        # ~25,000 tokens: clearly over any budget
        huge_content = "word " * 25000
        messages = [
            {"role": "system", "content": "You are AIZEN AI."},
            {"role": "user",   "content": huge_content},
        ]

        budgeted, was_pruned, stats = prepare_budgeted_messages(messages, "ollama:qwen3:4b")
        self.assertTrue(stats.get("exceeds_essential"),
                        "Oversized payload must set exceeds_essential=True")
        # Must not crash and must return the essential messages
        self.assertIsInstance(budgeted, list)
        self.assertGreater(len(budgeted), 0)

    # ------------------------------------------------------------------
    # 8. Cloud model budget is unchanged
    # ------------------------------------------------------------------
    def test_08_cloud_model_budget_unchanged(self):
        """The Groq cloud model context budget must not be affected by local fixes."""
        from core.context_budget import get_model_context_budget

        groq_budget = get_model_context_budget("groq/openai/gpt-oss-120b")
        # Must equal 8000 TPM × 0.80 safety factor = 6400 (default)
        self.assertEqual(groq_budget, 6400,
                         "Groq cloud budget must remain 6400 tokens")

        # Cloud budget must not be confused with Ollama budget
        ollama_budget = get_model_context_budget("ollama:qwen3:4b")
        self.assertNotEqual(ollama_budget, groq_budget,
                            "Local and cloud budgets must be distinct")


if __name__ == "__main__":
    unittest.main(verbosity=2)
