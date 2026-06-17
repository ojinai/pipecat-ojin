"""pipecat-ojin: Ojin avatar (Speech-To-Video) and TTS services for Pipecat."""

from pipecat_ojin.video import (
    OjinBotStartedSpeakingFrame,
    OjinBotStoppedSpeakingFrame,
    OjinVideoInitializedFrame,
    OjinVideoService,
    OjinVideoSettings,
)

__version__ = "0.1.0"

__all__ = [
    "OjinBotStartedSpeakingFrame",
    "OjinBotStoppedSpeakingFrame",
    "OjinVideoInitializedFrame",
    "OjinVideoService",
    "OjinVideoSettings",
    "__version__",
]
