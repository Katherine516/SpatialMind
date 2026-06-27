import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class LLMConfig:
    provider: str = "local"
    model: str = ""
    api_key: str = ""
    timeout_seconds: int = 45
    max_tokens: int = 1200


class LLMProvider:
    """Provider boundary for future hosted LLM planning calls."""

    provider_name = "base"

    def generate_plan_json(self, prompt: str, system_prompt: str) -> Dict[str, object]:
        raise NotImplementedError


class OpenAIResponsesProvider(LLMProvider):
    """OpenAI Responses API adapter.

    This adapter is intentionally tiny and avoids a required SDK dependency. It
    is only called when selected explicitly through CLI/config.
    """

    provider_name = "openai"

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def generate_plan_json(self, prompt: str, system_prompt: str) -> Dict[str, object]:
        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI provider.")
        model = self.config.model or os.environ.get("OPENAI_MODEL", "")
        if not model:
            raise RuntimeError("Set --llm-model or OPENAI_MODEL for the OpenAI provider.")
        payload = {
            "model": model,
            "instructions": system_prompt,
            "input": prompt,
            "max_output_tokens": self.config.max_tokens,
        }
        data = _post_json(
            "https://api.openai.com/v1/responses",
            payload,
            {
                "Authorization": "Bearer %s" % api_key,
                "Content-Type": "application/json",
            },
            self.config.timeout_seconds,
        )
        text = data.get("output_text") or _extract_openai_text(data)
        return _loads_json_object(text)


class AnthropicMessagesProvider(LLMProvider):
    """Anthropic Messages API adapter for Claude Opus/Sonnet models."""

    provider_name = "anthropic"

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def generate_plan_json(self, prompt: str, system_prompt: str) -> Dict[str, object]:
        api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for the Anthropic provider.")
        model = self.config.model or os.environ.get("ANTHROPIC_MODEL", "")
        if not model:
            raise RuntimeError("Set --llm-model or ANTHROPIC_MODEL for the Anthropic provider.")
        payload = {
            "model": model,
            "max_tokens": self.config.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            payload,
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            self.config.timeout_seconds,
        )
        text = _extract_anthropic_text(data)
        return _loads_json_object(text)


class StaticLLMProvider(LLMProvider):
    """Test double for deterministic LLM planning tests."""

    provider_name = "static"

    def __init__(self, response: Dict[str, object]) -> None:
        self.response = response

    def generate_plan_json(self, prompt: str, system_prompt: str) -> Dict[str, object]:
        return self.response


def build_llm_provider(provider: str, model: str = "", api_key: str = "") -> Optional[LLMProvider]:
    normalized = (provider or "local").lower()
    config = LLMConfig(provider=normalized, model=model, api_key=api_key)
    if normalized in ("", "local", "rules", "rule-based", "none"):
        return None
    if normalized in ("openai", "gpt"):
        return OpenAIResponsesProvider(config)
    if normalized in ("anthropic", "claude"):
        return AnthropicMessagesProvider(config)
    raise ValueError("Unsupported LLM provider: %s" % provider)


def _post_json(url: str, payload: Dict[str, object], headers: Dict[str, str], timeout: int) -> Dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("LLM provider returned HTTP %s: %s" % (exc.code, body)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach LLM provider: %s" % exc.reason) from exc


def _extract_openai_text(data: Dict[str, object]) -> str:
    chunks: List[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks)


def _extract_anthropic_text(data: Dict[str, object]) -> str:
    chunks: List[str] = []
    for content in data.get("content", []):
        if isinstance(content, dict) and content.get("type") == "text":
            chunks.append(str(content.get("text", "")))
    return "\n".join(chunks)


def _loads_json_object(text: str) -> Dict[str, object]:
    if not text:
        raise RuntimeError("LLM provider returned no text.")
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM provider returned JSON that is not an object.")
    return parsed
