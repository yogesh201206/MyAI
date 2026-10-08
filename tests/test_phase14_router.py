"""
tests/test_phase14_router.py — Phase 14 Free Smart Router Test Suite

16 router tests + 8 task classifier tests.
"""

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/home/yoges/myai")


# ===========================================================
# HELPERS
# ===========================================================

def _free_record(provider: str, model: str, days_ago: int = 0):
    from core.free_model_registry import FreeModelRecord, STATUS_VERIFIED
    return FreeModelRecord(
        provider=provider,
        model_id=model,
        free_verified=True,
        status=STATUS_VERIFIED,
        verified_at=date.today() - timedelta(days=days_ago),
        notes="test record",
    )


def _paid_record(provider: str, model: str):
    from core.free_model_registry import FreeModelRecord, STATUS_PAID
    return FreeModelRecord(
        provider=provider,
        model_id=model,
        free_verified=False,
        status=STATUS_PAID,
        verified_at=date.today(),
        notes="paid model",
    )


# ===========================================================
# ROUTER TESTS
# ===========================================================

class TestPhase14FreeSmartRouter(unittest.TestCase):

    def setUp(self):
        import config
        config.model_catalog = []
        config.model_map = {}
        config.current_model = "auto"
        config.model_selection_mode = "ROUTER"
        config.router_mode = "AUTO"
        config.router_enabled = True
        config.router_max_fallbacks = 2
        config.router_verbose = False
        config.last_routing_decision = None
        config.routing_history = []
        config.router_capability_weight  = 0.40
        config.router_context_weight     = 0.20
        config.router_health_weight      = 0.20
        config.router_reliability_weight = 0.15
        config.router_latency_weight     = 0.05
        config.project_mode = False
        config.active_project_path = None
        config.rag_enabled = False
        config.last_command_result = None

    # 1 — Paid model excluded BEFORE scoring
    def test_01_paid_model_excluded_before_scoring(self):
        """Paid model must be in rejected list, not scored."""
        import config
        config.model_catalog = [{"id": "groq/paid-model", "owned_by": "groq"}]

        with patch("core.free_model_registry.is_model_allowed", side_effect=lambda prov, mid: False):
            from core.model_ranker import rank_models
            scored, rejected = rank_models("CODING", estimated_context_tokens=1500)

        self.assertEqual(len(scored), 0, "Paid model must not appear in scored list")
        self.assertTrue(
            any("paid-model" in m for m, _ in rejected),
            "Paid model must appear in rejected list"
        )

    # 2 — Unknown model excluded
    def test_02_unknown_model_excluded(self):
        """Model not in registry → excluded."""
        import config
        config.model_catalog = [{"id": "unknown-provider/mystery-model", "owned_by": "unknown-provider"}]

        with patch("core.free_model_registry.is_model_allowed", side_effect=lambda prov, mid: False):
            from core.model_ranker import rank_models
            scored, rejected = rank_models("CHAT", estimated_context_tokens=1500)

        self.assertEqual(len(scored), 0)
        self.assertTrue(any("mystery-model" in m for m, _ in rejected))

    # 3 — Stale model excluded
    def test_03_stale_model_excluded(self):
        """Stale record → excluded by free-policy."""
        import config
        config.model_catalog = [{"id": "groq/stale-model", "owned_by": "groq"}]

        with patch("core.free_model_registry.is_model_allowed", side_effect=lambda prov, mid: False):
            from core.model_ranker import rank_models
            scored, rejected = rank_models("CHAT")

        self.assertEqual(len(scored), 0)
        self.assertTrue(any("stale-model" in m for m, _ in rejected))

    # 4 — Verified-free model enters router
    def test_04_verified_free_model_enters_router(self):
        """A verified-free model must appear in scored list."""
        import config
        config.model_catalog = [{"id": "groq/free-coder", "owned_by": "groq"}]

        with patch("core.free_model_registry.is_model_allowed", return_value=True), \
             patch("core.model_ranker.get_provider_for_model", return_value="groq"), \
             patch("core.model_ranker.get_provider_status", return_value="ONLINE"), \
             patch("core.model_ranker.get_provider_record", return_value=None):
            from core.model_ranker import rank_models
            scored, rejected = rank_models("CODING", estimated_context_tokens=1500)

        free_rejections = [m for m, r in rejected if "free" in r.lower()]
        self.assertEqual(len(free_rejections), 0)
        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].model_id, "groq/free-coder")

    # 5 — Offline free model scores lower than online
    def test_05_offline_free_model_not_preferred_over_healthy(self):
        """ONLINE provider must score higher than OFFLINE."""
        from core.provider_health import STATUS_ONLINE, STATUS_OFFLINE
        from core.model_ranker import _score_provider_health

        online_pts, _ = _score_provider_health(STATUS_ONLINE)
        offline_pts, _ = _score_provider_health(STATUS_OFFLINE)
        self.assertGreater(online_pts, offline_pts)

    # 6 — Context-incompatible model rejected
    def test_06_context_incompatible_model_rejected(self):
        """Model with context_length < required tokens must be rejected."""
        import config
        config.model_catalog = [
            {"id": "groq/tiny-ctx", "owned_by": "groq", "context_length": 2000}
        ]

        with patch("core.free_model_registry.is_model_allowed", return_value=True), \
             patch("core.model_ranker.get_provider_for_model", return_value="groq"), \
             patch("core.model_ranker.get_provider_status", return_value="ONLINE"), \
             patch("core.model_ranker.get_provider_record", return_value=None):
            from core.model_ranker import rank_models
            scored, rejected = rank_models("CODING", estimated_context_tokens=8000)

        ctx_rejections = [m for m, r in rejected if "context" in r.lower() or "insufficient" in r.lower()]
        self.assertGreater(len(ctx_rejections), 0)
        self.assertEqual(len(scored), 0)

    # 7 — Coding task prefers coder model
    def test_07_coding_task_prefers_coding_model(self):
        """For CODING task, a coder model must score higher than general model."""
        from core.model_ranker import _score_capability
        from core.task_classifier import TASK_CODING

        coder_meta = {"id": "groq/qwen2.5-coder-32b", "owned_by": "groq"}
        chat_meta  = {"id": "groq/general-chat-model", "owned_by": "groq"}

        coder_score, _ = _score_capability(coder_meta, TASK_CODING)
        chat_score,  _ = _score_capability(chat_meta,  TASK_CODING)

        self.assertGreater(coder_score, chat_score)

    # 8 — Large-context task prefers wider model
    def test_08_large_context_task_prefers_wider_model(self):
        """Large-context model must score better for large-context request."""
        from core.model_ranker import _score_context_fit

        large_ctx_meta = {"id": "groq/llama-128k", "context_length": 131072}
        small_ctx_meta = {"id": "groq/llama-4k",   "context_length": 4096}
        req_tokens = 20000

        large_pts, _ = _score_context_fit(large_ctx_meta, req_tokens)
        small_pts, _ = _score_context_fit(small_ctx_meta, req_tokens)

        self.assertGreater(large_pts, small_pts)

    # 9 — Manual /use overrides automatic routing
    def test_09_manual_use_overrides_router(self):
        """When model_selection_mode=manual, route() returns the manual model."""
        import config
        from core.router import route

        config.model_selection_mode = "manual"
        config.current_model = "groq/openai-compatible-model"

        with patch("core.router.get_provider_for_model", return_value="groq"), \
             patch("core.router.classify_task") as mock_classify, \
             patch("core.router.count_free_candidates", return_value=2), \
             patch("core.free_model_registry.is_model_allowed", return_value=True):
            mock_classify.return_value = MagicMock(
                task_type="CHAT", confidence=0.8,
                ranker_task="CHAT",
            )
            decision = route("Hello!")

        self.assertTrue(decision.is_manual_override)
        self.assertEqual(decision.selected_model, "groq/openai-compatible-model")

    # 10 — Manual /use cannot select a paid model
    def test_10_manual_use_cannot_select_paid_model(self):
        """Even in manual mode, a paid model must be rejected."""
        import config
        from core.router import route

        config.model_selection_mode = "manual"
        config.current_model = "groq/paid-tier-model"

        with patch("core.router.get_provider_for_model", return_value="groq"), \
             patch("core.router.classify_task") as mock_classify, \
             patch("core.router.count_free_candidates", return_value=0), \
             patch("core.free_model_registry.is_model_allowed", return_value=False):
            mock_classify.return_value = MagicMock(
                task_type="CHAT", confidence=0.8,
                ranker_task="CHAT",
            )
            decision = route("Do something!")

        self.assertEqual(decision.selected_model, "")
        self.assertTrue(decision.is_manual_override)
        self.assertIn("blocked", decision.reason.lower())

    # 11 — Fallback only uses verified-free models
    def test_11_fallback_only_verified_free(self):
        """get_retry_model must only return verified-free models."""
        import config
        from core.router import get_retry_model

        config.model_selection_mode = "ROUTER"
        config.router_max_fallbacks = 2

        mock_scored = [MagicMock(model_id="groq/fallback-free", provider="groq")]
        with patch("core.router.rank_models", return_value=(mock_scored, [])):
            retry = get_retry_model("groq/failed-model", "groq", attempt=1)

        self.assertEqual(retry, "groq/fallback-free")

    # 12 — Fallback stops after maximum attempts
    def test_12_fallback_stops_at_max_attempts(self):
        """get_retry_model must return None when attempt > max_fallbacks."""
        import config
        from core.router import get_retry_model

        config.router_max_fallbacks = 2
        config.model_selection_mode = "ROUTER"

        retry = get_retry_model("groq/failed-model", "groq", attempt=3)
        self.assertIsNone(retry)

    # 13 — Zero free candidates produces safe empty decision
    def test_13_zero_free_candidates_safe_decision(self):
        """When no verified-free model exists, selected_model must be empty."""
        import config
        from core.router import route

        config.model_selection_mode = "ROUTER"
        config.router_enabled = True

        with patch("core.router.classify_task") as mock_classify, \
             patch("core.router.rank_models", return_value=([], [])), \
             patch("core.router.count_free_candidates", return_value=0), \
             patch("core.router.estimate_request_context_tokens", return_value=1500), \
             patch("core.router._get_weights", return_value={}):
            mock_classify.return_value = MagicMock(
                task_type="CODING", confidence=0.8,
                ranker_task="CODING",
            )
            decision = route("Write a function")

        self.assertEqual(decision.selected_model, "")
        self.assertEqual(decision.candidate_count, 0)
        self.assertIn("free", decision.reason.lower())

    # 14 — Future provider defaults to unknown and excluded
    def test_14_future_provider_unknown_excluded(self):
        """Newly discovered provider/model with no registry entry → excluded."""
        from core.free_model_registry import is_model_allowed
        allowed = is_model_allowed("futureai", "futureai/super-model-v99")
        self.assertFalse(allowed)

    # 15 — Router OFF still enforces free-only policy
    def test_15_router_off_still_enforces_free_policy(self):
        """When router_enabled=False, paid manual model must still be blocked."""
        import config
        from core.router import route

        config.router_enabled = False
        config.model_selection_mode = "manual"
        config.current_model = "groq/paid-model"

        with patch("core.router.get_provider_for_model", return_value="groq"), \
             patch("core.router.classify_task") as mock_classify, \
             patch("core.router.count_free_candidates", return_value=0), \
             patch("core.free_model_registry.is_model_allowed", return_value=False):
            mock_classify.return_value = MagicMock(
                task_type="CHAT", confidence=0.8,
                ranker_task="CHAT",
            )
            decision = route("Hello!")

        self.assertEqual(decision.selected_model, "")
        self.assertIn("blocked", decision.reason.lower())

    # 16 — Backward compatible config defaults
    def test_16_config_backward_compatibility(self):
        """Old config without router weight keys must load safely with defaults."""
        import config
        from core.storage import _apply_config_dict

        old_config_data = {
            "current_model": "auto",
            "streaming_enabled": True,
            "router_mode": "AUTO",
            # No router_enabled, no weight keys
        }
        _apply_config_dict(old_config_data)

        self.assertTrue(config.router_enabled)
        self.assertAlmostEqual(config.router_capability_weight,  0.40, places=2)
        self.assertAlmostEqual(config.router_context_weight,     0.20, places=2)
        self.assertAlmostEqual(config.router_health_weight,      0.20, places=2)
        self.assertAlmostEqual(config.router_reliability_weight, 0.15, places=2)
        self.assertAlmostEqual(config.router_latency_weight,     0.05, places=2)
        self.assertEqual(config.router_max_fallbacks, 2)


# ===========================================================
# TASK CLASSIFIER TESTS
# ===========================================================

class TestPhase14TaskClassifier(unittest.TestCase):

    def _classify(self, prompt: str, **ctx) -> str:
        from core.task_classifier import classify_task
        result = classify_task(prompt, ctx)
        return result.task_type

    def test_debugging_classified(self):
        task = self._classify("Why is this Java NullPointerException happening?")
        self.assertEqual(task, "DEBUGGING")

    def test_code_generation_classified(self):
        task = self._classify("Write me a FastAPI REST endpoint for user login")
        self.assertEqual(task, "CODE_GENERATION")

    def test_summarization_classified(self):
        task = self._classify("Summarize this document for me in bullet points")
        self.assertEqual(task, "SUMMARIZATION")

    def test_translation_classified(self):
        task = self._classify("Translate this text from English to Spanish")
        self.assertEqual(task, "TRANSLATION")

    def test_terminal_classified(self):
        task = self._classify("Why is this bash command failing with exit code 127?")
        self.assertEqual(task, "TERMINAL")

    def test_structured_output_classified(self):
        task = self._classify("Output the result as valid JSON with these fields")
        self.assertEqual(task, "STRUCTURED_OUTPUT")

    def test_creative_writing_classified(self):
        task = self._classify("Write a short story about a robot that learns to paint")
        self.assertEqual(task, "CREATIVE_WRITING")

    def test_ranker_task_mapping(self):
        """Phase 14 sub-tasks must expose ranker_task mapped to a Phase 11 dimension."""
        from core.task_classifier import classify_task
        result = classify_task("Fix this Python AttributeError traceback")
        self.assertTrue(hasattr(result, "ranker_task"))
        self.assertIn(result.ranker_task,
                      {"CODING", "REASONING", "CHAT", "FAST", "RESEARCH", "VISION"})


if __name__ == "__main__":
    unittest.main()
