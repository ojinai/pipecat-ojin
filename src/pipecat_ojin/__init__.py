"""pipecat-ojin: Ojin avatar (Speech-To-Video) service for Pipecat."""

from pipecat_ojin.video import (
    OjinBotStartedSpeakingFrame,
    OjinBotStoppedSpeakingFrame,
    OjinFirstVideoFrame,
    OjinVideoInitializedFrame,
    OjinVideoService,
    OjinVideoSettings,
)

__version__ = "0.1.0"

__all__ = [
    "OjinBotStartedSpeakingFrame",
    "OjinBotStoppedSpeakingFrame",
    "OjinFirstVideoFrame",
    "OjinVideoInitializedFrame",
    "OjinVideoService",
    "OjinVideoSettings",
    "__version__",
]
