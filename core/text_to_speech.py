"""
core/text_to_speech.py — Text-to-Speech synthesis backend and text sanitizer.

Responsibilities:
  - Sanitize Markdown and terminal formatting into natural spoken English/multilingual text.
  - Exclude large code blocks ("The code is displayed in the terminal.").
  - Cap speech output length at voice_max_speech_chars (default 3000).
  - Provide speech output via local pyttsx3 or safe fallback.
  - Asynchronous / non-blocking speech playback.
  - Safe speech interruption / cancellation via stop_speech().
  - Graceful degradation if eSpeak / audio output is unavailable in WSL.
"""

import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import config
from ui.console import console

_tts_engine = None
_tts_lock = threading.Lock()
_tts_thread = None
_stop_requested = threading.Event()
_tts_status = "UNKNOWN"
_tts_status_detail = ""


def clean_text_for_speech(
    text: str,
    max_chars: Optional[int] = None,
) -> Tuple[str, bool]:
    """
    Convert raw AIZEN response text (including Markdown, code blocks, tables)
    into clean, natural spoken speech.

    Rules:
      - Replace code fences (```...```) with "The code is displayed in the terminal."
      - Remove inline backticks `code`.
      - Strip Markdown headers, emphasis, blockquotes, bullets, and links.
      - Simplify tables and URLs.
      - Cap output length at max_chars (default config.voice_max_speech_chars = 3000).
      - Returns (clean_speech_text: str, was_truncated: bool).
    """
    if not text:
        return "", False

    if max_chars is None:
        max_chars = getattr(config, "voice_max_speech_chars", 3000)

    cleaned = text

    # 1. Replace multi-line code blocks with placeholder
    # E.g. ```python ... ```
    code_block_pattern = re.compile(r"```[a-zA-Z0-9_\-\+]*\n[\s\S]*?```", re.MULTILINE)
    cleaned = code_block_pattern.sub(" The code is displayed in the terminal. ", cleaned)

    # 2. Replace any leftover inline code blocks or stray ```
    cleaned = re.sub(r"```[\s\S]*?```", " The code is displayed in the terminal. ", cleaned)

    # 3. Strip inline backticks `foo` -> foo
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)

    # 4. Strip markdown image tags ![alt](url)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", r"\1", cleaned)

    # 5. Convert markdown links [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

    # 6. Simplify plain URLs -> "link"
    cleaned = re.sub(r"https?://\S+", "link", cleaned)

    # 7. Strip Markdown headings (# Heading -> Heading)
    cleaned = re.sub(r"^\s*#{1,6}\s+", "", cleaned, flags=re.MULTILINE)

    # 8. Strip bold/italic formatting (**word**, *word*, __word__, _word_)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    cleaned = re.sub(r"~~([^~]+)~~", r"\1", cleaned)

    # 9. Strip blockquotes (> Quote -> Quote)
    cleaned = re.sub(r"^\s*>\s*", "", cleaned, flags=re.MULTILINE)

    # 10. Strip bullet characters (-, *, +) at line start
    cleaned = re.sub(r"^\s*[\*\-\+]\s+", "", cleaned, flags=re.MULTILINE)

    # 11. Simplify markdown table borders and divider lines
    cleaned = re.sub(r"\|", " ", cleaned)
    cleaned = re.sub(r"^\s*[-:\s|]{3,}\s*$", "", cleaned, flags=re.MULTILINE)

    # 12. Strip XML/HTML tags (like <tool_call> etc.)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)

    # 13. Collapse multiple whitespace and newlines into natural spacing
    cleaned = re.sub(r"\n+", ". ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 14. Check truncation against max_chars
    was_truncated = False
    if len(cleaned) > max_chars:
        # Find last sentence or word boundary before max_chars
        cutoff = cleaned[:max_chars].rfind(". ")
        if cutoff > (max_chars // 2):
            cleaned = cleaned[:cutoff + 1]
        else:
            word_cutoff = cleaned[:max_chars].rfind(" ")
            cleaned = cleaned[:word_cutoff] + "..." if word_cutoff > 0 else cleaned[:max_chars] + "..."
        was_truncated = True

    return cleaned.strip(), was_truncated


def get_tts_status() -> Tuple[str, str]:
    """
    Check availability of the TTS backend.
    Returns (status, detail).
    """
    global _tts_status, _tts_status_detail, _tts_engine

    if _tts_engine is not None:
        return "READY", "pyttsx3"

    try:
        import pyttsx3
        # Attempt a dry initialization check
        eng = pyttsx3.init()
        # If init succeeded without throwing, pyttsx3 is ready
        _tts_engine = eng
        # Configure default rate/volume
        speed = getattr(config, "voice_speed", 1.0)
        default_rate = eng.getProperty("rate")
        if default_rate:
            eng.setProperty("rate", int(default_rate * speed))
        return "READY", "pyttsx3"
    except RuntimeError as e:
        err_msg = str(e)
        if "eSpeak" in err_msg or "espeak" in err_msg:
            return "UNAVAILABLE", "eSpeak library missing in WSL (install 'espeak' via apt)"
        return "ERROR", err_msg
    except ImportError:
        return "UNAVAILABLE", "pyttsx3 package not installed"
    except Exception as e:
        return "ERROR", f"TTS initialization error: {e}"


def get_tts_engine() -> Any:
    """Lazy initialize and return the pyttsx3 engine."""
    global _tts_engine
    if _tts_engine is not None:
        return _tts_engine

    try:
        import pyttsx3
        eng = pyttsx3.init()
        speed = getattr(config, "voice_speed", 1.0)
        rate = eng.getProperty("rate")
        if rate:
            eng.setProperty("rate", int(rate * speed))
        _tts_engine = eng
        return _tts_engine
    except Exception as e:
        raise RuntimeError(f"TTS engine unavailable: {e}")


def list_voices() -> List[Dict[str, Any]]:
    """Enumerate voices available in the TTS engine."""
    voice_list = []
    try:
        eng = get_tts_engine()
        voices = eng.getProperty("voices")
        if voices:
            for v in voices:
                voice_list.append({
                    "id": getattr(v, "id", "unknown"),
                    "name": getattr(v, "name", "unknown"),
                    "languages": getattr(v, "languages", []),
                    "gender": getattr(v, "gender", "unknown"),
                })
    except Exception:
        pass
    return voice_list


def stop_speech() -> None:
    """Stop any currently playing speech."""
    global _stop_requested, _tts_engine
    _stop_requested.set()
    config.voice_is_speaking = False
    try:
        if _tts_engine is not None:
            _tts_engine.stop()
    except Exception:
        pass


def speak_text(
    text: str,
    non_blocking: bool = True,
    on_done: Optional[Callable[[], None]] = None,
) -> bool:
    """
    Sanitize and speak the given text using local TTS.

    Args:
        text: Text to speak (will be automatically sanitized).
        non_blocking: If True, plays in background thread.
        on_done: Optional callback upon speech completion.

    Returns:
        bool: True if speech playback was successfully started/queued, False otherwise.
    """
    clean_speech, was_truncated = clean_text_for_speech(text)
    if not clean_speech:
        return False

    status, detail = get_tts_status()
    if status not in ("READY", "AVAILABLE"):
        console.print(f"[dim yellow]TTS unavailable: {detail}[/dim yellow]")
        return False

    if was_truncated:
        console.print("[dim]Voice output truncated; full answer is available in terminal.[/dim]")

    def _worker():
        global _stop_requested
        _stop_requested.clear()
        config.voice_is_speaking = True
        try:
            with _tts_lock:
                eng = get_tts_engine()
                # Apply speed setting
                speed = getattr(config, "voice_speed", 1.0)
                try:
                    eng.setProperty("rate", int(200 * speed))
                except Exception:
                    pass

                # If speech stop was signaled before start
                if _stop_requested.is_set():
                    return

                eng.say(clean_speech)
                eng.runAndWait()
        except Exception as e:
            # Voice output failure must never crash AIZEN
            pass
        finally:
            config.voice_is_speaking = False
            if on_done and callable(on_done):
                try:
                    on_done()
                except Exception:
                    pass

    if non_blocking:
        global _tts_thread
        _tts_thread = threading.Thread(target=_worker, daemon=True, name="AIZEN-TTS")
        _tts_thread.start()
        return True
    else:
        _worker()
        return True
