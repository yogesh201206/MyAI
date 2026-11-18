"""
tests/test_phase15.py — Phase 15 Final QA and Regression Tests

Covers:
  A. Version system
  B. Config load/save/atomic write/recovery
  C. Chat storage atomic write/recovery
  D. OmniRoute detection (mocked)
  E. Storage defaults
  F. debug mode toggle
  G. /doctor command dispatch
  H. /version command dispatch
  I. Provider summary fix
  J. Model system (model_catalog)
  K. Token usage state
  L. Streaming state
  M. Provider health
  N. Voice fallback (no hardware)
  O. Tool registry
  P. Command handler dispatch
  Q. Terminal safety (command_safety)
  R. File path safety
  S. Startup sequence (mocked)
  T. Regression: all modules importable
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure workspace root on path
sys.path.insert(0, "/home/yoges/myai")
os.environ.setdefault("PYTHONPATH", "/home/yoges/myai")


# ══════════════════════════════════════════════════════════
# A. VERSION SYSTEM
# ══════════════════════════════════════════════════════════

class TestVersionSystem(unittest.TestCase):
    def test_version_string_exists(self):
        import config
        self.assertTrue(hasattr(config, "AIZEN_VERSION"))
        self.assertIsInstance(config.AIZEN_VERSION, str)
        self.assertRegex(config.AIZEN_VERSION, r"^\d+\.\d+\.\d+$")

    def test_version_command_no_crash(self):
        """myai.py --version should not raise."""
        from myai import _print_version
        try:
            _print_version()
        except SystemExit:
            pass
        except Exception as e:
            self.fail(f"_print_version() raised: {e}")


# ══════════════════════════════════════════════════════════
# B. CONFIG LOAD/SAVE/ATOMIC/RECOVERY
# ══════════════════════════════════════════════════════════

class TestConfigAtomicWrite(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        from core.storage import _atomic_write
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            _atomic_write(path, {"key": "value"})
            self.assertTrue(os.path.isfile(path))
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["key"], "value")

    def test_atomic_write_no_tmp_left_on_success(self):
        from core.storage import _atomic_write
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            _atomic_write(path, {"x": 1})
            files = os.listdir(tmpdir)
            tmp_files = [f for f in files if f.endswith(".tmp")]
            self.assertEqual(len(tmp_files), 0)

    def test_save_config_creates_backup(self):
        import config
        from core.storage import save_config, _backup_path
        # Save once to create the file
        save_config()
        # Save again — should create backup
        save_config()
        backup = _backup_path(config.CONFIG_FILE)
        self.assertTrue(os.path.isfile(backup))

    def test_load_config_recovers_from_backup(self):
        import config
        from core.storage import save_config, load_config, _backup_path

        # Write a good config
        config.current_model = "test-recovery-model"
        save_config()
        save_config()  # Creates backup of test-recovery-model

        # Corrupt the primary config
        with open(config.CONFIG_FILE, "w") as f:
            f.write("CORRUPTED_JSON{{{{")

        # load_config should recover from backup
        load_config()
        self.assertEqual(config.current_model, "test-recovery-model")

        # Restore
        config.current_model = "auto"
        save_config()

    def test_load_config_applies_all_defaults_on_total_failure(self):
        import config
        from core.storage import _apply_config_defaults
        _apply_config_defaults()
        self.assertEqual(config.current_model, config.DEFAULT_MODEL)
        self.assertFalse(config.voice_enabled)


# ══════════════════════════════════════════════════════════
# C. CHAT STORAGE ATOMIC WRITE/RECOVERY
# ══════════════════════════════════════════════════════════

class TestChatStorage(unittest.TestCase):
    def test_save_chats_creates_backup(self):
        import config
        from core.storage import save_chats, load_chats, _backup_path

        original = config.chats[:]
        config.chats = [{"id": "t1", "title": "Test", "messages": [], "attachments": []}]
        save_chats()
        save_chats()  # second save creates backup

        backup = _backup_path(config.CHATS_FILE)
        self.assertTrue(os.path.isfile(backup))

        # Restore
        config.chats = original
        save_chats()

    def test_load_chats_handles_corruption(self):
        import config
        from core.storage import save_chats, load_chats

        # Save valid chats
        original = config.chats[:]
        save_chats()

        # Corrupt primary
        with open(config.CHATS_FILE, "w") as f:
            f.write("NOT_JSON[[")

        load_chats()  # should not raise
        self.assertIsInstance(config.chats, list)

        # Restore
        config.chats = original
        save_chats()


# ══════════════════════════════════════════════════════════
# D. OMNIROUTE DETECTION (MOCKED)
# ══════════════════════════════════════════════════════════

class TestOmniRouteDetection(unittest.TestCase):
    @patch("requests.get")
    def test_check_connection_returns_true_on_200(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        from api.omniroute import check_connection
        result = check_connection()
        self.assertTrue(result)

    @patch("requests.get", side_effect=Exception("connection refused"))
    def test_check_connection_returns_false_on_error(self, mock_get):
        from api.omniroute import check_connection
        result = check_connection()
        self.assertFalse(result)

    @patch("requests.get")
    def test_fetch_models_returns_true_on_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "test-model"}]}
        mock_get.return_value = mock_resp

        from api.omniroute import fetch_models
        result = fetch_models()
        self.assertTrue(result)

    @patch("requests.get", side_effect=Exception("offline"))
    def test_fetch_models_returns_false_on_failure(self, mock_get):
        from api.omniroute import fetch_models
        result = fetch_models()
        self.assertFalse(result)


# ══════════════════════════════════════════════════════════
# E. STORAGE DEFAULTS
# ══════════════════════════════════════════════════════════

class TestStorageDefaults(unittest.TestCase):
    def test_setup_storage_creates_dirs(self):
        import config
        from core.storage import setup_storage
        setup_storage()
        self.assertTrue(os.path.isdir(config.DATA_DIR))
        self.assertTrue(os.path.isdir(config.VOICE_TMP_DIR))
        self.assertTrue(os.path.isfile(config.CHATS_FILE))
        self.assertTrue(os.path.isfile(config.CONFIG_FILE))


# ══════════════════════════════════════════════════════════
# F. DEBUG MODE TOGGLE
# ══════════════════════════════════════════════════════════

class TestDebugMode(unittest.TestCase):
    def test_debug_mode_default_false(self):
        import config
        from core.storage import _apply_config_defaults
        _apply_config_defaults()
        self.assertFalse(config.debug_mode)

    def test_debug_mode_persists(self):
        import config
        from core.storage import save_config, load_config

        config.debug_mode = True
        save_config()
        config.debug_mode = False
        load_config()
        self.assertTrue(config.debug_mode)

        # Restore
        config.debug_mode = False
        save_config()


# ══════════════════════════════════════════════════════════
# G. /DOCTOR COMMAND
# ══════════════════════════════════════════════════════════

class TestDoctorCommand(unittest.TestCase):
    def test_doctor_handler_does_not_raise(self):
        from commands.handlers import handle_command
        try:
            handle_command("/doctor")
        except SystemExit:
            pass
        except Exception as e:
            self.fail(f"/doctor raised unexpectedly: {e}")


# ══════════════════════════════════════════════════════════
# H. /VERSION COMMAND
# ══════════════════════════════════════════════════════════

class TestVersionCommand(unittest.TestCase):
    def test_version_handler_does_not_raise(self):
        from commands.handlers import handle_command
        try:
            handle_command("/version")
        except Exception as e:
            self.fail(f"/version raised unexpectedly: {e}")


# ══════════════════════════════════════════════════════════
# I. PROVIDER SUMMARY FIX (show_aizen_home)
# ══════════════════════════════════════════════════════════

class TestProviderSummaryFix(unittest.TestCase):
    def test_show_aizen_home_does_not_crash(self):
        """show_aizen_home must not raise even with no active connection."""
        from ui.console import show_aizen_home
        with patch("api.omniroute.check_connection", return_value=False):
            try:
                show_aizen_home()
            except Exception as e:
                self.fail(f"show_aizen_home() raised: {e}")


# ══════════════════════════════════════════════════════════
# J. MODEL SYSTEM
# ══════════════════════════════════════════════════════════

class TestModelSystem(unittest.TestCase):
    def test_model_catalog_is_list(self):
        import config
        self.assertIsInstance(config.model_catalog, list)

    def test_model_map_is_dict(self):
        import config
        self.assertIsInstance(config.model_map, dict)

    @patch("requests.get")
    def test_fetch_models_populates_catalog(self, mock_get):
        import config
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [
            {"id": "gpt-4"}, {"id": "claude-3"}, {"id": "gemini-pro"},
            {"id": "groq/openai/gpt-oss-120b", "owned_by": "groq"}
        ]}
        mock_get.return_value = mock_resp

        from api.omniroute import fetch_models
        fetch_models()
        self.assertGreaterEqual(len(config.raw_model_catalog), 4)
        self.assertIn("gpt-4", config.raw_model_map)
        # Verified free model appears in filtered catalog; unverified models are hidden
        self.assertEqual(len(config.model_catalog), 1)
        self.assertIn("groq/openai/gpt-oss-120b", config.model_map)
        self.assertNotIn("gpt-4", config.model_map)


# ══════════════════════════════════════════════════════════
# K. TOKEN USAGE STATE
# ══════════════════════════════════════════════════════════

class TestTokenUsage(unittest.TestCase):
    def test_last_usage_has_required_keys(self):
        import config
        required = {"prompt_tokens", "completion_tokens", "total_tokens", "actual_model", "response_time"}
        self.assertTrue(required.issubset(config.last_usage.keys()))

    def test_human_number_formatting(self):
        from core.token_manager import human_number
        self.assertEqual(human_number(0), "0")
        self.assertIn("k", human_number(4200).lower())
        self.assertIn("M", human_number(1_500_000))

    def test_get_context_status_returns_dict(self):
        from core.token_manager import get_context_status
        ctx = get_context_status()
        self.assertIsInstance(ctx, dict)
        self.assertIn("used", ctx)


# ══════════════════════════════════════════════════════════
# L. STREAMING STATE
# ══════════════════════════════════════════════════════════

class TestStreamingState(unittest.TestCase):
    def test_streaming_enabled_is_bool(self):
        import config
        self.assertIsInstance(config.streaming_enabled, bool)

    def test_streaming_command_toggles(self):
        import config
        from commands.handlers import handle_command
        original = config.streaming_enabled

        handle_command("/stream off")
        self.assertFalse(config.streaming_enabled)

        handle_command("/stream on")
        self.assertTrue(config.streaming_enabled)

        config.streaming_enabled = original


# ══════════════════════════════════════════════════════════
# M. PROVIDER HEALTH
# ══════════════════════════════════════════════════════════

class TestProviderHealth(unittest.TestCase):
    def test_get_summary_returns_dict(self):
        from core.provider_health import get_summary
        summary = get_summary()
        self.assertIsInstance(summary, dict)

    def test_status_constants_exist(self):
        from core.provider_health import STATUS_COLORS, STATUS_SYMBOLS
        self.assertIn("ONLINE", STATUS_COLORS)
        self.assertIn("OFFLINE", STATUS_COLORS)
        self.assertIn("ONLINE", STATUS_SYMBOLS)


# ══════════════════════════════════════════════════════════
# N. VOICE FALLBACK (NO HARDWARE)
# ══════════════════════════════════════════════════════════

class TestVoiceFallback(unittest.TestCase):
    def test_audio_check_no_crash(self):
        from core.audio_manager import check_audio_subsystem
        ok, msg = check_audio_subsystem()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)

    def test_tts_unavailable_no_crash(self):
        from core.text_to_speech import get_tts_status, speak_text
        status, detail = get_tts_status()
        self.assertIsInstance(status, str)
        # speak_text must never raise
        result = speak_text("test", non_blocking=False)
        self.assertIsInstance(result, bool)

    def test_handle_push_to_talk_no_audio_returns_none(self):
        import config
        config.voice_enabled = True
        config.voice_input_enabled = True
        with patch("core.voice_manager.check_audio_subsystem", return_value=(False, "no audio")):
            from core.voice_manager import handle_push_to_talk
            result = handle_push_to_talk()
            self.assertIsNone(result)
        config.voice_enabled = False


# ══════════════════════════════════════════════════════════
# O. TOOL REGISTRY
# ══════════════════════════════════════════════════════════

class TestToolRegistry(unittest.TestCase):
    def test_registry_has_tools(self):
        from core.tool_registry import registry
        tools = registry.list_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

    def test_tool_schema_has_required_fields(self):
        from core.tool_registry import registry
        for tool in registry.list_tools():
            self.assertTrue(hasattr(tool, "name"))
            self.assertTrue(hasattr(tool, "description"))
            self.assertTrue(len(tool.name) > 0)

    def test_tools_prompt_not_empty(self):
        from core.tool_registry import registry
        prompt = registry.get_tools_prompt()
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)


# ══════════════════════════════════════════════════════════
# P. COMMAND HANDLER DISPATCH
# ══════════════════════════════════════════════════════════

class TestCommandHandlers(unittest.TestCase):
    def test_unknown_command_no_crash(self):
        from commands.handlers import handle_command
        try:
            handle_command("/unknown_command_xyz")
        except Exception as e:
            self.fail(f"Unknown command raised: {e}")

    def test_stream_toggle(self):
        import config
        from commands.handlers import handle_command
        handle_command("/stream off")
        self.assertFalse(config.streaming_enabled)
        handle_command("/stream on")
        self.assertTrue(config.streaming_enabled)

    def test_voice_status_no_crash(self):
        from commands.handlers import handle_command
        try:
            handle_command("/voice status")
        except Exception as e:
            self.fail(f"/voice status raised: {e}")

    def test_rag_toggle(self):
        import config
        from commands.handlers import handle_command
        original = config.rag_enabled
        handle_command("/rag off")
        self.assertFalse(config.rag_enabled)
        handle_command("/rag on")
        self.assertTrue(config.rag_enabled)
        config.rag_enabled = original


# ══════════════════════════════════════════════════════════
# Q. TERMINAL SAFETY
# ══════════════════════════════════════════════════════════

class TestTerminalSafety(unittest.TestCase):
    def test_rm_rf_root_classified_blocked(self):
        from core.command_safety import classify, BLOCKED
        result = classify("rm -rf /")
        self.assertEqual(result.level, BLOCKED)

    def test_git_reset_hard_classified_dangerous(self):
        from core.command_safety import classify, DANGEROUS
        result = classify("git reset --hard HEAD~1")
        self.assertEqual(result.level, DANGEROUS)

    def test_sudo_classified_dangerous(self):
        from core.command_safety import classify, DANGEROUS
        result = classify("sudo systemctl restart nginx")
        self.assertEqual(result.level, DANGEROUS)

    def test_ls_classified_safe(self):
        from core.command_safety import classify, READ_ONLY
        result = classify("ls -la")
        self.assertEqual(result.level, READ_ONLY)

    def test_blocked_commands(self):
        from core.command_safety import classify, BLOCKED
        result = classify(":(){ :|:& };:")
        self.assertEqual(result.level, BLOCKED)


# ══════════════════════════════════════════════════════════
# R. FILE PATH SAFETY
# ══════════════════════════════════════════════════════════

class TestFilePathSafety(unittest.TestCase):
    def test_tool_executor_blocks_path_traversal(self):
        """file_write tool should reject ../../../etc/passwd paths."""
        from core.tool_executor import execute_tool
        result = execute_tool({
            "tool": "file_write",
            "args": {"path": "../../../etc/passwd", "content": "bad"}
        })
        self.assertFalse(result.get("success"))

    def test_tool_executor_blocks_absolute_system_paths(self):
        """file_write to /etc/passwd must fail."""
        from core.tool_executor import execute_tool
        result = execute_tool({
            "tool": "file_write",
            "args": {"path": "/etc/passwd", "content": "bad"}
        })
        self.assertFalse(result.get("success"))


# ══════════════════════════════════════════════════════════
# S. STARTUP SEQUENCE (MOCKED)
# ══════════════════════════════════════════════════════════

class TestStartupSequence(unittest.TestCase):
    @patch("api.omniroute.fetch_models", return_value=True)
    @patch("ui.console.show_aizen_home")
    def test_startup_no_crash(self, mock_home, mock_fetch):
        """_startup() should complete without error when mocked."""
        from app import _startup
        try:
            _startup()
        except Exception as e:
            self.fail(f"_startup() raised: {e}")


# ══════════════════════════════════════════════════════════
# T. REGRESSION: ALL MODULES IMPORTABLE
# ══════════════════════════════════════════════════════════

class TestAllModulesImportable(unittest.TestCase):
    def _try_import(self, module_name):
        try:
            __import__(module_name)
        except Exception as e:
            self.fail(f"Failed to import {module_name}: {e}")

    def test_import_config(self): self._try_import("config")
    def test_import_app(self): self._try_import("app")
    def test_import_myai(self): self._try_import("myai")
    def test_import_api_omniroute(self): self._try_import("api.omniroute")
    def test_import_core_storage(self): self._try_import("core.storage")
    def test_import_core_chat_manager(self): self._try_import("core.chat_manager")
    def test_import_core_model_manager(self): self._try_import("core.model_manager")
    def test_import_core_token_manager(self): self._try_import("core.token_manager")
    def test_import_core_provider_health(self): self._try_import("core.provider_health")
    def test_import_core_analytics(self): self._try_import("core.analytics")
    def test_import_core_router(self): self._try_import("core.router")
    def test_import_core_tool_registry(self): self._try_import("core.tool_registry")
    def test_import_core_tool_executor(self): self._try_import("core.tool_executor")
    def test_import_core_tool_parser(self): self._try_import("core.tool_parser")
    def test_import_core_command_safety(self): self._try_import("core.command_safety")
    def test_import_core_command_runner(self): self._try_import("core.command_runner")
    def test_import_core_audio_manager(self): self._try_import("core.audio_manager")
    def test_import_core_speech_to_text(self): self._try_import("core.speech_to_text")
    def test_import_core_text_to_speech(self): self._try_import("core.text_to_speech")
    def test_import_core_voice_manager(self): self._try_import("core.voice_manager")
    def test_import_core_kb_manager(self): self._try_import("core.kb_manager")
    def test_import_core_skill_loader(self): self._try_import("core.skill_loader")
    def test_import_commands_handlers(self): self._try_import("commands.handlers")
    def test_import_ui_console(self): self._try_import("ui.console")
    def test_import_ui_banner(self): self._try_import("ui.banner")
    def test_import_ui_prompts(self): self._try_import("ui.prompts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
