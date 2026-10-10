"""Small server-side ElevenLabs text-to-speech client."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ElevenLabsUnavailable(RuntimeError):
    """Raised when speech synthesis cannot be used safely."""


class ElevenLabsClient:
    api_url = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(self) -> None:
        self.api_key = os.environ.get("ELEVENLABS_API_KEY")
        self.default_voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
        self.model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.default_voice_id)

    def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        """Return MP3 bytes. The API key never reaches a browser client."""
        selected_voice = voice_id or self.default_voice_id
        if not self.api_key or not selected_voice:
            raise ElevenLabsUnavailable(
                "Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID on the backend."
            )

        payload = json.dumps({"text": text, "model_id": self.model_id}).encode("utf-8")
        request = Request(
            f"{self.api_url}/{selected_voice}?output_format=mp3_44100_128",
            data=payload,
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS host
                return response.read()
        except HTTPError as error:
            # Do not expose vendor payloads: they can contain account or quota details.
            raise ElevenLabsUnavailable(f"ElevenLabs rejected the request ({error.code}).") from error
        except URLError as error:
            raise ElevenLabsUnavailable("ElevenLabs could not be reached.") from error


elevenlabs = ElevenLabsClient()
