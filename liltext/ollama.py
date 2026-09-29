from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:11434"


class OllamaError(RuntimeError):
    pass


def _request(url: str, payload: dict | None = None, timeout: float = 10) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            detail = json.loads(body).get("error", body)
        except (OSError, json.JSONDecodeError):
            detail = str(exc)
        raise OllamaError(str(detail)) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise OllamaError(f"Ollama is unavailable at {url.rsplit('/', 1)[0]}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama returned malformed JSON") from exc


def models(base_url: str = DEFAULT_URL) -> list[str]:
    data = _request(f"{base_url}/api/tags", timeout=5)
    try:
        return sorted(str(item["name"]) for item in data.get("models", []))
    except (TypeError, KeyError) as exc:
        raise OllamaError("Ollama returned an invalid /api/tags response") from exc


def chat(model: str, messages: list[dict], *, max_tokens: int = 200, timeout: float = 120, base_url: str = DEFAULT_URL) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": messages,
        "options": {"num_predict": max_tokens},
    }
    try:
        data = _request(f"{base_url}/api/chat", payload, timeout=timeout)
        content = data["message"]["content"]
    except KeyError as exc:
        error = data.get("error") if isinstance(data, dict) else None
        raise OllamaError(error or "Ollama returned an invalid chat response") from exc
    if not isinstance(content, str):
        raise OllamaError("Ollama returned a non-text response")
    return content.strip()
