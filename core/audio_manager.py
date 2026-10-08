"""
core/audio_manager.py — Microphone/audio device capture and temporary audio file management.

Responsibilities:
  - Enumerate and inspect available audio input and output devices.
  - Safe recording of mono 16kHz audio for Whisper compatibility.
  - Silence detection and push-to-talk bounded capture.
  - Graceful degradation if PortAudio/sounddevice or microphone is missing (especially in WSL).
  - Manage ~/.myai/tmp/ temporary WAV files (creation, deletion, startup sweep).
"""

import os
import glob
import time
import uuid
import wave
from typing import Any, Dict, List, Optional, Tuple

import config
from ui.console import console

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_MAX_RECORD_SECONDS = 30.0
DEFAULT_SILENCE_THRESHOLD = 500       # RMS energy threshold for 16-bit PCM
DEFAULT_SILENCE_DURATION = 1.8        # Seconds of silence to trigger auto-stop


def get_temp_audio_dir() -> str:
    """Return ~/.myai/tmp/ directory, ensuring it exists."""
    os.makedirs(config.VOICE_TMP_DIR, exist_ok=True)
    return config.VOICE_TMP_DIR


def generate_temp_audio_path(prefix: str = "voice_") -> str:
    """Generate a unique temporary .wav file path in ~/.myai/tmp/."""
    d = get_temp_audio_dir()
    unique_id = uuid.uuid4().hex[:12]
    return os.path.join(d, f"{prefix}{unique_id}.wav")


def delete_temp_audio_file(file_path: Optional[str]) -> bool:
    """Safely delete a temporary audio file."""
    if not file_path:
        return False
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
            return True
    except Exception:
        pass
    return False


def clean_stale_temp_audio_files(max_age_seconds: float = 3600.0) -> int:
    """Sweep and remove stale voice temporary files in ~/.myai/tmp/ on startup."""
    count = 0
    d = get_temp_audio_dir()
    try:
        patterns = [os.path.join(d, "voice_*.wav"), os.path.join(d, "tts_*.wav")]
        now = time.time()
        for pat in patterns:
            for fpath in glob.glob(pat):
                try:
                    if os.path.isfile(fpath):
                        mtime = os.path.getmtime(fpath)
                        if (now - mtime) > max_age_seconds:
                            os.remove(fpath)
                            count += 1
                except Exception:
                    pass
    except Exception:
        pass
    return count


# ------------------------------------------------------------------
# DEVICE DISCOVERY & STATUS
# ------------------------------------------------------------------

def check_audio_subsystem() -> Tuple[bool, str]:
    """
    Check if the local audio recording subsystem (sounddevice / PortAudio) is functional.
    Returns (is_available: bool, status_message: str).
    """
    try:
        import sounddevice as sd
        # Query default device or devices list
        devices = sd.query_devices()
        if not devices:
            return False, "No audio devices detected."
        return True, "Audio subsystem operational."
    except OSError as e:
        err_str = str(e)
        if "PortAudio" in err_str:
            return False, "PortAudio library not found. Install 'libportaudio2' via apt to enable microphone input in WSL."
        return False, f"Audio driver error: {err_str}"
    except ImportError:
        return False, "sounddevice package not installed."
    except Exception as e:
        return False, f"Audio subsystem unavailable: {str(e)}"


def list_audio_devices() -> List[Dict[str, Any]]:
    """
    List input and output audio devices with clean human-readable details.
    """
    devices_info = []
    try:
        import sounddevice as sd
        raw_devices = sd.query_devices()
        default_in, default_out = sd.default.device

        for idx, dev in enumerate(raw_devices):
            max_in = dev.get("max_input_channels", 0)
            max_out = dev.get("max_output_channels", 0)
            dev_name = dev.get("name", f"Device {idx}")

            if max_in > 0:
                devices_info.append({
                    "id": idx,
                    "name": dev_name,
                    "type": "Input",
                    "channels": max_in,
                    "default": (idx == default_in),
                    "sample_rate": int(dev.get("default_samplerate", DEFAULT_SAMPLE_RATE)),
                })
            if max_out > 0:
                devices_info.append({
                    "id": idx,
                    "name": dev_name,
                    "type": "Output",
                    "channels": max_out,
                    "default": (idx == default_out),
                    "sample_rate": int(dev.get("default_samplerate", DEFAULT_SAMPLE_RATE)),
                })
    except Exception:
        pass

    return devices_info


def get_default_input_device_name() -> str:
    """Return the name of the active/default input device or 'Default'."""
    if getattr(config, "voice_input_device", None) is not None:
        return str(config.voice_input_device)
    available, msg = check_audio_subsystem()
    if not available:
        return "Unavailable"
    try:
        import sounddevice as sd
        def_in = sd.default.device[0]
        if def_in >= 0:
            dev = sd.query_devices(def_in)
            return dev.get("name", "Default Microphone")
    except Exception:
        pass
    return "Default"


def get_default_output_device_name() -> str:
    """Return the name of the active/default output device or 'Default'."""
    if getattr(config, "voice_output_device", None) is not None:
        return str(config.voice_output_device)
    available, _ = check_audio_subsystem()
    if not available:
        return "System Default"
    try:
        import sounddevice as sd
        def_out = sd.default.device[1]
        if def_out >= 0:
            dev = sd.query_devices(def_out)
            return dev.get("name", "Default Speaker")
    except Exception:
        pass
    return "Default"


# ------------------------------------------------------------------
# AUDIO RECORDING (PUSH-TO-TALK)
# ------------------------------------------------------------------

def record_audio(
    max_duration: float = DEFAULT_MAX_RECORD_SECONDS,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    silence_threshold: int = DEFAULT_SILENCE_THRESHOLD,
    silence_duration: float = DEFAULT_SILENCE_DURATION,
    device: Optional[Any] = None,
    on_start: Optional[Any] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Record mono 16-bit PCM audio from the microphone into a temporary .wav file.

    Features:
      - Automatically stops after `silence_duration` seconds of continuous silence
        (once some voice audio has been captured).
      - Maximum recording cap of `max_duration` seconds.
      - Graceful handling of Ctrl+C / user interrupt.
      - Safe cleanup on error or cancellation.

    Returns:
      (audio_file_path: Optional[str], error_or_cancel_message: Optional[str])
    """
    available, error_msg = check_audio_subsystem()
    if not available:
        return None, error_msg

    try:
        import sounddevice as sd
        import numpy as np
    except Exception as e:
        return None, f"Audio library import failed: {e}"

    target_wav_path = generate_temp_audio_path("voice_rec_")
    audio_frames: List[np.ndarray] = []
    has_spoken = False
    silence_start_time: Optional[float] = None
    start_time = time.time()

    def _audio_callback(indata, frames, time_info, status):
        nonlocal has_spoken, silence_start_time
        if status:
            pass
        # Copy audio block
        audio_block = indata.copy()
        audio_frames.append(audio_block)

        # Calculate RMS energy for silence detection
        # indata is float32 in [-1.0, 1.0] or int16
        rms = np.sqrt(np.mean(np.square(audio_block)))
        # Convert float32 RMS to 16-bit PCM equivalent
        rms_16 = rms * 32767.0

        now = time.time()
        if rms_16 > silence_threshold:
            has_spoken = True
            silence_start_time = None
        else:
            if has_spoken and silence_start_time is None:
                silence_start_time = now

    config.voice_is_listening = True
    if on_start and callable(on_start):
        try:
            on_start()
        except Exception:
            pass

    target_device = device if device is not None else getattr(config, "voice_input_device", None)

    stream = None
    try:
        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=target_device,
            callback=_audio_callback,
        )
        with stream:
            while True:
                elapsed = time.time() - start_time
                if elapsed >= max_duration:
                    break
                if has_spoken and silence_start_time is not None:
                    if (time.time() - silence_start_time) >= silence_duration:
                        break
                time.sleep(0.05)

    except KeyboardInterrupt:
        config.voice_is_listening = False
        delete_temp_audio_file(target_wav_path)
        return None, "Voice input cancelled."
    except Exception as e:
        config.voice_is_listening = False
        delete_temp_audio_file(target_wav_path)
        return None, f"Microphone recording error: {e}"
    finally:
        config.voice_is_listening = False
        if stream:
            try:
                stream.close()
            except Exception:
                pass

    if not audio_frames or not has_spoken:
        delete_temp_audio_file(target_wav_path)
        return None, "No speech detected (silence)."

    # Concatenate and write WAV file
    try:
        full_audio = np.concatenate(audio_frames, axis=0)
        # Convert float32 in [-1.0, 1.0] to int16
        int16_audio = (np.clip(full_audio, -1.0, 1.0) * 32767.0).astype(np.int16)

        with wave.open(target_wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(int16_audio.tobytes())

        return target_wav_path, None

    except Exception as e:
        delete_temp_audio_file(target_wav_path)
        return None, f"Error saving audio WAV: {e}"
