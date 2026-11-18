"""
api/ollama.py — Native Ollama API client for AIZEN local models.

Model IDs exposed to AIZEN are namespaced as ``ollama:<model-name>`` so
they can never be confused with OmniRoute/cloud model IDs.
"""

import json
import time

import requests

import config


def _model_name(model_id: str) -> str:
    value = str(model_id or "").strip()
    if value.startswith("ollama:"):
        value = value.split(":", 1)[1]
    if not value:
        raise ValueError("No Ollama model selected.")
    return value


def _context_length(show_data: dict) -> int:
    info = show_data.get("model_info") or {}
    values = [
        value for key, value in info.items()
        if str(key).endswith(".context_length") and isinstance(value, (int, float))
    ]
    if values:
        return int(max(values))
    return int(getattr(config, "OLLAMA_DEFAULT_CONTEXT", 8192))


def fetch_models(show_message: bool = False) -> list:
    """Fetch installed Ollama models and store them separately from cloud models."""
    base = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    timeout = float(getattr(config, "OLLAMA_TIMEOUT", 8))
    try:
        response = requests.get(f"{base}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        models = []
        model_map = {}
        for item in payload.get("models", []):
            name = item.get("name") or item.get("model")
            if not name:
                continue
            model_id = f"ollama:{name}"
            context_length = int(getattr(config, "OLLAMA_DEFAULT_CONTEXT", 8192))
            try:
                show = requests.post(
                    f"{base}/api/show",
                    json={"name": name},
                    timeout=timeout,
                )
                if show.ok:
                    context_length = _context_length(show.json())
            except (requests.RequestException, ValueError, TypeError):
                pass
            # AIZEN's configured num_ctx is the actual request limit. Do not
            # advertise a larger native context window than we send to Ollama.
            context_length = min(
                context_length,
                int(getattr(config, "OLLAMA_NUM_CTX", 8192)),
            )
            meta = {
                "id": model_id,
                "name": name,
                "owned_by": "Ollama (Local)",
                "provider": "ollama",
                "source": "ollama",
                "policy_status": "LOCAL",
                "context_length": context_length,
                "max_input_tokens": context_length,
                "max_output_tokens": 2048,
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
                "capabilities": {},
            }
            models.append(meta)
            model_map[model_id] = meta
        models.sort(key=lambda m: m["id"].lower())
        config.local_model_catalog = models
        config.local_model_map = model_map
        if show_message:
            from ui.console import console
            console.print(f"[green]✓ Found {len(models)} installed Ollama model(s).[/green]")
        return models
    except (requests.RequestException, ValueError, TypeError) as exc:
        config.local_model_catalog = []
        config.local_model_map = {}
        if show_message:
            from ui.console import console
            console.print(f"[yellow]Ollama is unavailable: {exc}[/yellow]")
        return []


def check_connection() -> bool:
    base = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        response = requests.get(
            f"{base}/api/tags",
            timeout=float(getattr(config, "OLLAMA_TIMEOUT", 8)),
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def _payload_messages(messages):
    """Ollama accepts the OpenAI-style role/content message shape."""
    return [
        {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
        for m in messages
        if isinstance(m, dict) and m.get("role") in {"system", "user", "assistant"}
    ]


def send_chat(messages, model):
    """Non-streaming local completion; returns AIZEN's normalized result shape."""
    base = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model_name = _model_name(model)
    started = time.time()
    response = requests.post(
        f"{base}/api/chat",
        json={
            "model": model_name,
            "messages": _payload_messages(messages),
            "stream": False,
            "options": {
                "num_ctx": int(getattr(config, "OLLAMA_NUM_CTX", 8192)),
                "num_predict": 2048,
            },
        },
        timeout=float(getattr(config, "OLLAMA_REQUEST_TIMEOUT", 300)),
    )
    if not response.ok:
        raise RuntimeError(f"Ollama API error ({response.status_code}): {response.text[:1000]}")
    data = response.json()
    message = data.get("message") or {}
    prompt_tokens = data.get("prompt_eval_count")
    completion_tokens = data.get("eval_count")
    prompt_tokens = int(prompt_tokens) if prompt_tokens is not None else None
    completion_tokens = int(completion_tokens) if completion_tokens is not None else None
    total_tokens = (
        prompt_tokens + completion_tokens
        if prompt_tokens is not None and completion_tokens is not None
        else None
    )
    return {
        "answer": message.get("content") or "",
        "actual_model": f"ollama:{data.get('model', model_name)}",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "response_time": time.time() - started,
    }


def stream_chat(messages, model):
    """Stream native Ollama NDJSON chunks using AIZEN's content/done event contract."""
    base = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model_name = _model_name(model)
    started = time.time()
    payload = {
        "model": model_name,
        "messages": _payload_messages(messages),
        "stream": True,
        "options": {
            "num_ctx": int(getattr(config, "OLLAMA_NUM_CTX", 8192)),
            "num_predict": 2048,
        },
    }
    with requests.post(
        f"{base}/api/chat",
        json=payload,
        stream=True,
        timeout=float(getattr(config, "OLLAMA_REQUEST_TIMEOUT", 300)),
    ) as response:
        if not response.ok:
            raise RuntimeError(f"Ollama API error ({response.status_code}): {response.text[:1000]}")
        final = {}
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8", errors="replace")
            try:
                chunk = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            message = chunk.get("message") or {}
            content = message.get("content")
            if content:
                yield ("content", content)
            if chunk.get("done"):
                final = chunk
        prompt_tokens = final.get("prompt_eval_count")
        completion_tokens = final.get("eval_count")
        prompt_tokens = int(prompt_tokens) if prompt_tokens is not None else None
        completion_tokens = int(completion_tokens) if completion_tokens is not None else None
        total_tokens = (
            prompt_tokens + completion_tokens
            if prompt_tokens is not None and completion_tokens is not None
            else None
        )
        yield ("done", {
            "actual_model": f"ollama:{final.get('model', model_name)}",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "response_time": time.time() - started,
        })
