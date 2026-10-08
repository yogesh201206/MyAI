"""
core/voice_manager.py — Voice subsystem coordinator, state management, and UI rendering.

Responsibilities:
  - Public voice state and configuration management.
  - Render /voice status Rich panel.
  - Render /voice devices and /voice voices tables.
  - Push-to-talk orchestration (capture -> transcribe -> clean audio -> return text).
  - Voice output coordination (read AI response aloud if voice_output_enabled is True).
  - Safe error handling without crashing normal text AIZEN session.
"""

import os
from typing import Any, Dict, List, Optional, Tuple
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import config
from core.audio_manager import (
    check_audio_subsystem,
    clean_stale_temp_audio_files,
    delete_temp_audio_file,
    get_default_input_device_name,
    get_default_output_device_name,
    list_audio_devices,
    record_audio,
)
from core.speech_to_text import get_stt_status, transcribe_audio
from core.storage import save_config
from core.text_to_speech import (
    clean_text_for_speech,
    get_tts_status,
    list_voices,
    speak_text,
    stop_speech,
)
from ui.console import console


# ------------------------------------------------------------------
# CONFIG & STATE TOGGLES
# ------------------------------------------------------------------

def set_voice_mode(enabled: bool) -> None:
    """Turn overall voice mode ON or OFF and persist."""
    config.voice_enabled = enabled
    save_config()
    status_str = "[bold green]ON[/bold green]" if enabled else "[bold red]OFF[/bold red]"
    console.print(f"[bold cyan]AIZEN[/bold cyan] Voice Mode is now {status_str}.")


def set_voice_input(enabled: bool) -> None:
    """Turn voice input (microphone) ON or OFF and persist."""
    config.voice_input_enabled = enabled
    save_config()
    status_str = "[bold green]ON[/bold green]" if enabled else "[bold red]OFF[/bold red]"
    console.print(f"[bold cyan]AIZEN[/bold cyan] Voice Input is now {status_str}.")


def set_voice_output(enabled: bool) -> None:
    """Turn voice output (text-to-speech) ON or OFF and persist."""
    config.voice_output_enabled = enabled
    save_config()
    status_str = "[bold green]ON[/bold green]" if enabled else "[bold red]OFF[/bold red]"
    console.print(f"[bold cyan]AIZEN[/bold cyan] Voice Output is now {status_str}.")


def set_voice_speed(speed: float) -> None:
    """Set TTS speech playback speed factor (e.g. 0.8 to 2.0)."""
    if speed < 0.5 or speed > 3.0:
        console.print("[red]Voice speed must be between 0.5 and 3.0.[/red]")
        return
    config.voice_speed = round(float(speed), 2)
    save_config()
    console.print(f"[bold cyan]AIZEN[/bold cyan] Voice Speed set to [bold]{config.voice_speed}x[/bold].")


def set_voice_language(lang_code: str) -> None:
    """Set speech recognition language code (e.g. 'auto', 'en', 'ta')."""
    clean_lang = lang_code.strip().lower()
    config.voice_language = clean_lang
    save_config()
    console.print(f"[bold cyan]AIZEN[/bold cyan] Voice Language set to [bold]{config.voice_language}[/bold].")


# ------------------------------------------------------------------
# STATUS & INSPECTION PANELS
# ------------------------------------------------------------------

def show_voice_status() -> None:
    """Display the /voice status Rich panel."""
    # Subsystem statuses
    stt_status, stt_detail = get_stt_status()
    tts_status, tts_detail = get_tts_status()
    audio_ok, audio_detail = check_audio_subsystem()

    # Formatted values
    v_mode = "[bold green]ON[/bold green]" if config.voice_enabled else "[bold red]OFF[/bold red]"
    v_input = "[bold green]ON[/bold green]" if config.voice_input_enabled else "[bold red]OFF[/bold red]"
    v_output = "[bold green]ON[/bold green]" if config.voice_output_enabled else "[bold red]OFF[/bold red]"

    mic_name = get_default_input_device_name()
    if not audio_ok:
        mic_name = f"[dim red]Unavailable ({audio_detail})[/dim red]"

    spk_name = get_default_output_device_name()
    if tts_status not in ("READY", "AVAILABLE"):
        tts_display = f"[dim red]{tts_detail}[/dim red]"
    else:
        tts_display = f"[cyan]{config.voice_tts_backend}[/cyan]"

    stt_display = f"[cyan]{stt_detail}[/cyan]" if stt_status in ("READY", "AVAILABLE") else f"[dim red]{stt_detail}[/dim red]"

    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="bold white", justify="left")
    grid.add_column(justify="left")

    grid.add_row("Voice Mode", v_mode)
    grid.add_row("Voice Input", v_input)
    grid.add_row("Voice Output", v_output)
    grid.add_row("STT Backend", stt_display)
    grid.add_row("TTS Backend", tts_display)
    grid.add_row("Microphone", mic_name)
    grid.add_row("Output Device", spk_name)
    grid.add_row("Language", str(config.voice_language))
    grid.add_row("Speech Speed", f"{config.voice_speed:.1f}x")

    panel = Panel(
        grid,
        title="[bold cyan]🎙  AIZEN Voice Subsystem Status[/bold cyan]",
        subtitle="[dim]Push-to-Talk: Alt+V | Commands: /voice help[/dim]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def show_voice_devices() -> None:
    """Display available input and output audio devices."""
    devices = list_audio_devices()
    if not devices:
        audio_ok, msg = check_audio_subsystem()
        console.print(f"[dim yellow]No audio devices found. {msg}[/dim yellow]")
        return

    table = Table(title="Audio Devices", border_style="cyan")
    table.add_column("#", justify="right", style="bold cyan")
    table.add_column("Type", justify="center", style="magenta")
    table.add_column("Device Name", justify="left")
    table.add_column("Channels", justify="center", style="dim")
    table.add_column("Default", justify="center", style="green")

    for dev in devices:
        is_default = "✓" if dev.get("default") else ""
        table.add_row(
            str(dev.get("id")),
            str(dev.get("type")),
            str(dev.get("name")),
            str(dev.get("channels")),
            is_default,
        )

    console.print(table)


def show_voice_voices() -> None:
    """Display available TTS voices."""
    voices = list_voices()
    if not voices:
        status, detail = get_tts_status()
        console.print(f"[dim yellow]No TTS voices found. Backend status: {detail}[/dim yellow]")
        return

    table = Table(title="Available TTS Voices", border_style="cyan")
    table.add_column("#", justify="right", style="bold cyan")
    table.add_column("Voice ID / Name", justify="left")
    table.add_column("Languages", justify="left", style="dim")
    table.add_column("Gender", justify="center", style="magenta")

    for idx, v in enumerate(voices, 1):
        langs = ", ".join(v.get("languages", [])) if v.get("languages") else "Default"
        table.add_row(
            str(idx),
            f"{v.get('name')} ({v.get('id')})",
            langs,
            str(v.get("gender")),
        )

    console.print(table)


# ------------------------------------------------------------------
# PUSH-TO-TALK ORCHESTRATION
# ------------------------------------------------------------------

def handle_push_to_talk() -> Optional[str]:
    """
    Execute push-to-talk voice capture and transcription:
      1. Check voice input is enabled.
      2. Record mono audio via microphone with listening indicator.
      3. Transcribe audio with Whisper.
      4. Clean up temporary audio file.
      5. Print recognized text and return it for normal pipeline dispatch.

    Returns:
      Transcribed prompt string, or None if cancelled/silent/unavailable.
    """
    # Auto-enable voice mode if user triggers Alt+V directly
    if not config.voice_enabled:
        config.voice_enabled = True

    if not config.voice_input_enabled:
        console.print("[dim yellow]Voice input is disabled. Enable with /voice input on[/dim yellow]")
        return None

    # Check audio subsystem
    available, err_msg = check_audio_subsystem()
    if not available:
        console.print(f"[dim red]Microphone unavailable in current environment: {err_msg}[/dim red]")
        return None

    console.print("[bold cyan]🎙 Listening...[/bold cyan] [dim](speak into microphone, stops on silence or Ctrl+C)[/dim]")

    # Record audio
    audio_path, err = record_audio()
    if err:
        if "cancelled" in err.lower():
            console.print("[dim yellow]Voice input cancelled.[/dim yellow]")
        else:
            console.print(f"[dim yellow]{err}[/dim yellow]")
        return None

    if not audio_path or not os.path.isfile(audio_path):
        console.print("[dim yellow]No audio recorded.[/dim yellow]")
        return None

    console.print("[dim cyan]Processing speech...[/dim cyan]")

    try:
        transcript, lang, conf = transcribe_audio(audio_path, language=config.voice_language)
    finally:
        # Guarantee immediate deletion of temporary audio file
        delete_temp_audio_file(audio_path)

    if not transcript or not transcript.strip():
        console.print("[dim yellow]No speech recognized.[/dim yellow]")
        return None

    transcript_clean = transcript.strip()
    lang_info = f" [dim]({lang})[/dim]" if lang else ""
    console.print(f"[bold green]Recognized{lang_info}:[/bold green]\n\"{transcript_clean}\"\n")

    return transcript_clean


# ------------------------------------------------------------------
# RESPONSE SPEECH COORDINATOR
# ------------------------------------------------------------------

def speak_response_if_enabled(response_text: str) -> None:
    """
    Speak completed AI response aloud if voice mode and output are enabled.
    Text output has already appeared on terminal — speech is supplementary.
    """
    if not (getattr(config, "voice_enabled", False) and getattr(config, "voice_output_enabled", False)):
        return

    if not response_text or not response_text.strip():
        return

    # Start non-blocking TTS
    started = speak_text(response_text, non_blocking=True)
    if started:
        console.print("[dim]🔊 Speaking response... (type /voice stop to silence)[/dim]")
