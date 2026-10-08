# AIZEN AI — Troubleshooting & Diagnostics Guide

This document lists common issues, diagnostic steps, and resolutions when running **AIZEN AI**.

---

## 1. Quick Diagnostic: Running `myai --doctor`

Whenever something isn't working as expected, the first step is to run:

```bash
myai --doctor
```

Or within the AIZEN terminal:
```text
/doctor
```

This verifies Python runtime version, virtual environment paths, OmniRoute server status, writable data directories, and voice libraries.

---

## 2. OmniRoute Server Issues

### Symptom: `OmniRoute: ○ Offline` in banner or `Connection refused`

**Causes:**
1. OmniRoute server is not started on port 20128.
2. A firewall is blocking loopback traffic on port 20128.

**Resolutions:**
- Check if OmniRoute process is alive:
  ```bash
  ss -ltn | grep 20128
  ```
- Start OmniRoute manually using nvm/node:
  ```bash
  omniroute serve
  ```
- Or run AIZEN through the auto-starting launcher:
  ```bash
  ./start-myai.sh
  ```
  The launcher detects when OmniRoute is offline, starts it in the background, waits for the socket to accept connections, and tails `~/.myai/omniroute.log` if it fails.

---

## 3. Storage & Configuration Recovery

### Symptom: Warning: `config.json was corrupted — recovered from backup`

**Cause:**
An abnormal process termination or system reboot occurred while writing.

**Behavior:**
AIZEN uses atomic writes (`.tmp` + rename). If a corrupt `config.json` is detected on load, AIZEN automatically falls back to `config.json.bak` and restores your configuration without crashing.

**Manual Reset:**
If you ever want to reset AIZEN settings to factory defaults:
```bash
rm ~/.myai/config.json ~/.myai/config.json.bak
# Restart AIZEN AI — defaults will be freshly generated.
```

---

## 4. Voice Mode & Audio Issues

### Symptom: `TTS unavailable: eSpeak library missing in WSL`

**Cause:**
`pyttsx3` on Linux/WSL relies on the `espeak-ng` or `espeak` C library.

**Resolution:**
Install eSpeak using your system package manager:
```bash
# Ubuntu / Debian / WSL
sudo apt update && sudo apt install -y espeak libespeak1
```

### Symptom: `Microphone unavailable in current environment: no audio`

**Cause:**
No audio capture device is detected (common in headless Linux servers or standard WSL2 instances without PulseAudio forwarding).

**Resolution:**
- On WSL2: Configure WSLg audio or PulseAudio forwarding.
- On Linux Desktop: Verify `arecord -l` lists an ALSA capture device.
- Push-to-talk can be tested with `/voice ptt`. If no hardware exists, text chat remains 100% operational.

---

## 5. RAG & FAISS Issues

### Symptom: `faiss-cpu` or `sentence-transformers` import error

**Resolution:**
Ensure all dependencies are installed in your active virtual environment:
```bash
.venv/bin/pip install faiss-cpu sentence-transformers pypdf
```

### Symptom: Vector index search is slow or memory intensive

**Resolution:**
- By default, AIZEN uses `all-MiniLM-L6-v2`, which is optimized for CPU inference and requires ~80MB RAM.
- Clear old indexed vectors:
  ```text
  /rag clear
  ```

---

## 6. Debug Mode

To inspect complete Python tracebacks for unhandled exceptions:

```bash
# From command line:
myai --debug

# Or from within AIZEN:
/debug on
```
