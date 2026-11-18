"""
api/omniroute.py — HTTP client for the OmniRoute API.

Three responsibilities only:
  1. fetch_models()   — pull the model catalog
  2. check_connection() — lightweight connectivity probe
  3. send_chat()      — POST a chat completion and return parsed results
"""

import json
import time

import requests

import config
from ui.console import console


# ------------------------------------------------------------------
# MODEL CATALOG
# ------------------------------------------------------------------

def fetch_models(show_message=False):
    """
    Fetch the model list from OmniRoute and populate config.model_catalog
    and config.model_map.

    Returns True on success, False on any error.
    """
    try:
        response = requests.get(
            config.MODELS_URL,
            headers={"Authorization": f"Bearer {config.API_KEY}"},
            timeout=15
        )

        if response.status_code != 200:
            if show_message:
                from rich.panel import Panel
                console.print(
                    Panel(
                        response.text,
                        title="Model Fetch Error",
                        border_style="red"
                    )
                )
            return False

        result = response.json()

        config.raw_model_catalog = sorted(
            result.get("data", []),
            key=lambda item: item.get("id", "").lower()
        )

        config.raw_model_map = {
            item.get("id"): item
            for item in config.raw_model_catalog
            if item.get("id")
        }

        # Sync provider registry with the raw catalog (passive discovery of all providers)
        try:
            from core.provider_health import sync_catalog
            sync_catalog(config.raw_model_catalog)
        except Exception:
            pass

        # Apply AIZEN Free-Only Model Registry policy
        from core.free_model_registry import filter_free_models
        config.model_catalog = filter_free_models(config.raw_model_catalog)

        config.model_map = {
            item.get("id"): item
            for item in config.model_catalog
            if item.get("id")
        }

        if show_message:
            console.print(
                f"[green]✓ Loaded {len(config.model_catalog)} verified-free models[/green] "
                f"[dim]({len(config.raw_model_catalog)} total discovered)[/dim]"
            )

        return True

    except requests.exceptions.ConnectionError:
        if show_message:
            console.print("[red]Cannot connect to OmniRoute.[/red]")
        return False

    except Exception as error:
        if show_message:
            console.print(f"[red]Model fetch error: {error}[/red]")
        return False


# ------------------------------------------------------------------
# CONNECTION PROBE
# ------------------------------------------------------------------

def check_connection():
    """Return True if OmniRoute responds with HTTP 200."""
    try:
        response = requests.get(
            config.MODELS_URL,
            headers={"Authorization": f"Bearer {config.API_KEY}"},
            timeout=3
        )
        return response.status_code == 200
    except Exception:
        return False


# ------------------------------------------------------------------
# PASSIVE HEALTH HELPERS
# ------------------------------------------------------------------

def _passive_success(actual_model: str, response_time: float):
    """Record a successful request into the provider health registry."""
    try:
        from core.provider_health import get_provider_for_model, record_success
        provider = get_provider_for_model(actual_model)
        if provider:
            record_success(provider, actual_model, response_time * 1000)
    except Exception:
        pass  # Health recording must never crash the app


def _passive_failure(
    model: str,
    status_code: int | None,
    error_text: str,
    response_time: float,
    diagnostics: dict | None = None,
):
    """Record a failed request into the provider health registry."""
    try:
        from core.provider_health import get_provider_for_model, record_failure
        provider = get_provider_for_model(model)
        if provider:
            record_failure(
                provider,
                model,
                error_text,
                error_code=status_code,
                diagnostics=diagnostics,
            )
    except Exception:
        pass  # Health recording must never crash the app


class OmniRouteAPIError(RuntimeError):
    """
    Subclass of RuntimeError raised on non-200 HTTP responses.
    Exposes status_code, retry_after, response_headers, and parsed details
    while remaining backward-compatible with any code catching RuntimeError.
    """
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
        response_headers: dict | None = None,
        raw_body: str = "",
        detected_tpm_limit: int | None = None,
        requested_tokens: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.response_headers = response_headers or {}
        self.raw_body = raw_body
        self.detected_tpm_limit = detected_tpm_limit
        self.requested_tokens = requested_tokens


def _handle_http_error(response, model: str, response_time: float) -> OmniRouteAPIError:
    """Helper to process and construct OmniRouteAPIError from failed HTTP response."""
    status_code = response.status_code
    text = response.text
    headers = dict(response.headers) if hasattr(response, "headers") else {}

    try:
        from core.context_budget import (
            parse_api_error,
            record_detected_tpm_limit,
            set_model_cooldown,
        )
        details = parse_api_error(status_code, text, headers)
        if details.detected_tpm_limit:
            record_detected_tpm_limit(model, details.detected_tpm_limit)
        if details.retry_after and details.retry_after > 0:
            set_model_cooldown(model, details.retry_after)

        diag = {
            "retry_after": details.retry_after,
            "detected_tpm": details.detected_tpm_limit,
            "requested_tokens": details.requested_tokens,
            "status_code": status_code,
        }
        _passive_failure(model, status_code, text, response_time, diagnostics=diag)

        return OmniRouteAPIError(
            details.error_message or text,
            status_code=status_code,
            retry_after=details.retry_after,
            response_headers=headers,
            raw_body=text,
            detected_tpm_limit=details.detected_tpm_limit,
            requested_tokens=details.requested_tokens,
        )
    except Exception:
        _passive_failure(model, status_code, text, response_time)
        return OmniRouteAPIError(text, status_code=status_code, raw_body=text)


# ------------------------------------------------------------------
# CHAT COMPLETION
# ------------------------------------------------------------------

def send_chat(messages, model):
    """
    POST a non-streaming chat completion request.

    Returns a dict:
        {
            "answer":        str,
            "actual_model":  str,
            "prompt_tokens": int | None,
            "completion_tokens": int | None,
            "total_tokens":  int | None,
            "response_time": float
        }

    Raises:
        requests.exceptions.Timeout      — on timeout
        requests.exceptions.ConnectionError — if OmniRoute is unreachable
        KeyboardInterrupt                  — propagated from signal
        OmniRouteAPIError / RuntimeError    — if API returns non-200
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }

    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json"
    }

    start_time = time.time()

    response = requests.post(
        config.CHAT_URL,
        headers=headers,
        json=payload,
        timeout=90
    )

    response_time = time.time() - start_time

    if response.status_code != 200:
        raise _handle_http_error(response, model, response_time)

    result = response.json()

    answer = result["choices"][0]["message"]["content"]
    actual_model = result.get("model", model)

    usage = result.get("usage", {})
    prompt_tokens = int(usage["prompt_tokens"]) if (usage and usage.get("prompt_tokens") is not None) else None
    completion_tokens = int(usage["completion_tokens"]) if (usage and usage.get("completion_tokens") is not None) else None
    total_tokens = int(usage["total_tokens"]) if (usage and usage.get("total_tokens") is not None) else None

    _passive_success(actual_model, response_time)

    return {
        "answer": answer,
        "actual_model": actual_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "response_time": response_time
    }


def stream_chat(messages, model):
    """
    POST a streaming chat completion request to OmniRoute.

    Yields events:
        ("content", delta_text)
        ("done", {
            "actual_model": str,
            "prompt_tokens": int | None,
            "completion_tokens": int | None,
            "total_tokens": int | None,
            "response_time": float
        })

    Raises:
        requests.exceptions.Timeout
        requests.exceptions.ConnectionError
        KeyboardInterrupt
        OmniRouteAPIError / RuntimeError
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True}
    }

    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json"
    }

    start_time = time.time()

    with requests.post(
        config.CHAT_URL,
        headers=headers,
        json=payload,
        timeout=90,
        stream=True
    ) as response:
        if response.status_code != 200:
            raise _handle_http_error(response, model, time.time() - start_time)

        actual_model = model
        usage = None

        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = (
                raw_line.decode("utf-8").strip()
                if isinstance(raw_line, bytes)
                else raw_line.strip()
            )
            if not line or line.startswith(":"):
                continue

            if line.startswith("data: "):
                data_str = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
            else:
                continue

            if data_str == "[DONE]":
                break

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if "model" in chunk and chunk["model"]:
                actual_model = chunk["model"]

            if "usage" in chunk and chunk["usage"]:
                usage = chunk["usage"]

            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield ("content", content)

        response_time = time.time() - start_time

        _passive_success(actual_model, response_time)

        prompt_tokens = int(usage["prompt_tokens"]) if (usage and usage.get("prompt_tokens") is not None) else None
        completion_tokens = int(usage["completion_tokens"]) if (usage and usage.get("completion_tokens") is not None) else None
        total_tokens = int(usage["total_tokens"]) if (usage and usage.get("total_tokens") is not None) else None

        yield ("done", {
            "actual_model": actual_model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "response_time": response_time
        })

