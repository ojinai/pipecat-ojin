"""OjinSTVWebRTCService — a Pipecat adapter for direct-WebRTC avatar sessions.

In direct mode the inference server publishes the avatar's A/V into the room
itself, so this service pushes no audio or video frames downstream. It forwards
the TTS audio stream to ``ojin.stv.OjinSTVWebRTCClient`` and maps the client's
lifecycle events (derived from the server's metadata frames) onto the same
Pipecat frames :class:`~pipecat_ojin.video.OjinVideoService` emits, keeping the
rest of the pipeline identical between relay and direct sessions.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from ojin.stv import (
    OjinSessionTrace,
    OjinSTVWebRTCClient,
    STVEvent,
    WebRTCSettings,
)
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipecat_ojin.video import (
    OjinBotStartedSpeakingFrame,
    OjinBotStoppedSpeakingFrame,
    OjinFirstVideoFrame,
    OjinVideoInitializedFrame,
    OjinVideoSettings,
)

logger = logging.getLogger(__name__)

_TRACE_ROOT = os.getenv("OJIN_STV_TRACE_DIR", "/root/debug/sessions/stv-pipecat-ojin")
_HALF_SECOND = 0.5
_HALF_SECOND_TOL = 0.01


class OjinSTVWebRTCService(FrameProcessor):
    """Pipecat FrameProcessor for an avatar the inference server publishes itself."""

    def __init__(
        self,
        settings: OjinVideoSettings,
        webrtc_settings: WebRTCSettings,
        *,
        session_trace: Optional[OjinSessionTrace] = None,
        stv_client: Optional[OjinSTVWebRTCClient] = None,
    ) -> None:
        """Build the adapter and wire the client's lifecycle events.

        Args:
            settings: connection identity + client behavior knobs.
            webrtc_settings: room credentials the server needs to join.
            session_trace: an ``ojin.stv.OjinSessionTrace`` to record this call;
                injected as the client's tracer and dumped to disk on close.
                ``None`` -> the client uses a no-op tracer.
            stv_client: a pre-built client (dependency injection for tests).
                When given, ``settings``/``webrtc_settings`` connection fields
                are not used to build a client.
        """
        super().__init__(name="ojin-stv-webrtc")
        self._settings = settings
        self._first_video_pushed = False
        self._waiting_for_first_tts = False
        self._trace = session_trace
        self._stv = stv_client or OjinSTVWebRTCClient(
            webrtc_settings=webrtc_settings,
            api_key=settings.api_key,
            config_id=settings.config_id,
            ws_url=settings.ws_url,
            tracer=session_trace,
            config=settings.stv_config,
            buffer_preinit_tts_audio=settings.buffer_preinit_tts_audio,
        )
        self._wire_events()

    def set_can_start_playback(self, value: bool) -> None:
        """API-compatibility no-op: this service holds no media to gate."""

    def can_generate_metrics(self) -> bool:
        """Enable Pipecat TTFB / processing metrics for this service."""
        return True

    async def connect_with_retry(self) -> bool:
        """Connect the underlying client with retry; ``True`` on success."""
        return await self._stv.connect_with_retry()

    def _wire_events(self) -> None:
        """Map ``OjinSTVWebRTCClient`` events onto Pipecat frames + TTFB metrics."""

        @self._stv.on(STVEvent.SESSION_READY)
        async def _on_ready(session_data=None, **_):
            frame = OjinVideoInitializedFrame(session_data=session_data)
            await self.push_frame(frame, FrameDirection.DOWNSTREAM)
            await self.push_frame(frame, FrameDirection.UPSTREAM)

        @self._stv.on(STVEvent.FIRST_FRAME)
        async def _on_first_frame(**_):
            if self._first_video_pushed:
                return
            self._first_video_pushed = True
            await self.push_frame(OjinFirstVideoFrame(), FrameDirection.DOWNSTREAM)
            await self.push_frame(OjinFirstVideoFrame(), FrameDirection.UPSTREAM)

        @self._stv.on(STVEvent.BOT_STARTED_SPEAKING)
        async def _on_started(**_):
            await self.push_frame(OjinBotStartedSpeakingFrame())
            await self.push_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
            await self.push_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await self.stop_ttfb_metrics()

        @self._stv.on(STVEvent.BOT_STOPPED_SPEAKING)
        async def _on_stopped(**_):
            await self.push_frame(OjinBotStoppedSpeakingFrame())
            await self.push_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
            await self.push_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

        @self._stv.on(STVEvent.ERROR)
        async def _on_error(message="", fatal=False, **_):
            await self.push_error(message, fatal=fatal)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Map each inbound Pipecat frame to the matching OjinSTVWebRTCClient call."""
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            await self._stv.start()
        elif isinstance(frame, TTSStartedFrame):
            self._waiting_for_first_tts = True
            await self._stv.start_turn()
            await self.push_frame(frame, direction)
        elif isinstance(frame, TTSAudioRawFrame):
            if self._is_trailing_silence(frame):
                return
            if self._waiting_for_first_tts:
                self._waiting_for_first_tts = False
                await self.start_ttfb_metrics()
            await self._stv.send_tts_audio(
                frame.audio, frame.sample_rate, frame.num_channels
            )
        elif isinstance(frame, InterruptionFrame):
            await self._stv.interrupt()
            await self.push_frame(frame, direction)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stv.close()
            self._write_trace()
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    @staticmethod
    def _is_trailing_silence(frame: TTSAudioRawFrame) -> bool:
        """Whether ``frame`` is the ~0.5 s all-zero trailing-silence sentinel.

        Mirrors ``OjinSTVWebRTCClient.send_tts_audio``'s discard rule so the
        adapter can drop it before arming TTFB metrics (which must time the
        first real audio).
        """
        pcm = frame.audio
        if not pcm or any(pcm):
            return False
        duration = len(pcm) / (frame.sample_rate * frame.num_channels * 2)
        return abs(duration - _HALF_SECOND) < _HALF_SECOND_TOL

    def _write_trace(self) -> None:
        """Dump the session's Perfetto trace to disk on close (best-effort, once)."""
        trace, self._trace = self._trace, None
        if trace is None:
            return
        now = datetime.now(timezone.utc)
        path = os.path.join(
            _TRACE_ROOT,
            now.strftime("%Y-%m-%d"),
            f"{now.strftime('%H-%M-%S')}_{trace.session_id}",
            "session.json",
        )
        try:
            logger.info("Ojin STV session trace written to %s", trace.dump(path))
        except Exception as exc:
            logger.warning("Failed to write Ojin STV session trace: %s", exc)
