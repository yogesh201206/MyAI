import json
from unittest.mock import Mock, patch

import config
from api import ollama


class FakeResponse:
    def __init__(self, payload=None, status_code=200, lines=None):
        self._payload = payload or {}
        self.status_code = status_code
        self.ok = status_code == 200
        self.text = json.dumps(self._payload)
        self._lines = lines or []

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.text)

    def iter_lines(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_models_namespaces_and_caps_context():
    config.OLLAMA_BASE_URL = "http://localhost:11434"
    config.OLLAMA_NUM_CTX = 8192
    tags = FakeResponse({"models": [{"name": "qwen3:4b", "size": 123}]})
    show = FakeResponse({"model_info": {"qwen3.context_length": 262144}})
    with patch.object(ollama.requests, "get", return_value=tags), \
         patch.object(ollama.requests, "post", return_value=show):
        models = ollama.fetch_models()
    assert models[0]["id"] == "ollama:qwen3:4b"
    assert models[0]["source"] == "ollama"
    assert models[0]["context_length"] == 8192
    assert "ollama:qwen3:4b" in config.local_model_map


def test_send_chat_normalizes_usage():
    response = FakeResponse({
        "model": "qwen3:4b",
        "message": {"content": "Hello from local"},
        "prompt_eval_count": 12,
        "eval_count": 7,
    })
    with patch.object(ollama.requests, "post", return_value=response):
        result = ollama.send_chat([{"role": "user", "content": "Hi"}], "ollama:qwen3:4b")
    assert result["answer"] == "Hello from local"
    assert result["actual_model"] == "ollama:qwen3:4b"
    assert result["prompt_tokens"] == 12
    assert result["completion_tokens"] == 7
    assert result["total_tokens"] == 19


def test_stream_chat_emits_content_and_done_usage():
    lines = [
        b'{"model":"qwen3:4b","message":{"content":"Hello "},"done":false}',
        b'{"model":"qwen3:4b","message":{"content":"world"},"done":false}',
        b'{"model":"qwen3:4b","done":true,"prompt_eval_count":4,"eval_count":2}',
    ]
    response = FakeResponse(lines=lines)
    with patch.object(ollama.requests, "post", return_value=response):
        events = list(ollama.stream_chat([], "ollama:qwen3:4b"))
    assert events[0] == ("content", "Hello ")
    assert events[1] == ("content", "world")
    assert events[-1][0] == "done"
    assert events[-1][1]["total_tokens"] == 6
