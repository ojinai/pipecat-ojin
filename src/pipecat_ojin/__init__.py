"""pipecat-ojin: Ojin avatar (Speech-To-Video) service for Pipecat."""

from ojin.stv import WebRTCSettings

from pipecat_ojin.stv_webrtc import OjinSTVWebRTCService
from pipecat_ojin.video import (
    OjinBotStartedSpeakingFrame,
    OjinBotStoppedSpeakingFrame,
    OjinFirstVideoFrame,
    OjinVideoInitializedFrame,
    OjinVideoService,
    OjinVideoSettings,
)

__version__ = "0.1.4"

__all__ = [
    "OjinBotStartedSpeakingFrame",
    "OjinBotStoppedSpeakingFrame",
    "OjinFirstVideoFrame",
    "OjinSTVWebRTCService",
    "OjinVideoInitializedFrame",
    "OjinVideoService",
    "OjinVideoSettings",
    "WebRTCSettings",
    "__version__",
]
