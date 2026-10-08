"""
core/speech_to_text.py — Speech-to-Text backend using faster-whisper.

Responsibilities:
  - Lazy-load Whisper model on first use (never during normal AIZEN startup).
  - Transcribe audio files (mono 16kHz WAV).
  - Support automatic language detection (Tamil, English, Tanglish, etc.).
  - Return transcript, detected language, and average confidence.
  - Graceful fallback and error reporting if dependencies or models are missing.
"""

import os
import time
from typing import Any, Optional, Tuple

import config
from ui.console import console

_stt_model_instance = None
_stt_model_name = "tiny"
_stt_status = "UNKNOWN"
_stt_status_detail = ""


def get_stt_status() -> Tuple[str, str]:
    """
    Return (status, detail) for speech-to-text backend.
    Status can be: 'READY', 'AVAILABLE', 'UNAVAILABLE', 'LOADING', 'ERROR'.
    """
    global _stt_status, _stt_status_detail, _stt_model_instance
    if _stt_model_instance is not None:
        return "READY", f"local-whisper ({_stt_model_name})"

    try:
        import faster_whisper
        return "AVAILABLE", f"faster-whisper ({_stt_model_name} on first use)"
    except ImportError:
        return "UNAVAILABLE", "faster-whisper package not installed"
    except Exception as e:
        return "ERROR", str(e)


def load_stt_model(model_name: Optional[str] = None) -> Any:
    """
    Lazy load faster-whisper WhisperModel instance.
    Uses CPU and int8 quantization for lightweight WSL compatibility.
    """
    global _stt_model_instance, _stt_model_name, _stt_status, _stt_status_detail

    if _stt_model_instance is not None:
        return _stt_model_instance

    if model_name:
        _stt_model_name = model_name
    elif hasattr(config, "voice_stt_model"):
        _stt_model_name = getattr(config, "voice_stt_model", "tiny")
    else:
        _stt_model_name = "tiny"

    try:
        from faster_whisper import WhisperModel
        _stt_status = "LOADING"
        # int8 compute type is fast and memory-efficient on modern CPUs
        console.print(f"[dim]Initializing speech recognition model ({_stt_model_name})...[/dim]")
        _stt_model_instance = WhisperModel(_stt_model_name, device="cpu", compute_type="int8")
        _stt_status = "READY"
        _stt_status_detail = f"local-whisper ({_stt_model_name})"
        return _stt_model_instance
    except ImportError:
        _stt_status = "UNAVAILABLE"
        _stt_status_detail = "faster-whisper package not installed"
        raise RuntimeError("Speech recognition dependency 'faster-whisper' is not installed.")
    except Exception as e:
        _stt_status = "ERROR"
        _stt_status_detail = str(e)
        raise RuntimeError(f"Failed to load speech recognition model: {e}")


def transcribe_audio(
    audio_path: str,
    language: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], float]:
    """
    Transcribe a local WAV file to text.

    Args:
        audio_path: Path to mono 16kHz WAV file.
        language: Language code ('en', 'ta', etc.) or 'auto' (None for auto-detection).

    Returns:
        (transcript: Optional[str], detected_language: Optional[str], confidence: float)
    """
    if not audio_path or not os.path.isfile(audio_path):
        return None, None, 0.0

    try:
        model = load_stt_model()
    except Exception as e:
        console.print(f"[red]Speech recognition error:[/red] {e}")
        return None, None, 0.0

    # Determine language argument
    lang_param = None
    if language and language.lower() not in ("auto", "none", ""):
        lang_param = language.lower()
    elif hasattr(config, "voice_language") and config.voice_language.lower() not in ("auto", "none", ""):
        lang_param = config.voice_language.lower()

    try:
        # Transcribe with faster-whisper
        # beam_size=1 or 2 is fast and lightweight
        segments, info = model.transcribe(
            audio_path,
            language=lang_param,
            beam_size=2,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        detected_lang = getattr(info, "language", lang_param or "unknown")
        lang_prob = getattr(info, "language_probability", 1.0)

        segment_texts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                segment_texts.append(text)

        full_transcript = " ".join(segment_texts).strip()
        if not full_transcript:
            return None, detected_lang, float(lang_prob)

        return full_transcript, detected_lang, float(lang_prob)

    except Exception as e:
        console.print(f"[red]Transcription failed:[/red] {e}")
        return None, None, 0.0
