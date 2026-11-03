"""Client for an Ollama server (#27): its version, the models that can call tools, and streamed chat.

Ollama has no access keys of its own; a proxy in front of it checks one. The key goes out as a bearer token.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

# Loading a large model into GPU memory can take minutes before the first token arrives.
TIMEOUT = httpx.Timeout(10, read=300)


class OllamaError(Exception):
    """A problem worth showing to the person as it is."""


class Ollama:
    def __init__(self, url: str, key: str = "", transport: httpx.BaseTransport | None = None) -> None:
        parts = urlsplit(url.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise OllamaError("The Ollama address must start with http:// or https://")
        self.host = parts.netloc
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = httpx.Client(base_url=url.strip().rstrip("/"), headers=headers, timeout=TIMEOUT,
                                 transport=transport)

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            r = self.http.request(method, path, **kwargs)
        except httpx.TimeoutException as e:
            raise OllamaError(f"The Ollama server at {self.host} did not answer in time.") from e
        except httpx.HTTPError as e:
            raise OllamaError(f"Cannot reach the Ollama server at {self.host}: {e}") from e
        _check(r, self.host)
        return r

    def version(self) -> str:
        return self._send("GET", "/api/version").json().get("version", "?")

    def models(self) -> list[dict]:
        """Models that can call tools, smallest first: the others cannot use Clipcura."""
        out = []
        for m in self._send("GET", "/api/tags").json().get("models", []):
            caps = m.get("capabilities") or []
            if "tools" not in caps:
                continue
            out.append({"name": m["name"], "size": m.get("size", 0),
                        "parameters": (m.get("details") or {}).get("parameter_size", ""),
                        "vision": "vision" in caps, "cloud": m["name"].endswith("cloud")})
        return sorted(out, key=lambda m: (m["size"], m["name"]))

    def chat(self, model: str, messages: list[dict], tools: list[dict], on_text: Callable[[str], None],
             cancel: threading.Event | None = None) -> dict:
        """One model reply, streamed: text goes to `on_text` as it arrives; tool calls come back in the reply."""
        content: list[str] = []
        calls: list[dict] = []
        body = {"model": model, "messages": messages, "tools": tools, "stream": True}
        try:
            with self.http.stream("POST", "/api/chat", json=body) as r:
                if r.status_code >= 400:
                    r.read()
                    _check(r, self.host)
                for line in r.iter_lines():
                    if cancel is not None and cancel.is_set():
                        break
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise OllamaError(f"Ollama: {chunk['error']}")
                    message = chunk.get("message") or {}
                    if message.get("content"):
                        content.append(message["content"])
                        on_text(message["content"])
                    calls.extend(message.get("tool_calls") or [])
                    if chunk.get("done"):
                        break
        except httpx.TimeoutException as e:
            raise OllamaError(f"The Ollama server at {self.host} did not answer in time.") from e
        except httpx.HTTPError as e:
            raise OllamaError(f"Cannot reach the Ollama server at {self.host}: {e}") from e
        except json.JSONDecodeError as e:
            raise OllamaError(f"The server at {self.host} did not answer like Ollama.") from e
        reply: dict = {"role": "assistant", "content": "".join(content)}
        if calls:
            reply["tool_calls"] = calls
        return reply


def _check(r: httpx.Response, host: str) -> None:
    if r.status_code in (401, 403):
        raise OllamaError(f"The Ollama server at {host} refused the access key (HTTP {r.status_code}).")
    if r.status_code >= 400:
        try:
            detail = r.json().get("error") or r.text
        except ValueError:
            detail = r.text
        raise OllamaError(f"Ollama at {host} answered {r.status_code}: {str(detail)[:300]}")
