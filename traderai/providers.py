"""Small adapters for native LLM APIs and OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class ProviderError(Exception):
    """A provider request failed without exposing credentials or response bodies."""


@dataclass
class LLMClient:
    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    timeout: float = 120

    def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.provider in ("openai", "openai-compatible"):
            base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
            url = f"{base}/chat/completions"
            headers["Authorization"] = f"Bearer {self.api_key}"
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            }
        elif self.provider == "anthropic":
            url = f"{(self.base_url or 'https://api.anthropic.com/v1').rstrip('/')}/messages"
            headers.update({"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
            payload = {"model": self.model, "max_tokens": 2048, "system": system,
                       "messages": [{"role": "user", "content": user}]}
        elif self.provider == "gemini":
            base = (self.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
            url = f"{base}/models/{urllib.parse.quote(self.model, safe='')}:generateContent"
            headers["x-goog-api-key"] = self.api_key
            payload = {"systemInstruction": {"parts": [{"text": system}]},
                       "contents": [{"role": "user", "parts": [{"text": user}]}]}
        else:
            raise ProviderError(f"Unsupported provider: {self.provider}")

        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"{self.provider} returned HTTP {exc.code}. Check your model, API key, and endpoint.") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Could not reach {self.provider} ({type(exc).__name__}).") from None
        except (ValueError, UnicodeDecodeError):
            raise ProviderError(f"{self.provider} returned invalid JSON.") from None

        try:
            if self.provider in ("openai", "openai-compatible"):
                result = data["choices"][0]["message"]["content"]
            elif self.provider == "anthropic":
                result = "\n".join(part["text"] for part in data["content"] if part.get("type") == "text")
            else:
                result = "\n".join(part["text"] for part in data["candidates"][0]["content"]["parts"] if "text" in part)
            if not isinstance(result, str) or not result.strip():
                raise ValueError("empty response")
            return result.strip()
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError(f"{self.provider} returned an empty or unexpected response.") from None
