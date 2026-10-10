"""Validated structured output from GLM 5.3, with opt-in Gemini support."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_GLM_MODEL = "glm-5.3"
DEFAULT_BASETEN_MODEL = "zai-org/GLM-5.3"


class LLMUnavailable(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    """Upstream response was incomplete or failed schema validation."""


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
        return {"provider": provider, "model": os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
                "configured": bool(os.environ.get("GEMINI_API_KEY"))}
    return {"provider": provider, "configured": False, "error": "Choose baseten, glm (Z.ai), or gemini."}


def _generate_glm(system: str, prompt: str, schema: type[T]) -> T:
    import httpx

    baseten = os.environ.get("LLM_PROVIDER", "glm").strip().lower() == "baseten"
    api_key = ((os.environ.get("BASETEN_API_KEY") or os.environ.get("GLM_API_KEY") or "") if baseten else
               (os.environ.get("GLM_API_KEY") or os.environ.get("ZAI_API_KEY") or "")).strip()
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
    return genai.Client(api_key=api_key)


def generate_structured(system: str, prompt: str, schema: type[T]) -> T:
    """Switch providers without changing Architect or Mechanical agents."""
    provider = os.environ.get("LLM_PROVIDER", "glm").strip().lower()
    if provider in {"glm", "baseten"}:
        return _generate_glm(system, prompt, schema)
    if provider != "gemini":
        raise LLMUnavailable("LLM_PROVIDER must be baseten, glm (Z.ai), or gemini.")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    from google.genai import types
    response = _gemini_client(api_key).models.generate_content(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system,
            response_mime_type="application/json", response_schema=schema, temperature=0.3),
    )
    if isinstance(response.parsed, schema):
        return response.parsed
    return schema.model_validate_json(response.text or "{}")
