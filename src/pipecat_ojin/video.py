"""OjinVideoService — a Pipecat adapter for an Ojin lip-synced talking avatar.

`OjinVideoService` is a Pipecat ``FrameProcessor`` that turns the TTS audio
stream into a lip-synced avatar. Place it after your TTS service and before
``transport.output()`` — the slot Pipecat's built-in avatar services use::

    transport.input() -> STT -> LLM -> TTS -> [OjinVideoService] -> transport.output()

All avatar behaviour (connect/retry, audio-as-clock playback, A/V sync, re-sync
after barge-in, off-loop JPEG decode, session tracing) lives in
``ojin.stv.OjinSTVClient``; this class is only the mapping between Pipecat frames
and the client's API. It needs ``ojin-client[stv]`` and ``pipecat-ai``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ojin.stv import (
    OjinSessionTrace,
    OjinSTVClient,
    STVAudioFrame,
    STVConfig,
    STVEvent,
    STVVideoFrame,
)
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputImageRawFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# Per-session Perfetto trace output dir (same layout as the python-sdk example).
_TRACE_ROOT = os.getenv("OJIN_STV_TRACE_DIR", "/root/debug/sessions/stv-pipecat-ojin")

# The ~0.5 s all-zero trailing-silence sentinel some TTS engines emit. These mirror
# OjinSTVClient.send_tts_audio's own discard rule (ojin.stv) so the adapter can drop
# it *before* arming TTFB — TTFB must time the first real audio, not the silence.
_HALF_SECOND = 0.5
_HALF_SECOND_TOL = 0.01


@dataclass
class OjinVideoInitializedFrame(Frame):
    """Frame indicating the avatar session is ready (server handshake complete)."""

    session_data: Optional[dict] = None


@dataclass
class OjinFirstVideoFrame(Frame):
    """First real rendered avatar frame has been pushed to the transport.

    Emitted once, when the head's first non-empty frame is forwarded downstream
    (idle or speech). Downstream consumers reveal the avatar; an upstream gate
    starts accepting user audio.
    """


class OjinBotStartedSpeakingFrame(Frame):
    """Emitted when the avatar starts speaking (a buffer is promoted to current)."""

    pass


class OjinBotStoppedSpeakingFrame(Frame):
    """Emitted when the avatar stops speaking (current buffer drains, none queued)."""

    pass


@dataclass
class OjinVideoSettings:
    """Connection identity and frame size for :class:`OjinVideoService`."""

    api_key: str = ""
    config_id: str = ""
    ws_url: str = "wss://models.ojin.ai/realtime"
    # When True (default), TTS audio sent during the avatar's cold-start handshake
    # is buffered and replayed once the session is ready, instead of dropped — so
    # an opening line isn't lost. Set False to drop pre-init audio (old behavior).
    buffer_preinit_tts_audio: bool = True
    # Behavioral knobs forwarded to the underlying OjinSTVClient (buffering, fps,
    # barge-in, and the off-by-default loop-stall diagnostics). None -> the client
    # builds its own STVConfig() defaults. Set a config to enable the stall
    # watchdog / probe (loop_stall_watchdog_ms / stall_probe_ms) in production.
    stv_config: Optional[STVConfig] = None


class _PushFrameOutput:
    """STVOutput sink: forwards the client's synced A/V downstream, behind the gate."""

    def __init__(self, service: "OjinVideoService") -> None:
        self._svc = service

    async def write_audio(self, frame: STVAudioFrame) -> None:
        if self._svc._can_start_playback:
            await self._svc.push_frame(
                OutputAudioRawFrame(frame.pcm, frame.sample_rate, frame.num_channels)
            )

    async def write_video(self, frame: STVVideoFrame) -> None:
        if self._svc._can_start_playback and frame.rgb is not None:
            if not self._svc._first_video_pushed:
                self._svc._first_video_pushed = True
                await self._svc.push_frame(
                    OjinFirstVideoFrame(), FrameDirection.DOWNSTREAM
                )
                await self._svc.push_frame(
                    OjinFirstVideoFrame(), FrameDirection.UPSTREAM
                )
            out = OutputImageRawFrame(
                image=frame.rgb,
                size=(frame.width, frame.height),
                format=frame.format,
            )
            # Carry the client's per-frame monotonic presentation timestamp
            # (STVVideoFrame.pts, nanoseconds; set in OjinSTVClient._emit_tick).
            # Previously dropped here, which left the outgoing video timeline
            # UNPINNED: with ``video_out_is_live=True`` the Daily output paces
            # video off its own wall clock and stamps RTP at draw time, so any
            # encoder/SFU re-time at a content boundary surfaces on the client
            # as a multi-second media_time/RTP jump (the turn-boundary freeze;
            # see notes/wiki/issues/30-06-2026/freeze_on_interruption).
            # NOTE: honoring this pts for pacing additionally requires
            # ``video_out_is_live=False`` AND rebasing this monotonic pts onto
            # the pipeline clock's epoch (the two clocks share no origin) — a
            # change that must be A/B-validated on a live Daily session before
            # enabling. Carrying the value here is a safe, inert prerequisite.
            out.pts = frame.pts
            await self._svc.push_frame(out)

    def on_event(self, event: STVEvent, **kwargs: object) -> None:
        pass  # lifecycle events are wired via the client's emitter (see _wire_events)


class OjinVideoService(FrameProcessor):
    """Pipecat FrameProcessor that turns the TTS audio stream into a lip-synced avatar."""

    def __init__(
        self,
        settings: OjinVideoSettings,
        *,
        session_trace: Optional[OjinSessionTrace] = None,
        stv_client: Optional[OjinSTVClient] = None,
    ) -> None:
        """Build the adapter and wire the client's lifecycle events.

        Args:
            settings: connection identity + avatar frame size.
            session_trace: an ``ojin.stv.OjinSessionTrace`` to record this call;
                injected as the client's tracer and dumped to disk on close.
                ``None`` -> the client uses a no-op tracer.
            stv_client: a pre-built client (dependency injection for tests or
                alternative transports). When given, ``settings`` connection
                fields are not used to build a client.
        """
        super().__init__(name="ojin-video")
        self._settings = settings
        self._can_start_playback = True  # gate open by default; close to defer A/V
        self._first_video_pushed = False  # one-shot: first real frame forwarded
        self._waiting_for_first_tts = False
        self._trace = session_trace
        self._output = _PushFrameOutput(self)
        self._stv = stv_client or OjinSTVClient(
            api_key=settings.api_key,
            config_id=settings.config_id,
            ws_url=settings.ws_url,
            output=self._output,
            tracer=session_trace,
            config=settings.stv_config,
            buffer_preinit_tts_audio=settings.buffer_preinit_tts_audio,
        )
        self._wire_events()

    def set_can_start_playback(self, value: bool) -> None:
        """Open (``True``) or close (``False``) the playback gate.

        Defaults open. Close it before participant join to keep the connect->join
        idle backlog out of the transport, then re-open at join.
        """
        self._can_start_playback = value

    def can_generate_metrics(self) -> bool:
        """Enable Pipecat TTFB / processing metrics for this service."""
        return True

    async def connect_with_retry(self) -> bool:
        """Connect the underlying client with retry; ``True`` on success."""
        return await self._stv.connect_with_retry()

    def _wire_events(self) -> None:
        """Map ``OjinSTVClient`` events onto Pipecat frames + TTFB metrics."""

        @self._stv.on(STVEvent.SESSION_READY)
        async def _on_ready(session_data=None, **_):
            frame = OjinVideoInitializedFrame(session_data=session_data)
            await self.push_frame(frame, FrameDirection.DOWNSTREAM)
            await self.push_frame(frame, FrameDirection.UPSTREAM)

        @self._stv.on(STVEvent.BOT_STARTED_SPEAKING)
        async def _on_started(**_):
            await self.push_frame(OjinBotStartedSpeakingFrame())
            await self.stop_ttfb_metrics()

        @self._stv.on(STVEvent.BOT_STOPPED_SPEAKING)
        async def _on_stopped(**_):
            await self.push_frame(OjinBotStoppedSpeakingFrame())

        @self._stv.on(STVEvent.ERROR)
        async def _on_error(message="", fatal=False, **_):
            await self.push_error(message, fatal=fatal)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Map each inbound Pipecat frame to the matching OjinSTVClient call."""
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
                # Drop the trailing-silence sentinel here, before arming TTFB: TTFB
                # must time the first *real* audio. It never reaches the client (which
                # would discard it too) and leaves TTFB un-armed for the next frame.
                return
            if self._waiting_for_first_tts:
                self._waiting_for_first_tts = False
                await self.start_ttfb_metrics()
            await self._stv.send_tts_audio(
                frame.audio, frame.sample_rate, frame.num_channels
            )
        elif isinstance(frame, InterruptionFrame):
            # Barge-in on the pipeline's GATED interruption signal only. InterruptionFrame is
            # broadcast solely when interruptions are actually allowed (e.g. DeepgramFlux
            # ``should_interrupt`` / a UserTurnStartStrategy's ``enable_interruptions``), so
            # honoring it here respects the configured interruption policy.
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

        Mirrors ``OjinSTVClient.send_tts_audio``'s discard rule so the adapter can
        drop it before arming TTFB metrics (which must time the first real audio).
        """
        pcm = frame.audio
        if not pcm or any(pcm):  # empty, or any non-zero byte -> real audio
            return False
        duration = len(pcm) / (frame.sample_rate * frame.num_channels * 2)
        return abs(duration - _HALF_SECOND) < _HALF_SECOND_TOL

    def _write_trace(self) -> None:
        """Dump the session's Perfetto trace to disk on close (best-effort, once)."""
        trace, self._trace = self._trace, None  # write at most once
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
        except Exception as exc:  # never let trace I/O break teardown
            logger.warning("Failed to write Ojin STV session trace: %s", exc)
