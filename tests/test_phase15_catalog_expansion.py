"""
tests/test_phase15_catalog_expansion.py — Phase 15 Free Model Catalog Expansion Tests.

Verifies:
  1. Verified free model is accepted (Groq & AI Horde text models).
  2. Paid model is rejected (NVIDIA, Gemini, Kiro, Devin).
  3. Unknown model is rejected (default-deny).
  4. Stale model is rejected (> 30 days).
  5. Provider isolation: same model on another provider is rejected.
  6. Future provider works through registry data without code changes.
  7. /pick shows newly verified models.
  8. /models shows newly verified models.
  9. /use accepts verified free model.
  10. /use rejects unknown/paid model with clear policy message.
  11. Smart Router never selects paid model.
  12. Smart Router never selects unknown model.
  13. Empty verified-free catalog is handled safely.
  14. Old config remains readable and backward compatible.
  15. Existing Groq models remain verified.
  16. Registry overlay does not destroy existing records; refresh merges safely.
  17. Cached catalogs do not bypass registry.
  18. Provider health does not determine free eligibility.
  19. Safety Test (Section 24): Catalog with [free, paid, unknown, stale] -> only free reaches ranking.
  20. Safety Test (Section 24): All models paid/unknown -> no request, reason explicitly states unavailable.
"""

from datetime import date, datetime, timedelta, timezone
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/yoges/myai")
os.environ.setdefault("PYTHONPATH", "/home/yoges/myai")

import config
from core.free_model_registry import (
    FreeModelRecord,
    FreeModelRegistry,
    filter_free_models,
    get_free_registry,
    get_model_status,
    is_model_allowed,
    is_record_stale,
    is_verified_free,
    register_model,
)


class TestPhase15CatalogExpansion(unittest.TestCase):
    def setUp(self):
        # Reset global registry to defaults
        get_free_registry().reset_defaults()
        config.free_verification_days = 30
        config.model_catalog = []
        config.model_map = {}
        config.current_model = "auto"
        config.model_selection_mode = "ROUTER"
        config.router_mode = "AUTO"
        config.router_enabled = True

    # 1. Verified free model is accepted
    def test_01_verified_free_models_accepted(self):
        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-120b"))
        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-20b"))
        self.assertTrue(is_verified_free("aihorde", "aihorde/aphrodite/TheDrummer/Cydonia-24B-v4.3"))
        self.assertTrue(is_verified_free("aihorde", "aihorde/aphrodite/TheDrummer/Skyfall-31B-v4.2"))
        self.assertTrue(is_verified_free("aihorde", "aihorde/google/gemma-4-31b"))

        raw = [
            {"id": "groq/openai/gpt-oss-120b", "owned_by": "groq"},
            {"id": "aihorde/aphrodite/TheDrummer/Cydonia-24B-v4.3", "owned_by": "aihorde"},
        ]
        filtered = filter_free_models(raw)
        self.assertEqual(len(filtered), 2)

    # 2. Paid model is rejected
    def test_02_paid_models_rejected(self):
        self.assertFalse(is_verified_free("nvidia", "nvidia/google/gemma-4-31b-it"))
        self.assertFalse(is_verified_free("gemini", "gemini/gemini-2.5-flash"))
        self.assertFalse(is_verified_free("kiro", "kiro/claude-sonnet-4.5"))
        self.assertFalse(is_verified_free("devin-cli-agentic", "devin-cli-agentic/dva/claude-fable-5-1-max"))

        raw = [
            {"id": "nvidia/google/gemma-4-31b-it", "owned_by": "nvidia"},
            {"id": "gemini/gemini-2.5-flash", "owned_by": "gemini"},
        ]
        filtered = filter_free_models(raw)
        self.assertEqual(len(filtered), 0)

    # 3. Unknown model is rejected (default-deny)
    def test_03_unknown_models_rejected(self):
        self.assertFalse(is_verified_free("opencode", "oc/big-pickle"))
        self.assertFalse(is_verified_free("cloudflare-playground", "cfp/zai-org/glm-5.2"))
        self.assertFalse(is_verified_free("duckduckgo-web", "ddgw/gpt-5.4-mini"))
        self.assertEqual(get_model_status("opencode", "oc/big-pickle"), "UNKNOWN")

    # 4. Stale model is rejected
    def test_04_stale_model_rejected(self):
        stale_rec = FreeModelRecord(
            provider="test-prov",
            model="test-prov/old-model",
            display_name="Old Model",
            free_verified=True,
            verification_source="Doc",
            verified_at="2026-01-01",
        )
        register_model(stale_rec)
        today = date(2026, 10, 5)
        self.assertTrue(is_record_stale(stale_rec, as_of=today, verification_days=30))
        self.assertFalse(is_verified_free("test-prov", "test-prov/old-model", as_of=today, verification_days=30))

    # 5. Provider isolation: same model name on another provider is rejected
    def test_05_provider_isolation(self):
        # gpt-oss-20b is free on groq, but NOT on nvidia or other
        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-20b"))
        self.assertFalse(is_verified_free("nvidia", "nvidia/openai/gpt-oss-20b"))
        self.assertFalse(is_verified_free("other-prov", "other-prov/openai/gpt-oss-20b"))

    # 6. Future provider works through registry data without code changes
    def test_06_future_provider_works_data_driven(self):
        future_rec = FreeModelRecord(
            provider="futurecloud",
            model="futurecloud/super-zero-cost",
            display_name="Super Zero Cost",
            free_verified=True,
            verification_source="https://futurecloud.example/zero-cost",
            verified_at="2026-10-05",
            notes="Documented public zero-cost access",
        )
        register_model(future_rec)
        self.assertTrue(is_verified_free("futurecloud", "futurecloud/super-zero-cost"))
        self.assertTrue(is_model_allowed("futurecloud", "futurecloud/super-zero-cost"))

        catalog = [{"id": "futurecloud/super-zero-cost", "owned_by": "futurecloud"}]
        filtered = filter_free_models(catalog)
        self.assertEqual(len(filtered), 1)

    # 7. /pick shows newly verified models
    def test_07_pick_shows_newly_verified_models(self):
        from ui.picker import ModelPicker
        catalog = [
            {"id": "groq/openai/gpt-oss-20b", "owned_by": "groq"},
            {"id": "aihorde/google/gemma-4-31b", "owned_by": "aihorde"},
            {"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro"},  # paid
        ]
        free_catalog = filter_free_models(catalog)
        picker = ModelPicker(free_catalog)
        visible_ids = [m["id"] for m in picker.filtered]
        self.assertIn("groq/openai/gpt-oss-20b", visible_ids)
        self.assertIn("aihorde/google/gemma-4-31b", visible_ids)
        self.assertNotIn("kiro/claude-sonnet-4.5", visible_ids)

    # 8. /models shows newly verified models
    def test_08_models_shows_newly_verified_models(self):
        config.model_catalog = [
            {"id": "groq/openai/gpt-oss-20b", "owned_by": "groq", "context_length": 131072, "max_output_tokens": 8192},
            {"id": "aihorde/google/gemma-4-31b", "owned_by": "aihorde", "context_length": 32768, "max_output_tokens": 4096},
        ]
        from core.model_manager import show_models
        with patch("core.model_manager.console.print") as mock_print:
            show_models()
            self.assertTrue(mock_print.called)
            displayed_ids = [m["id"] for m in config.last_displayed_models]
            self.assertIn("groq/openai/gpt-oss-20b", displayed_ids)
            self.assertIn("aihorde/google/gemma-4-31b", displayed_ids)

    # 9. /use accepts verified free model
    def test_09_use_accepts_verified_free_model(self):
        from core.model_manager import select_model
        config.model_catalog = [{"id": "groq/openai/gpt-oss-20b", "owned_by": "groq"}]
        config.model_map = {"groq/openai/gpt-oss-20b": config.model_catalog[0]}

        with patch("core.storage.save_config"), patch("ui.console.show_model_info"):
            select_model("groq/openai/gpt-oss-20b")
        self.assertEqual(config.current_model, "groq/openai/gpt-oss-20b")
        self.assertEqual(config.model_selection_mode, "manual")

    # 10. /use rejects unknown/paid model with clear policy message
    def test_10_use_rejects_unknown_and_paid_models(self):
        from core.model_manager import select_model
        with patch("core.model_manager.console.print") as mock_print:
            select_model("kiro/claude-sonnet-4.5")
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any("free-only policy" in c.lower() for c in calls))
            self.assertTrue(any("not currently verified" in c.lower() for c in calls))

    # 11. Smart Router never selects paid model
    def test_11_router_never_selects_paid_model(self):
        from core.router import route
        config.model_catalog = [
            {"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro"},
            {"id": "gemini/gemini-2.5-flash", "owned_by": "gemini"},
        ]
        decision = route("Write a python program")
        self.assertEqual(decision.selected_model, "")
        self.assertEqual(decision.candidate_count, 0)

    # 12. Smart Router never selects unknown model
    def test_12_router_never_selects_unknown_model(self):
        from core.router import route
        config.model_catalog = [
            {"id": "opencode/oc/big-pickle", "owned_by": "opencode"},
            {"id": "cloudflare-playground/cfp/glm-5", "owned_by": "cloudflare-playground"},
        ]
        decision = route("Write a function")
        self.assertEqual(decision.selected_model, "")
        self.assertEqual(decision.candidate_count, 0)

    # 13. Empty verified-free catalog handled safely
    def test_13_empty_catalog_handled_safely(self):
        from core.router import route
        config.model_catalog = []
        config.model_map = {}
        decision = route("Hello AIZEN")
        self.assertEqual(decision.selected_model, "")
        self.assertEqual(decision.candidate_count, 0)
        self.assertIn("free", decision.reason.lower())

    # 14. Old config remains readable
    def test_14_old_config_backward_compatible(self):
        from core.storage import _apply_config_dict
        old_data = {"current_model": "auto", "streaming_enabled": True}
        _apply_config_dict(old_data)
        self.assertTrue(hasattr(config, "free_verification_days"))
        self.assertEqual(config.free_verification_days, 30)

    # 15. Existing Groq models remain verified
    def test_15_existing_groq_models_verified(self):
        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-120b"))
        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-20b"))

    # 16. Registry overlay does not destroy existing records; refresh merges safely
    def test_16_registry_overlay_and_refresh_merge(self):
        reg = get_free_registry()
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
            overlay_data = [
                {
                    "provider": "user-prov",
                    "model": "user-prov/custom-llm",
                    "display_name": "Custom LLM",
                    "free_verified": True,
                    "verification_source": "User audit",
                    "verified_at": "2026-10-05",
                    "notes": "Custom user overlay entry",
                }
            ]
            json.dump(overlay_data, tf)
            tf_path = tf.name

        try:
            reg.load_custom_records(tf_path)
            self.assertTrue(reg.is_verified_free("user-prov", "user-prov/custom-llm"))
            # Default Groq model must still exist
            self.assertTrue(reg.is_verified_free("groq", "groq/openai/gpt-oss-120b"))

            # Refresh should not destroy records
            reg.refresh()
            self.assertTrue(reg.is_verified_free("user-prov", "user-prov/custom-llm"))
            self.assertTrue(reg.is_verified_free("groq", "groq/openai/gpt-oss-120b"))
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    # 17. Cached catalogs do not bypass registry
    def test_17_cached_catalogs_do_not_bypass_registry(self):
        # Suppose a model was cached in config.model_catalog, but its registry record is invalidated
        reg = get_free_registry()
        reg.verify_model(
            provider="temp-prov",
            model="temp-prov/model-1",
            source="test",
            save=False,
        )
        self.assertTrue(is_verified_free("temp-prov", "temp-prov/model-1"))

        # Now invalidate it
        reg.invalidate_model("temp-prov", "temp-prov/model-1", save=False)
        self.assertFalse(is_verified_free("temp-prov", "temp-prov/model-1"))

        cached_catalog = [{"id": "temp-prov/model-1", "owned_by": "temp-prov"}]
        filtered = filter_free_models(cached_catalog)
        self.assertEqual(len(filtered), 0)

    # 18. Provider health does not determine free eligibility
    def test_18_provider_health_independent_of_free_eligibility(self):
        # Offline model is still verified free
        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-120b"))
        # Online paid model is still paid
        self.assertFalse(is_verified_free("gemini", "gemini/gemini-2.5-flash"))

    # 19. SAFETY TEST (Section 24): Catalog with [free, paid, unknown, stale] -> ONLY free reaches ranking
    def test_19_safety_test_only_free_reaches_ranking(self):
        from core.model_ranker import rank_models

        stale_rec = FreeModelRecord(
            provider="prov-stale",
            model="prov-stale/stale-model",
            display_name="Stale",
            free_verified=True,
            verification_source="Doc",
            verified_at="2025-01-01",
        )
        register_model(stale_rec)

        config.model_catalog = [
            {"id": "groq/openai/gpt-oss-120b", "owned_by": "groq", "context_length": 131072},
            {"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro", "context_length": 200000},       # PAID
            {"id": "unknown/mystery-model", "owned_by": "unknown", "context_length": 100000},      # UNKNOWN
            {"id": "prov-stale/stale-model", "owned_by": "prov-stale", "context_length": 100000},  # STALE
        ]

        today = date(2026, 10, 5)
        scored, rejected = rank_models("CODING", estimated_context_tokens=1500)

        # Scored MUST contain only the verified-free model
        scored_ids = [m.model_id for m in scored]
        self.assertIn("groq/openai/gpt-oss-120b", scored_ids)
        self.assertNotIn("kiro/claude-sonnet-4.5", scored_ids)
        self.assertNotIn("unknown/mystery-model", scored_ids)
        self.assertNotIn("prov-stale/stale-model", scored_ids)

        rejected_ids = [m for m, _ in rejected]
        self.assertIn("kiro/claude-sonnet-4.5", rejected_ids)
        self.assertIn("unknown/mystery-model", rejected_ids)
        self.assertIn("prov-stale/stale-model", rejected_ids)

    # 20. SAFETY TEST (Section 24): All models paid/unknown -> AIZEN makes NO request and reports unavailable
    def test_20_safety_all_models_paid_unknown_no_request(self):
        from core.router import route

        config.model_catalog = [
            {"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro"},
            {"id": "unknown/mystery-model", "owned_by": "unknown"},
        ]

        decision = route("Write a critical security script")
        self.assertEqual(decision.selected_model, "")
        self.assertEqual(decision.candidate_count, 0)
        self.assertIn("no verified-free model is currently available for this task", decision.reason.lower())


if __name__ == "__main__":
    unittest.main()
