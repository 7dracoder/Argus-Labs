"""Privacy-preserving interface between a Presage client and RoboForge.

Presage runs where the camera is available. This backend deliberately accepts
only a coarse, user-consented interaction state; it never accepts raw video or
biometric readings.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PresageInteractionSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent: bool
    state: Literal["focused", "needs_guidance", "needs_break"]
    confidence: float = Field(ge=0, le=1)


def recommended_interface(signal: PresageInteractionSignal) -> dict:
    """Return ephemeral presentation settings, without persisting the signal."""
    if not signal.consent:
        raise ValueError("Presage adaptation requires explicit, current-session consent.")

    if signal.state == "needs_guidance":
        return {
            "mode": "guided",
            "language_level": "plain",
            "voice_speed": 0.85,
            "suggested_message": "I can explain this in simpler steps and show the cheapest safe option.",
        }
    if signal.state == "needs_break":
        return {
            "mode": "pause_offer",
            "language_level": "plain",
            "voice_speed": 0.8,
            "suggested_message": "Would you like to pause, save this revision, or continue with a short summary?",
        }
    return {
        "mode": "standard",
        "language_level": "technical",
        "voice_speed": 1.0,
        "suggested_message": None,
    }
