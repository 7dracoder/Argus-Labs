"""Gemini client wrapper. Configure with env vars:

GEMINI_API_KEY  - free key from https://aistudio.google.com/apikey
GEMINI_MODEL    - defaults to a free-tier Flash model
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-3.5-flash"


class LLMUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    from google import genai

    return genai.Client(api_key=api_key)


def generate_structured(system: str, prompt: str, schema: type[T]) -> T:
    """Call Gemini and parse the JSON response into `schema`."""
    from google.genai import types

    response = _client().models.generate_content(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.3,
        ),
    )
    if isinstance(response.parsed, schema):
        return response.parsed
    return schema.model_validate_json(response.text or "{}")
