"""Validated Gemini/GLM output, with opt-in GLM failover on Gemini quota errors."""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from threading import Lock
from time import monotonic
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_GLM_MODEL = "glm-5.3"
DEFAULT_BASETEN_MODEL = "zai-org/GLM-5.3"
_fallback_lock = Lock()
_fallback_until: dict[tuple[str, str, str], float] = {}


class LLMUnavailable(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    """Upstream response was incomplete or failed schema validation."""


def _fallback_provider() -> str:
    provider = os.environ.get("LLM_FALLBACK_PROVIDER", "").strip().lower()
    if provider not in {"", "baseten", "glm"}:
        raise LLMUnavailable("LLM_FALLBACK_PROVIDER must be baseten, glm, or empty to disable.")
    return provider


def _fallback_identity(provider: str) -> tuple[str, str, str]:
    # Scope the cooldown to the primary key/model; rotating a key can recover immediately.
    return (os.environ.get("GEMINI_API_KEY", "").strip(),
            os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), provider)


def _fallback_remaining(provider: str) -> float:
    with _fallback_lock:
        identity = _fallback_identity(provider)
        remaining = _fallback_until.get(identity, 0) - monotonic()
        if remaining <= 0:
            _fallback_until.pop(identity, None)
        return max(0, remaining)


def _fallback_cooldown() -> int:
    try:
        seconds = int(os.environ.get("LLM_FALLBACK_COOLDOWN_SECONDS", "60"))
    except ValueError:
        seconds = 0
    if not 1 <= seconds <= 3600:
        raise LLMUnavailable("LLM_FALLBACK_COOLDOWN_SECONDS must be between 1 and 3600.")
    return seconds


def _glm_key(provider: str) -> str:
    key = ((os.environ.get("BASETEN_API_KEY") or os.environ.get("GLM_API_KEY"))
           if provider == "baseten" else (os.environ.get("GLM_API_KEY") or os.environ.get("ZAI_API_KEY")))
    return (key or "").strip()


def _glm_rejection(response, baseten: bool = False) -> str:
    """Map documented codes to safe advice; never expose vendor error bodies."""
    if baseten:
        if response.status_code == 401:
            return ("Baseten authentication failed (401). Set a valid BASETEN_API_KEY or GLM_API_KEY "
                    "in the root .env, then restart the backend.")
        if response.status_code == 403:
            return "Baseten denied model access (403). Check API key permissions and Model API access."
        if response.status_code == 429:
            return "Baseten rate or account limit reached (429). Check your account limits and credits."
        return f"Baseten rejected the GLM request ({response.status_code})."
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = str(error.get("code", "")) if isinstance(error, dict) else ""
    except (ValueError, TypeError):
        code = ""
    if response.status_code == 401:
        if code == "1005":
            return "GLM authentication requires two-factor verification in your Z.ai account."
        return ("GLM authentication failed (401). Replace GLM_API_KEY in the root .env with a valid "
                "key from the account matching GLM_BASE_URL, then restart the backend.")
    if code == "1113":
        return "GLM account balance or API resource package is insufficient. Check your provider account."
    if code in {"1309", "1311", "1315"}:
        return "GLM model access is unavailable for this account or key type. Check your plan and GLM_BASE_URL."
    return f"GLM rejected the request ({response.status_code})."


def llm_status() -> dict:
    provider = os.environ.get("LLM_PROVIDER", "glm").strip().lower()
    if provider in {"glm", "baseten"}:
        baseten = provider == "baseten"
        key = (os.environ.get("BASETEN_API_KEY") or os.environ.get("GLM_API_KEY")) if baseten else (
            os.environ.get("GLM_API_KEY") or os.environ.get("ZAI_API_KEY"))
        return {"provider": provider,
                "model": os.environ.get("GLM_MODEL", DEFAULT_BASETEN_MODEL if baseten else DEFAULT_GLM_MODEL),
                "configured": bool(key and key.strip())}
    if provider == "gemini":
        result = {"provider": provider, "model": os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
                  "configured": bool(os.environ.get("GEMINI_API_KEY", "").strip())}
        try:
            fallback = _fallback_provider()
        except LLMUnavailable as error:
            return {**result, "error": str(error)}
        if fallback:
            remaining = _fallback_remaining(fallback)
            result.update(fallback_provider=fallback, fallback_configured=bool(_glm_key(fallback)),
                          fallback_model=os.environ.get("GLM_MODEL", DEFAULT_BASETEN_MODEL
                              if fallback == "baseten" else DEFAULT_GLM_MODEL),
                          active_provider=fallback if remaining else provider,
                          fallback_reason="gemini_quota_exhausted" if remaining else None,
                          primary_retry_after_seconds=math.ceil(remaining))
        return result
    return {"provider": provider, "configured": False, "error": "Choose baseten, glm (Z.ai), or gemini."}


def _generate_glm(system: str, prompt: str, schema: type[T], *, provider: str | None = None) -> T:
    import httpx

    provider = provider or os.environ.get("LLM_PROVIDER", "glm").strip().lower()
    baseten = provider == "baseten"
    api_key = _glm_key(provider)
    if not api_key:
        raise LLMUnavailable("Set BASETEN_API_KEY (or GLM_API_KEY) on the backend." if baseten else
                             "Set GLM_API_KEY (or ZAI_API_KEY) on the backend.")
    default_url = "https://inference.baseten.co/v1" if baseten else "https://api.z.ai/api/paas/v4"
    base_url = os.environ.get("GLM_BASE_URL", default_url).strip().rstrip("/")
    if not base_url.startswith("https://"):
        raise LLMUnavailable("GLM_BASE_URL must use HTTPS.")
    effort = os.environ.get("GLM_REASONING_EFFORT", "low")
    if effort not in {"low", "high", "max"}:
        raise LLMUnavailable("GLM_REASONING_EFFORT must be low, high, or max.")
    payload = {
        "model": os.environ.get("GLM_MODEL", DEFAULT_BASETEN_MODEL if baseten else DEFAULT_GLM_MODEL),
        "messages": [
            {"role": "system", "content": system + "\nReturn only a JSON object matching this JSON Schema:\n"
             + json.dumps(schema.model_json_schema())},
            {"role": "user", "content": prompt},
        ],
        "stream": False, "response_format": {"type": "json_object"},
        "reasoning_effort": effort, "max_tokens": 16384,
    }
    # Baseten controls GLM reasoning with reasoning_effort, not Z.ai's extension.
    if not baseten:
        payload["thinking"] = {"type": "enabled"}
    try:
        # Keep credentials at the configured host; never follow redirects.
        with httpx.Client(timeout=120, follow_redirects=False) as client:
            response = client.post(f"{base_url}/chat/completions", json=payload,
                                   headers={"Authorization": f"Bearer {api_key}"})
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise LLMResponseError(_glm_rejection(error.response, baseten)) from None
    except httpx.RequestError as error:
        raise LLMResponseError("GLM could not be reached.") from error
    try:
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise LLMResponseError("GLM did not finish a complete JSON answer.")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("GLM returned no JSON answer.")
        return schema.model_validate_json(content)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise LLMResponseError("GLM returned invalid structured output.") from error


@lru_cache(maxsize=2)
def _gemini_client(api_key: str):
    from google import genai
    from google.genai import types
    # Hand quota errors to our explicit backup policy instead of SDK retry loops.
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(
        timeout=120000, retry_options=types.HttpRetryOptions(attempts=1)))


def generate_structured(system: str, prompt: str, schema: type[T]) -> T:
    """Switch providers without changing Architect or Mechanical agents."""
    provider = os.environ.get("LLM_PROVIDER", "glm").strip().lower()
    if provider in {"glm", "baseten"}:
        return _generate_glm(system, prompt, schema, provider=provider)
    if provider != "gemini":
        raise LLMUnavailable("LLM_PROVIDER must be baseten, glm (Z.ai), or gemini.")
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    fallback = _fallback_provider()
    cooldown = _fallback_cooldown() if fallback else 0
    if fallback and _fallback_remaining(fallback):
        return _generate_glm(system, prompt, schema, provider=fallback)
    from google.genai import errors, types
    import httpx
    try:
        response = _gemini_client(api_key).models.generate_content(
            model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system,
                # Native JSON Schema preserves $defs/additionalProperties and avoids
                # the SDK's legacy Schema conversion of extra="forbid" CAD models.
                response_mime_type="application/json", response_json_schema=schema.model_json_schema(),
                temperature=0.3),
        )
    except errors.APIError as error:
        if error.code == 429:
            if fallback and _glm_key(fallback):
                with _fallback_lock:
                    _fallback_until[_fallback_identity(fallback)] = monotonic() + cooldown
                return _generate_glm(system, prompt, schema, provider=fallback)
            raise LLMResponseError("Gemini quota or rate limit reached (429). Configure a GLM backup or retry later.") from None
        if error.code in {401, 403}:
            raise LLMResponseError("Gemini authentication or access failed. Check GEMINI_API_KEY and model access, then restart the backend.") from None
        raise LLMResponseError(f"Gemini rejected the request ({error.code}).") from None
    except httpx.RequestError:
        raise LLMResponseError("Gemini could not be reached.") from None
    except (ValueError, TypeError):
        raise LLMResponseError("Gemini returned invalid structured output.") from None
    try:
        if isinstance(response.parsed, schema):
            return response.parsed
        return schema.model_validate_json(response.text or "{}")
    except (ValueError, TypeError):
        raise LLMResponseError("Gemini returned invalid structured output.") from None
