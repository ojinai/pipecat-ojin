"""Tests for the OjinSTVWebRTCService adapter over ojin.stv.OjinSTVWebRTCClient.

In direct-WebRTC mode the inference server publishes the avatar's A/V into the
room itself, so this adapter only (a) translates Pipecat frames into client
calls and (b) maps client lifecycle events (derived from the server's metadata
frames) to Pipecat frames + TTFB metrics. It must never push audio or video
frames downstream. Negotiation/clock/event derivation lives in ojin.stv and is
tested there.
"""

import asyncio
import contextlib
import unittest
from unittest.mock import AsyncMock

import pytest
from ojin.stv import STVEvent, WebRTCSettings
from ojin.stv.events import EventEmitter
from ojin.stv.ojin_stv_webrtc_client import WEBRTC_JOIN_FAILED
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputImageRawFrame,
    TextFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipecat_ojin.stv_webrtc import OjinSTVWebRTCService
from pipecat_ojin.video import (
    OjinBotStartedSpeakingFrame,
    OjinBotStoppedSpeakingFrame,
    OjinFirstVideoFrame,
    OjinVideoInitializedFrame,
    OjinVideoSettings,
)

try:
    from pipecat.tests.utils import run_test

    _HAS_RUN_TEST = True
except Exception:  # pragma: no cover - depends on pipecat packaging test utils
    _HAS_RUN_TEST = False


class FakeSTVWebRTCClient:
    """Stand-in for OjinSTVWebRTCClient.

    Records adapter->client calls and uses the real EventEmitter so the adapter's
    event wiring runs against production dispatch logic.
    """

    def __init__(self) -> None:
        self._events = EventEmitter()
        self.calls: list = []
        self.connect_return = True

    def on(self, event):
        return self._events.on(event)

    def add_listener(self, event, cb) -> None:
        self._events.add_listener(event, cb)

    async def emit(self, event, **kwargs) -> None:
        await self._events.emit(event, **kwargs)

    async def start(self) -> None:
        self.calls.append("start")

    async def start_turn(self) -> None:
        self.calls.append("start_turn")

    async def send_tts_audio(self, pcm, sample_rate, num_channels) -> None:
        self.calls.append(("send_tts_audio", pcm, sample_rate, num_channels))

    async def interrupt(self) -> None:
        self.calls.append("interrupt")

    async def close(self) -> None:
        self.calls.append("close")

    async def connect_with_retry(self) -> bool:
        self.calls.append("connect_with_retry")
        return self.connect_return


class FakeSessionTrace:
    """Records dump calls so tests can assert the trace is written exactly once."""

    def __init__(self, raise_on_dump: bool = False) -> None:
        self.session_id = "test-session"
        self.dump_paths: list[str] = []
        self._raise_on_dump = raise_on_dump

    def dump(self, path: str) -> str:
        if self._raise_on_dump:
            raise OSError("disk full")
        self.dump_paths.append(path)
        return path


def _audio() -> TTSAudioRawFrame:
    return TTSAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=24000, num_channels=1)


def _silence() -> TTSAudioRawFrame:
    # 0.5 s of all-zero PCM @ 24 kHz mono int16 == the client's trailing-silence
    # sentinel (24000 samples * 2 bytes = 24000 bytes => 0.5 s).
    return TTSAudioRawFrame(audio=b"\x00" * 24000, sample_rate=24000, num_channels=1)


def _webrtc_settings() -> WebRTCSettings:
    return WebRTCSettings(room_url="https://example.daily.co/room", token="secret")


def _adapter(
    fake: FakeSTVWebRTCClient, *, session_trace=None, **settings_kw
) -> OjinSTVWebRTCService:
    return OjinSTVWebRTCService(
        OjinVideoSettings(**settings_kw),
        _webrtc_settings(),
        session_trace=session_trace,
        stv_client=fake,
    )


class TestAdapterShape(unittest.IsolatedAsyncioTestCase):
    """The bot-facing surface: `_stv` attribute, no `_output`, no-op gate, metrics."""

    async def test_exposes_client_as_stv(self) -> None:
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake)
        self.assertIs(svc._stv, fake)

    async def test_defines_no_output_attribute(self) -> None:
        # The bot's netstats probe distinguishes the services via
        # getattr(avatar, "_output", None) — this adapter must not define one.
        svc = _adapter(FakeSTVWebRTCClient())
        self.assertFalse(hasattr(svc, "_output"))

    async def test_set_can_start_playback_is_callable_no_op(self) -> None:
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake)
        svc.push_frame = AsyncMock()
        self.assertIsNone(svc.set_can_start_playback(False))
        self.assertIsNone(svc.set_can_start_playback(True))
        svc.push_frame.assert_not_called()

    async def test_no_op_gate_does_not_suppress_events(self) -> None:
        # Unlike OjinVideoService's real gate, closing this one changes nothing:
        # there is no media here, so lifecycle events keep flowing.
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake)
        svc.push_frame = AsyncMock()
        svc.set_can_start_playback(False)
        await fake.emit(STVEvent.FIRST_FRAME, frame_type=0)
        firsts = [
            c
            for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OjinFirstVideoFrame)
        ]
        self.assertEqual(len(firsts), 2)

    async def test_can_generate_metrics_is_true(self) -> None:
        svc = _adapter(FakeSTVWebRTCClient())
        self.assertTrue(svc.can_generate_metrics())


class TestEventToFrameMapping(unittest.IsolatedAsyncioTestCase):
    """Client lifecycle events map to the Pipecat frames + TTFB the bot expects."""

    def _wired(self):
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake)
        svc.push_frame = AsyncMock()
        svc.push_error = AsyncMock()
        svc.start_ttfb_metrics = AsyncMock()
        svc.stop_ttfb_metrics = AsyncMock()
        return fake, svc

    async def test_session_ready_pushes_initialized_frame_both_directions(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.SESSION_READY, session_data={"foo": 1})
        init = [
            c
            for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OjinVideoInitializedFrame)
        ]
        self.assertEqual(len(init), 2)
        self.assertEqual(init[0].args[0].session_data, {"foo": 1})
        dirs = {c.args[1] for c in init}
        self.assertEqual(dirs, {FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM})

    async def test_first_frame_pushes_first_video_frame_both_directions(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.FIRST_FRAME, frame_type=0)
        firsts = [
            c
            for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OjinFirstVideoFrame)
        ]
        self.assertEqual(len(firsts), 2)
        self.assertEqual(
            {c.args[1] for c in firsts},
            {FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM},
        )

    async def test_first_frame_is_one_shot(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.FIRST_FRAME, frame_type=0)
        svc.push_frame.reset_mock()
        await fake.emit(STVEvent.FIRST_FRAME, frame_type=1)
        firsts = [
            c
            for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OjinFirstVideoFrame)
        ]
        self.assertEqual(len(firsts), 0)

    async def test_started_speaking_emits_custom_plus_stock_both_directions(
        self,
    ) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.BOT_STARTED_SPEAKING)
        pushed = [type(c.args[0]) for c in svc.push_frame.call_args_list]
        self.assertIn(OjinBotStartedSpeakingFrame, pushed)
        # Stock boundary frames mirror BaseOutputTransport (which never fires in an
        # Ojin pipeline because the avatar consumes TTSAudioRawFrame): one per direction.
        stock = [
            c
            for c in svc.push_frame.call_args_list
            if type(c.args[0]) is BotStartedSpeakingFrame
        ]
        self.assertEqual(len(stock), 2)
        self.assertEqual(
            {c.args[1] for c in stock},
            {FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM},
        )
        svc.stop_ttfb_metrics.assert_awaited_once()

    async def test_stopped_speaking_emits_custom_plus_stock_both_directions(
        self,
    ) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.BOT_STOPPED_SPEAKING)
        pushed = [type(c.args[0]) for c in svc.push_frame.call_args_list]
        self.assertIn(OjinBotStoppedSpeakingFrame, pushed)
        stock = [
            c
            for c in svc.push_frame.call_args_list
            if type(c.args[0]) is BotStoppedSpeakingFrame
        ]
        self.assertEqual(len(stock), 2)
        self.assertEqual(
            {c.args[1] for c in stock},
            {FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM},
        )

    async def test_error_event_pushes_error_with_message_and_fatal(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.ERROR, message="boom", code="X", fatal=True)
        svc.push_error.assert_awaited_once()
        call = svc.push_error.call_args
        self.assertEqual(call.args[0], "boom")
        self.assertTrue(call.kwargs.get("fatal"))

    async def test_relay_fallback_is_not_an_error(self) -> None:
        """Protocol v2: sessionReady without a webrtc result = graceful relay
        fallback. The client emits no ERROR (v1's fatal WEBRTC_UNSUPPORTED is
        gone from the SDK), so the session proceeds normally."""
        fake, svc = self._wired()
        await fake.emit(STVEvent.SESSION_READY, session_data={"p": 1})
        await fake.emit(STVEvent.FIRST_FRAME, frame_type=0)
        svc.push_error.assert_not_awaited()

    async def test_webrtc_join_failed_error_is_fatal(self) -> None:
        fake, svc = self._wired()
        await fake.emit(
            STVEvent.ERROR,
            message="No terminal webrtcStatus within 10.0 s",
            code=WEBRTC_JOIN_FAILED,
            fatal=True,
        )
        svc.push_error.assert_awaited_once()
        self.assertTrue(svc.push_error.call_args.kwargs.get("fatal"))

    async def test_non_fatal_error_passes_fatal_false(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.ERROR, message="transient", fatal=False)
        svc.push_error.assert_awaited_once()
        self.assertFalse(svc.push_error.call_args.kwargs.get("fatal"))


class TestNoAVOutput(unittest.IsolatedAsyncioTestCase):
    """The invariant: this adapter never pushes Output*RawFrame, for any input."""

    async def test_full_session_script_pushes_no_av_frames(self) -> None:
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake, session_trace=FakeSessionTrace())
        svc.push_frame = AsyncMock()
        svc.push_error = AsyncMock()
        svc.start_ttfb_metrics = AsyncMock()
        svc.stop_ttfb_metrics = AsyncMock()

        await fake.emit(STVEvent.SESSION_READY, session_data={"p": 1})
        await fake.emit(STVEvent.WEBRTC_CONNECTED, participant_id="abc")
        await fake.emit(STVEvent.FIRST_FRAME, frame_type=0)
        await svc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        await svc.process_frame(_silence(), FrameDirection.DOWNSTREAM)
        await svc.process_frame(_audio(), FrameDirection.DOWNSTREAM)
        await fake.emit(STVEvent.BOT_STARTED_SPEAKING)
        await fake.emit(STVEvent.BOT_STOPPED_SPEAKING)
        await svc.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        await fake.emit(STVEvent.INTERRUPTED)
        await svc.process_frame(TextFrame("hi"), FrameDirection.DOWNSTREAM)
        await svc.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)
        await fake.emit(STVEvent.CLOSED)

        pushed = [c.args[0] for c in svc.push_frame.call_args_list]
        self.assertTrue(pushed)  # the script did push lifecycle/passthrough frames
        av = [
            f
            for f in pushed
            if isinstance(f, (OutputAudioRawFrame, OutputImageRawFrame))
        ]
        self.assertEqual(av, [])


class TestFrameRouting(unittest.IsolatedAsyncioTestCase):
    """Inbound Pipecat frames route to the right client calls (mid-stream frames)."""

    def _svc(self, **kw):
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake, **kw)
        svc.push_frame = AsyncMock()
        svc.start_ttfb_metrics = AsyncMock()
        return fake, svc

    async def test_tts_started_opens_turn(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("start_turn", fake.calls)

    async def test_tts_audio_forwarded_native_rate_and_arms_ttfb_once(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        first = _audio()
        await svc.process_frame(first, FrameDirection.DOWNSTREAM)
        await svc.process_frame(_audio(), FrameDirection.DOWNSTREAM)
        sends = [
            c for c in fake.calls if isinstance(c, tuple) and c[0] == "send_tts_audio"
        ]
        self.assertEqual(len(sends), 2)
        self.assertEqual(
            sends[0],
            ("send_tts_audio", first.audio, first.sample_rate, first.num_channels),
        )
        svc.start_ttfb_metrics.assert_awaited_once()

    async def test_tts_audio_consumed_never_pushed(self) -> None:
        _fake, svc = self._svc()
        frame = _audio()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        pushed = [c.args[0] for c in svc.push_frame.call_args_list]
        self.assertNotIn(frame, pushed)

    async def test_interruption_frame_interrupts_and_passes_through(self) -> None:
        fake, svc = self._svc()
        frame = InterruptionFrame()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn("interrupt", fake.calls)
        self.assertIn(
            (frame, FrameDirection.DOWNSTREAM),
            [c.args for c in svc.push_frame.call_args_list],
        )

    async def test_user_started_speaking_does_not_interrupt(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertNotIn("interrupt", fake.calls)

    async def test_end_frame_closes_client_and_passes_through(self) -> None:
        fake, svc = self._svc()
        frame = EndFrame()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn("close", fake.calls)
        self.assertIn(
            (frame, FrameDirection.DOWNSTREAM),
            [c.args for c in svc.push_frame.call_args_list],
        )

    async def test_cancel_frame_closes_client_and_passes_through(self) -> None:
        fake, svc = self._svc()
        frame = CancelFrame()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn("close", fake.calls)
        self.assertIn(
            (frame, FrameDirection.DOWNSTREAM),
            [c.args for c in svc.push_frame.call_args_list],
        )

    async def test_tts_started_forwarded_downstream(self) -> None:
        _fake, svc = self._svc()
        frame = TTSStartedFrame()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn(
            (frame, FrameDirection.DOWNSTREAM),
            [c.args for c in svc.push_frame.call_args_list],
        )

    async def test_unknown_frame_passes_through(self) -> None:
        _fake, svc = self._svc()
        frame = TextFrame("hello")
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn(
            (frame, FrameDirection.DOWNSTREAM),
            [c.args for c in svc.push_frame.call_args_list],
        )


class TestTtfbAndSilence(unittest.IsolatedAsyncioTestCase):
    """TTFB arming honours the trailing-silence sentinel and re-arms per turn."""

    def _svc(self, **kw):
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake, **kw)
        svc.push_frame = AsyncMock()
        svc.start_ttfb_metrics = AsyncMock()
        return fake, svc

    async def test_trailing_silence_first_frame_is_dropped_not_armed(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        await svc.process_frame(_silence(), FrameDirection.DOWNSTREAM)
        svc.start_ttfb_metrics.assert_not_awaited()
        self.assertNotIn(
            "send_tts_audio", [c[0] for c in fake.calls if isinstance(c, tuple)]
        )
        # the real first frame that follows still arms TTFB once
        await svc.process_frame(_audio(), FrameDirection.DOWNSTREAM)
        svc.start_ttfb_metrics.assert_awaited_once()

    async def test_ttfb_not_armed_without_a_tts_started_frame(self) -> None:
        _, svc = self._svc()
        await svc.process_frame(_audio(), FrameDirection.DOWNSTREAM)
        svc.start_ttfb_metrics.assert_not_awaited()

    async def test_ttfb_rearmed_on_each_turn(self) -> None:
        _, svc = self._svc()
        for _turn in range(2):
            await svc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
            await svc.process_frame(_audio(), FrameDirection.DOWNSTREAM)
        self.assertEqual(svc.start_ttfb_metrics.await_count, 2)

    async def test_bot_started_speaking_stops_ttfb(self) -> None:
        fake, svc = self._svc()
        svc.stop_ttfb_metrics = AsyncMock()
        await svc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        await svc.process_frame(_audio(), FrameDirection.DOWNSTREAM)
        await fake.emit(STVEvent.BOT_STARTED_SPEAKING)
        svc.stop_ttfb_metrics.assert_awaited_once()


class TestTraceWriting(unittest.IsolatedAsyncioTestCase):
    """End/CancelFrame write the session trace exactly once, best-effort."""

    def _svc(self, trace):
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake, session_trace=trace)
        svc.push_frame = AsyncMock()
        return fake, svc

    async def test_end_frame_writes_trace(self) -> None:
        trace = FakeSessionTrace()
        _fake, svc = self._svc(trace)
        await svc.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(trace.dump_paths), 1)
        self.assertIn(trace.session_id, trace.dump_paths[0])

    async def test_cancel_frame_writes_trace(self) -> None:
        trace = FakeSessionTrace()
        _fake, svc = self._svc(trace)
        await svc.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(trace.dump_paths), 1)

    async def test_trace_written_at_most_once(self) -> None:
        trace = FakeSessionTrace()
        _fake, svc = self._svc(trace)
        await svc.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)
        await svc.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(trace.dump_paths), 1)

    async def test_trace_dump_failure_does_not_break_teardown(self) -> None:
        trace = FakeSessionTrace(raise_on_dump=True)
        fake, svc = self._svc(trace)
        frame = EndFrame()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn("close", fake.calls)
        self.assertIn(
            (frame, FrameDirection.DOWNSTREAM),
            [c.args for c in svc.push_frame.call_args_list],
        )


class TestClientDelegation(unittest.IsolatedAsyncioTestCase):
    """connect_with_retry delegates to the client."""

    async def test_connect_with_retry_delegates_and_returns_true(self) -> None:
        fake = FakeSTVWebRTCClient()
        fake.connect_return = True
        svc = _adapter(fake)
        self.assertTrue(await svc.connect_with_retry())
        self.assertIn("connect_with_retry", fake.calls)

    async def test_connect_with_retry_propagates_false(self) -> None:
        fake = FakeSTVWebRTCClient()
        fake.connect_return = False
        svc = _adapter(fake)
        self.assertFalse(await svc.connect_with_retry())


@unittest.skipUnless(_HAS_RUN_TEST, "pipecat.tests.utils.run_test not available")
class TestLifecycleThroughPipeline(unittest.IsolatedAsyncioTestCase):
    """End-to-end through a real pipeline: StartFrame -> start, EndFrame -> close."""

    async def test_start_starts_client_and_end_closes_it(self) -> None:
        fake = FakeSTVWebRTCClient()
        svc = _adapter(fake)
        await run_test(
            svc,
            frames_to_send=[],
            expected_down_frames=None,
            send_end_frame=True,
        )
        self.assertIn("start", fake.calls)
        self.assertIn("close", fake.calls)


class _MetadataPlaybackSTVWebRTCClient(FakeSTVWebRTCClient):
    """FakeSTVWebRTCClient that simulates the metadata-driven speaking edges: after
    receiving an utterance's audio it fires BOT_STARTED_SPEAKING, then
    BOT_STOPPED_SPEAKING once the published turn drains — exactly the events the
    real client derives from the server's SPEECH->IDLE metadata frame transitions."""

    def __init__(self) -> None:
        super().__init__()
        self._playback_tasks: list = []

    async def send_tts_audio(self, pcm, sample_rate, num_channels) -> None:
        await super().send_tts_audio(pcm, sample_rate, num_channels)
        self._playback_tasks.append(asyncio.create_task(self._play()))

    async def _play(self) -> None:
        # Small delay so the TTS service's post-utterance pause engages BEFORE the
        # speaking-stopped event arrives — the real ordering (the server's published
        # playback lags synthesis).
        await asyncio.sleep(0.1)
        await self.emit(STVEvent.BOT_STARTED_SPEAKING)
        await asyncio.sleep(0.05)
        await self.emit(STVEvent.BOT_STOPPED_SPEAKING)


@pytest.mark.timeout(30, method="thread")
class TestPausedTTSResume(unittest.IsolatedAsyncioTestCase):
    """DELIVERY-level regression test for the paused-TTS deadlock (2026-07-02).

    TTS services with ``pause_frame_processing=True`` (e.g. ElevenLabs) pause their
    own frame processing after every utterance and resume ONLY on the stock
    ``BotStoppedSpeakingFrame`` — which stock pipelines get from the output
    transport, but Ojin pipelines do not (the avatar consumes ``TTSAudioRawFrame``).
    In direct-WebRTC mode there is no local playback at all, so the stock frames
    can only come from this adapter's metadata-derived speaking events. This test
    runs a REAL Pipeline and asserts the SECOND utterance is actually synthesized.
    """

    async def test_second_utterance_synthesizes_after_avatar_playback(self) -> None:
        from pipecat.frames.frames import TTSSpeakFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.services.tts_service import TTSService

        class PausingTTS(TTSService):
            """Minimal TTS with ElevenLabs-style pause-after-utterance semantics."""

            def __init__(self) -> None:
                super().__init__(pause_frame_processing=True, sample_rate=16000)
                self.spoken: list[str] = []

            async def run_tts(self, text: str, context_id: str):
                self.spoken.append(text)
                yield TTSAudioRawFrame(
                    audio=b"\x01\x00" * 320, sample_rate=16000, num_channels=1
                )

        fake = _MetadataPlaybackSTVWebRTCClient()
        tts = PausingTTS()
        svc = _adapter(fake)
        pipeline = Pipeline([tts, svc])
        task = PipelineTask(
            pipeline, params=PipelineParams(audio_out_sample_rate=16000)
        )
        await task.queue_frames(
            [TTSSpeakFrame("one"), TTSSpeakFrame("two"), EndFrame()]
        )
        runner = PipelineRunner(handle_sigint=False)
        run = asyncio.get_running_loop().create_task(runner.run(task))
        done, _ = await asyncio.wait({run}, timeout=10)
        if not done:  # pragma: no cover - the regression itself
            # Do NOT await task.cancel() here: with the resume missing, the pipeline
            # can wedge even during teardown (observed live 2026-07-02). Cancel the
            # runner future best-effort and fail loudly instead of hanging CI.
            run.cancel()
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(run, timeout=5)
            self.fail(
                "pipeline deadlocked: the TTS paused after utterance 1 and never "
                "resumed — the avatar must emit the stock BotStoppedSpeakingFrame "
                f"upstream at playback end (spoken so far: {tts.spoken})"
            )
        self.assertEqual(tts.spoken, ["one", "two"])


if __name__ == "__main__":
    unittest.main()
