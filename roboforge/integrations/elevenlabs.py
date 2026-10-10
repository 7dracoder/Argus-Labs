"""ElevenLabs speech input/output; credentials stay in the backend."""
from __future__ import annotations

import os
import re

import httpx


class ElevenLabsUnavailable(RuntimeError):
    """Sanitized configuration or vendor failure."""


class ElevenLabsClient:
    base_url = "https://api.elevenlabs.io/v1"

    def __init__(self) -> None:
        self.api_key = os.environ.get("ELEVENLABS_API_KEY")
        self.default_voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
        self.model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
        self.stt_model_id = os.environ.get("ELEVENLABS_STT_MODEL_ID", "scribe_v2")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.default_voice_id)

    def _request(self, path: str, **kwargs) -> httpx.Response:
        if not self.api_key:
            raise ElevenLabsUnavailable("Set ELEVENLABS_API_KEY in .env.")
        try:
            with httpx.Client(timeout=60, follow_redirects=False) as client:
                response = client.post(f"{self.base_url}/{path}",
                                       headers={"xi-api-key": self.api_key}, **kwargs)
            if not response.is_success:
                raise ElevenLabsUnavailable(f"ElevenLabs rejected the request ({response.status_code}). Check key permissions, credits, and model access.")
            return response
        except httpx.RequestError:
            raise ElevenLabsUnavailable("ElevenLabs could not be reached.") from None

    def synthesize(self, text: str, voice_id: str | None = None, speed: float = 1.0) -> bytes:
        selected_voice = voice_id or self.default_voice_id
        if not selected_voice or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", selected_voice):
            raise ElevenLabsUnavailable("Set a valid ELEVENLABS_VOICE_ID in .env.")
        if not 0.7 <= speed <= 1.2:
            raise ValueError("Voice speed must be between 0.7 and 1.2.")
        response = self._request(
            f"text-to-speech/{selected_voice}", params={"output_format": "mp3_44100_128"},
            json={"text": text, "model_id": self.model_id,
                  "voice_settings": {"stability": 0.65, "similarity_boost": 0.75,
                                     "style": 0, "use_speaker_boost": True, "speed": speed}},
        )
        if not response.content or not response.headers.get("content-type", "").startswith("audio/"):
            raise ElevenLabsUnavailable("ElevenLabs returned no playable audio.")
        return response.content

    def transcribe(self, audio: bytes, content_type: str) -> dict:
        response = self._request(
            "speech-to-text", data={"model_id": self.stt_model_id, "diarize": "false",
                                    "tag_audio_events": "false"},
            files={"file": ("recording", audio, content_type)},
        )
        try:
            payload = response.json()
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise ValueError("No supported transcript")
            return {"text": text.strip(), "language_code": payload.get("language_code")}
        except (ValueError, AttributeError):
            raise ElevenLabsUnavailable("ElevenLabs returned an empty or invalid transcript. Use a short recording.") from None


elevenlabs = ElevenLabsClient()
