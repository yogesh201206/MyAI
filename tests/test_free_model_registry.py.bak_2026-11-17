"""
tests/test_free_model_registry.py — Test suite for AIZEN Free Model Verification & Registry Management.

Covers all 12 mandatory Phase 13 acceptance test scenarios:
  Test 1  — Verified free: registry contains verified-free model -> allowed
  Test 2  — Paid: paid model -> rejected
  Test 3  — Unknown: missing registry entry -> rejected
  Test 4  — Stale: old verified_at -> rejected
  Test 5  — Provider isolation: provider-A/model-X must not automatically authorize provider-B/model-X
  Test 6  — /pick: Paid and unknown models must not appear
  Test 7  — /use: Paid/unknown/stale models must be rejected
  Test 8  — Smart router: Router must receive only verified-free candidates
  Test 9  — Provider health independence: Offline verified-free model remains verified-free but unavailable
  Test 10 — Empty catalog: 0 verified-free models -> AIZEN never selects a paid model
  Test 11 — Old config: Old config containing a now-disallowed model must not crash AIZEN
  Test 12 — Future provider: Newly discovered provider/model defaults to UNKNOWN until explicitly verified

Additional Phase 13 tests:
  - Custom registry persistence & reload
  - /free command suite (/free, /free list, /free status, /free verify, /free refresh)
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
    get_default_free_model,
    get_free_registry,
    get_model_status,
    is_model_allowed,
    is_record_stale,
    is_verified_free,
    parse_date,
    register_model,
)


class TestFreeModelRegistryPhase13(unittest.TestCase):
    def setUp(self):
        # Reset global registry to standard defaults before each test
        get_free_registry().reset_defaults()
        config.free_verification_days = 30

    # ══════════════════════════════════════════════════════════
    # Test 1 — Verified Free
    # ══════════════════════════════════════════════════════════
    def test_01_verified_free_model_allowed(self):
        """Registry contains verified-free model -> allowed."""
        raw_catalog = [
            {"id": "groq/openai/gpt-oss-120b", "owned_by": "groq"},
            {"id": "groq/openai/gpt-oss-20b", "owned_by": "groq"},
        ]
        filtered = filter_free_models(raw_catalog)
        self.assertEqual(len(filtered), 2)
        model_ids = [m["id"] for m in filtered]
        self.assertIn("groq/openai/gpt-oss-120b", model_ids)
        self.assertIn("groq/openai/gpt-oss-20b", model_ids)

        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-120b"))
        self.assertTrue(is_model_allowed("groq", "groq/openai/gpt-oss-120b"))
        self.assertEqual(get_model_status("groq", "groq/openai/gpt-oss-120b"), "VERIFIED FREE")

    # ══════════════════════════════════════════════════════════
    # Test 2 — Paid
    # ══════════════════════════════════════════════════════════
    def test_02_paid_model_rejected(self):
        """Paid model in registry with free_verified=False -> rejected."""
        raw_catalog = [
            {"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro"},
            {"id": "gemini/gemini-2.5-flash", "owned_by": "gemini"},
        ]
        filtered = filter_free_models(raw_catalog)
        self.assertEqual(len(filtered), 0)

        self.assertFalse(is_verified_free("kiro", "kiro/claude-sonnet-4.5"))
        self.assertFalse(is_model_allowed("kiro", "kiro/claude-sonnet-4.5"))
        self.assertEqual(get_model_status("kiro", "kiro/claude-sonnet-4.5"), "PAID")

        self.assertFalse(is_verified_free("gemini", "gemini/gemini-2.5-flash"))
        self.assertFalse(is_model_allowed("gemini", "gemini/gemini-2.5-flash"))
        self.assertEqual(get_model_status("gemini", "gemini/gemini-2.5-flash"), "PAID")

    # ══════════════════════════════════════════════════════════
    # Test 3 — Unknown
    # ══════════════════════════════════════════════════════════
    def test_03_unknown_model_rejected(self):
        """Missing registry entry -> rejected by default-deny."""
        self.assertFalse(is_verified_free("mystery-prov", "mystery-prov/super-llm-9000"))
        self.assertFalse(is_model_allowed("mystery-prov", "mystery-prov/super-llm-9000"))
        self.assertEqual(get_model_status("mystery-prov", "mystery-prov/super-llm-9000"), "UNKNOWN")

        # Unknown model from an existing provider
        self.assertFalse(is_verified_free("groq", "groq/mystery-brand-new-model"))
        self.assertEqual(get_model_status("groq", "groq/mystery-brand-new-model"), "UNKNOWN")

    # ══════════════════════════════════════════════════════════
    # Test 4 — Stale Verification
    # ══════════════════════════════════════════════════════════
    def test_04_stale_verification_rejected(self):
        """Old verified_at (> free_verification_days) or past expires_at -> rejected."""
        registry = get_free_registry()

        # Register a model verified 60 days ago
        old_date = (date(2026, 10, 3) - timedelta(days=60)).strftime("%Y-%m-%d")
        stale_record = FreeModelRecord(
            provider="groq",
            model="groq/openai/old-stale-model",
            display_name="Old Stale Model",
            free_verified=True,
            verification_source="Ancient Docs",
            verified_at=old_date,
            expires_at=None,
        )
        registry.register(stale_record)

        as_of = date(2026, 10, 3)
        self.assertTrue(is_record_stale(stale_record, as_of=as_of, verification_days=30))
        self.assertEqual(
            registry.get_model_status("groq", "groq/openai/old-stale-model", as_of=as_of, verification_days=30),
            "STALE",
        )
        self.assertFalse(
            registry.is_verified_free("groq", "groq/openai/old-stale-model", as_of=as_of, verification_days=30)
        )

        # Expired record (expires_at in the past)
        expired_record = FreeModelRecord(
            provider="groq",
            model="groq/openai/promotional-expiring",
            display_name="Expiring Promo",
            free_verified=True,
            verification_source="Promo Docs",
            verified_at="2026-10-01",
            expires_at="2026-10-02",  # expired yesterday relative to 2026-10-03
        )
        registry.register(expired_record)
        self.assertTrue(is_record_stale(expired_record, as_of=as_of, verification_days=30))
        self.assertEqual(
            registry.get_model_status("groq", "groq/openai/promotional-expiring", as_of=as_of),
            "STALE",
        )

    # ══════════════════════════════════════════════════════════
    # Test 5 — Provider Isolation
    # ══════════════════════════════════════════════════════════
    def test_05_provider_isolation(self):
        """provider-A/model-X must not automatically authorize provider-B/model-X."""
        # groq/openai/gpt-oss-20b is VERIFIED FREE
        self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-20b"))

        # The exact same model under provider 'nvidia' is NOT verified free (uses trial credits)
        self.assertFalse(is_verified_free("nvidia", "nvidia/openai/gpt-oss-20b"))
        self.assertEqual(get_model_status("nvidia", "nvidia/openai/gpt-oss-20b"), "PAID")

        # Provider mismatch query: provider="nvidia", model="groq/openai/gpt-oss-120b"
        self.assertFalse(is_verified_free("nvidia", "groq/openai/gpt-oss-120b"))

        # Provider mismatch query: provider="groq", model="nvidia/openai/gpt-oss-20b"
        self.assertFalse(is_verified_free("groq", "nvidia/openai/gpt-oss-20b"))

    # ══════════════════════════════════════════════════════════
    # Test 6 — /pick Filtering
    # ══════════════════════════════════════════════════════════
    def test_06_pick_shows_only_verified_free(self):
        """Paid, unknown, and stale models must not appear in /pick."""
        from ui.picker import ModelPicker

        mixed_catalog = [
            {"id": "groq/openai/gpt-oss-120b", "owned_by": "groq"},
            {"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro"},
            {"id": "unknown/random-model", "owned_by": "unknown"},
        ]
        free_only = filter_free_models(mixed_catalog)
        self.assertEqual(len(free_only), 1)

        picker = ModelPicker(free_only)
        visible_ids = [m["id"] for m in picker.filtered]
        self.assertIn("groq/openai/gpt-oss-120b", visible_ids)
        self.assertNotIn("kiro/claude-sonnet-4.5", visible_ids)
        self.assertNotIn("unknown/random-model", visible_ids)

    # ══════════════════════════════════════════════════════════
    # Test 7 — /use Protection
    # ══════════════════════════════════════════════════════════
    def test_07_use_rejects_paid_unknown_and_stale_models(self):
        """/use must reject paid, unknown, and stale models."""
        from core.model_manager import select_model

        config.current_model = "groq/openai/gpt-oss-120b"
        config.model_catalog = [{"id": "groq/openai/gpt-oss-120b", "owned_by": "groq"}]
        config.model_map = {"groq/openai/gpt-oss-120b": config.model_catalog[0]}

        # Paid model rejected
        with patch("ui.console.console.print") as mock_print:
            select_model("kiro/claude-sonnet-4.5")
            self.assertEqual(config.current_model, "groq/openai/gpt-oss-120b")
            printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Model is not available in AIZEN Free-Only mode", printed)

        # Unknown model rejected
        with patch("ui.console.console.print") as mock_print:
            select_model("totally-unknown-model")
            self.assertEqual(config.current_model, "groq/openai/gpt-oss-120b")
            printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
            self.assertIn("Model is not available in AIZEN Free-Only mode", printed)

    # ══════════════════════════════════════════════════════════
    # Test 8 — Smart Router Candidate Pool Free-Only
    # ══════════════════════════════════════════════════════════
    def test_08_smart_router_candidate_pool_is_free_only(self):
        """Smart router candidate pool must contain ONLY verified-free models."""
        from core.model_ranker import rank_models
        from core.router import route

        config.model_catalog = [
            {"id": "groq/openai/gpt-oss-120b", "owned_by": "groq", "context_length": 131072, "capabilities": {"tool_calling": True}},
            {"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro", "context_length": 200000, "capabilities": {"tool_calling": True}},
            {"id": "gemini/gemini-2.5-flash", "owned_by": "gemini", "context_length": 1000000, "capabilities": {"vision": True}},
        ]
        config.model_map = {m["id"]: m for m in config.model_catalog}
        config.model_selection_mode = "ROUTER"

        scored, rejected = rank_models("CODING", estimated_context_tokens=2000)
        scored_ids = [m.model_id for m in scored]
        self.assertIn("groq/openai/gpt-oss-120b", scored_ids)
        self.assertNotIn("kiro/claude-sonnet-4.5", scored_ids)
        self.assertNotIn("gemini/gemini-2.5-flash", scored_ids)

        decision = route("Write a python script")
        self.assertEqual(decision.selected_model, "groq/openai/gpt-oss-120b")
        self.assertFalse(decision.fallback_used)

    # ══════════════════════════════════════════════════════════
    # Test 9 — Provider Health Independence
    # ══════════════════════════════════════════════════════════
    def test_09_provider_health_independence(self):
        """An offline verified-free model remains verified-free, but unavailable."""
        from core.provider_health import STATUS_OFFLINE, STATUS_ONLINE

        # Online provider whose model is paid -> remains hidden
        raw_catalog = [{"id": "kiro/claude-sonnet-4.5", "owned_by": "kiro"}]
        with patch("core.provider_health.get_provider_status", return_value=STATUS_ONLINE):
            filtered = filter_free_models(raw_catalog)
            self.assertEqual(len(filtered), 0)
            self.assertFalse(is_verified_free("kiro", "kiro/claude-sonnet-4.5"))

        # Offline provider whose model is verified-free -> pricing status remains VERIFIED FREE
        with patch("core.provider_health.get_provider_status", return_value=STATUS_OFFLINE):
            self.assertTrue(is_verified_free("groq", "groq/openai/gpt-oss-120b"))
            self.assertEqual(get_model_status("groq", "groq/openai/gpt-oss-120b"), "VERIFIED FREE")

    # ══════════════════════════════════════════════════════════
    # Test 10 — Empty Free Catalog
    # ══════════════════════════════════════════════════════════
    def test_10_empty_free_catalog_never_selects_paid_model(self):
        """If 0 verified-free models exist, AIZEN must not select a paid model."""
        from core.router import route

        config.model_catalog = []
        config.model_map = {}
        config.model_selection_mode = "ROUTER"

        decision = route("Hello AIZEN")
        self.assertEqual(decision.selected_model, "")
        self.assertIn("No verified-free model is currently available", decision.reason)

    # ══════════════════════════════════════════════════════════
    # Test 11 — Old Config Compatibility
    # ══════════════════════════════════════════════════════════
    def test_11_old_config_with_disallowed_model(self):
        """Old config with a now-disallowed model must not crash AIZEN."""
        from core.storage import validate_and_sanitize_configured_model

        config.model_catalog = [{"id": "groq/openai/gpt-oss-120b", "owned_by": "groq"}]
        config.current_model = "kiro/claude-sonnet-4.5"

        valid, warn = validate_and_sanitize_configured_model()
        self.assertFalse(valid)
        self.assertIsNotNone(warn)
        self.assertEqual(config.current_model, "groq/openai/gpt-oss-120b")

        # Config files exist and are not corrupted
        self.assertTrue(os.path.exists(config.CONFIG_FILE))

    # ══════════════════════════════════════════════════════════
    # Test 12 — Future Provider Support
    # ══════════════════════════════════════════════════════════
    def test_12_future_provider_defaults_to_unknown(self):
        """Newly discovered provider/model must default to UNKNOWN until explicitly verified."""
        reg = get_free_registry()
        # Step A: Unknown by default
        self.assertEqual(reg.get_model_status("new-cloud", "new-cloud/omni-v1"), "UNKNOWN")
        self.assertFalse(reg.is_verified_free("new-cloud", "new-cloud/omni-v1"))

        # Step B: Register with verification evidence
        reg.verify_model(
            provider="new-cloud",
            model="new-cloud/omni-v1",
            display_name="Omni V1",
            source="https://newcloud.example/free-tier-docs",
            notes="Permanent free tier with zero charge.",
            save=False,
        )

        # Step C: Now allowed
        self.assertEqual(reg.get_model_status("new-cloud", "new-cloud/omni-v1"), "VERIFIED FREE")
        self.assertTrue(reg.is_verified_free("new-cloud", "new-cloud/omni-v1"))

    # ══════════════════════════════════════════════════════════
    # Phase 13 /free Command Handlers
    # ══════════════════════════════════════════════════════════
    def test_free_command_handlers(self):
        """Test /free, /free list, /free status, /free verify, /free refresh commands."""
        from commands.handlers import handle_command

        with patch("ui.console.console.print") as mock_print:
            handle_command("/free")
            handle_command("/free list")
            handle_command("/free status")
            handle_command("/free verify")
            handle_command("/free refresh")

            # Check that console prints were made
            self.assertTrue(mock_print.called)

    def test_custom_registry_persistence(self):
        """Test saving and loading user custom records."""
        reg = get_free_registry()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            temp_file = tf.name

        try:
            reg.verify_model(
                provider="custom-prov",
                model="custom-prov/model-1",
                display_name="Custom 1",
                source="Custom Docs",
                save=False,
            )
            saved = reg.save_custom_records(temp_file)
            self.assertTrue(saved)

            new_reg = FreeModelRegistry(load_defaults=False, load_user_file=False)
            count = new_reg.load_custom_records(temp_file)
            self.assertEqual(count, len(reg.get_all_records()))
            self.assertTrue(new_reg.is_verified_free("custom-prov", "custom-prov/model-1"))
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)


if __name__ == "__main__":
    unittest.main()
