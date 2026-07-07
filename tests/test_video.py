"""Tests for the OjinVideoService adapter over ojin.stv.OjinSTVClient.

The adapter only (a) translates Pipecat frames into OjinSTVClient calls,
(b) implements the STVOutput sink (pushing Output*RawFrame downstream) behind
the playback-start gate, and (c) maps client events to Pipecat frames + TTFB
metrics. All avatar behaviour lives in ojin.stv and is tested there.
"""

import asyncio
import contextlib
import unittest
from unittest.mock import AsyncMock

import pytest
from ojin.stv import STVAudioFrame, STVEvent, STVVideoFrame
from ojin.stv.events import EventEmitter
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputImageRawFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipecat_ojin.video import (
    OjinBotStartedSpeakingFrame,
    OjinBotStoppedSpeakingFrame,
    OjinFirstVideoFrame,
    OjinVideoInitializedFrame,
    OjinVideoService,
    OjinVideoSettings,
)

try:
    from pipecat.tests.utils import run_test

    _HAS_RUN_TEST = True
except Exception:  # pragma: no cover - depends on pipecat packaging test utils
    _HAS_RUN_TEST = False


class FakeSTVClient:
    """Stand-in for OjinSTVClient.

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


def _audio() -> TTSAudioRawFrame:
    return TTSAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=24000, num_channels=1)


def _silence() -> TTSAudioRawFrame:
    # 0.5 s of all-zero PCM @ 24 kHz mono int16 == the client's trailing-silence
    # sentinel (24000 samples * 2 bytes = 24000 bytes => 0.5 s).
    return TTSAudioRawFrame(audio=b"\x00" * 24000, sample_rate=24000, num_channels=1)


def _adapter(fake: FakeSTVClient, **settings_kw) -> OjinVideoService:
    return OjinVideoService(OjinVideoSettings(**settings_kw), stv_client=fake)


class TestPlaybackGate(unittest.IsolatedAsyncioTestCase):
    """The gate lives in the adapter; default open, close to drop A/V."""

    async def test_open_by_default_forwards_audio_and_video(self) -> None:
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()
        await svc._output.write_audio(
            STVAudioFrame(pcm=b"\x02\x00", sample_rate=24000, num_channels=1, pts=0)
        )
        await svc._output.write_video(
            STVVideoFrame(
                rgb=b"rgbrgb",
                source_bytes=b"jpg",
                width=1,
                height=2,
                frame_type=1,
                pts=0,
            )
        )
        pushed = [c.args[0] for c in svc.push_frame.call_args_list]
        audio = [f for f in pushed if isinstance(f, OutputAudioRawFrame)]
        image = [f for f in pushed if isinstance(f, OutputImageRawFrame)]
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0].audio, b"\x02\x00")
        self.assertEqual(audio[0].sample_rate, 24000)
        self.assertEqual(audio[0].num_channels, 1)
        self.assertEqual(len(image), 1)
        self.assertEqual(image[0].image, b"rgbrgb")
        self.assertEqual(image[0].size, (1, 2))
        self.assertEqual(image[0].format, "RGB")

    async def test_video_frame_carries_client_pts(self) -> None:
        """The outgoing OutputImageRawFrame must carry the client's monotonic pts.

        Regression guard for the turn-boundary freeze: dropping the pts left the
        Daily video timeline unpinned (RTP stamped off Daily's own wall clock),
        so an encoder/SFU re-time surfaced as a multi-second media_time jump on
        the client. See notes/wiki/issues/30-06-2026/freeze_on_interruption.
        """
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()
        pts_ns = 1_234_567_890_123
        await svc._output.write_video(
            STVVideoFrame(
                rgb=b"rgbrgb",
                source_bytes=b"jpg",
                width=1,
                height=2,
                frame_type=1,
                pts=pts_ns,
            )
        )
        image = [
            c.args[0]
            for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OutputImageRawFrame)
        ]
        self.assertEqual(len(image), 1)
        self.assertEqual(image[0].pts, pts_ns)

    async def test_closed_gate_drops_audio_and_video(self) -> None:
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()
        svc.set_can_start_playback(False)
        await svc._output.write_audio(
            STVAudioFrame(pcm=b"\x01\x00", sample_rate=24000, num_channels=1, pts=0)
        )
        await svc._output.write_video(
            STVVideoFrame(
                rgb=b"rgb", source_bytes=b"jpg", width=4, height=4, frame_type=1, pts=0
            )
        )
        svc.push_frame.assert_not_called()

    async def test_open_but_no_rgb_drops_video(self) -> None:
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()
        await svc._output.write_video(
            STVVideoFrame(
                rgb=None, source_bytes=b"jpg", width=1, height=1, frame_type=0, pts=0
            )
        )
        svc.push_frame.assert_not_called()


class TestEventToFrameMapping(unittest.IsolatedAsyncioTestCase):
    """Client lifecycle events map to the Pipecat frames + TTFB the bot expects."""

    def _wired(self):
        fake = FakeSTVClient()
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

    async def test_error_event_without_code_kwarg(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.ERROR, message="connect failed", fatal=True)
        svc.push_error.assert_awaited_once()
        self.assertEqual(svc.push_error.call_args.args[0], "connect failed")


class TestFrameRouting(unittest.IsolatedAsyncioTestCase):
    """Inbound Pipecat frames route to the right client calls (mid-stream frames)."""

    def _svc(self, **kw):
        fake = FakeSTVClient()
        svc = _adapter(fake, **kw)
        svc.push_frame = AsyncMock()
        svc.start_ttfb_metrics = AsyncMock()
        return fake, svc

    async def test_tts_started_opens_turn(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("start_turn", fake.calls)

    async def test_tts_audio_sends_to_client_and_arms_ttfb_once(self) -> None:
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

    async def test_tts_audio_not_pushed_downstream(self) -> None:
        # The adapter never passes the TTS audio frame through; the client's
        # output sink emits the played audio instead.
        _fake, svc = self._svc()
        frame = _audio()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        pushed = [c.args[0] for c in svc.push_frame.call_args_list]
        self.assertNotIn(frame, pushed)

    async def test_interruption_frame_interrupts(self) -> None:
        # Barge-in fires on the pipeline's GATED InterruptionFrame — broadcast
        # only when interruptions are actually allowed — not on raw VAD.
        fake, svc = self._svc()
        await svc.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("interrupt", fake.calls)

    async def test_user_started_speaking_does_not_interrupt(self) -> None:
        # Regression guard: the adapter must NOT barge in on the unconditional
        # UserStartedSpeakingFrame (that ignored the interruption policy and cut
        # the avatar off mid-utterance). Only InterruptionFrame may interrupt.
        fake, svc = self._svc()
        await svc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertNotIn("interrupt", fake.calls)

    async def test_end_frame_closes_client(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("close", fake.calls)

    async def test_cancel_frame_closes_client(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("close", fake.calls)

    async def test_can_generate_metrics_is_true(self) -> None:
        _, svc = self._svc()
        self.assertTrue(svc.can_generate_metrics())


class TestTtfbAndSilence(unittest.IsolatedAsyncioTestCase):
    """TTFB arming honours the trailing-silence sentinel and re-arms per turn."""

    def _svc(self, **kw):
        fake = FakeSTVClient()
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


class TestClientDelegation(unittest.IsolatedAsyncioTestCase):
    """connect_with_retry delegates to the client."""

    async def test_connect_with_retry_delegates_and_returns_true(self) -> None:
        fake = FakeSTVClient()
        fake.connect_return = True
        svc = _adapter(fake)
        self.assertTrue(await svc.connect_with_retry())
        self.assertIn("connect_with_retry", fake.calls)

    async def test_connect_with_retry_propagates_false(self) -> None:
        fake = FakeSTVClient()
        fake.connect_return = False
        svc = _adapter(fake)
        self.assertFalse(await svc.connect_with_retry())


class TestFrameTransparency(unittest.IsolatedAsyncioTestCase):
    """Handled frames are still forwarded; unknown frames pass through."""

    def _svc(self, **kw):
        fake = FakeSTVClient()
        svc = _adapter(fake, **kw)
        svc.push_frame = AsyncMock()
        svc.start_ttfb_metrics = AsyncMock()
        return fake, svc

    def _pushed_args(self, svc):
        return [c.args for c in svc.push_frame.call_args_list]

    async def test_tts_started_forwarded_downstream(self) -> None:
        _fake, svc = self._svc()
        frame = TTSStartedFrame()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn((frame, FrameDirection.DOWNSTREAM), self._pushed_args(svc))

    async def test_unknown_frame_passes_through(self) -> None:
        _fake, svc = self._svc()
        frame = OutputAudioRawFrame(b"\x00\x00", 24000, 1)
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn((frame, FrameDirection.DOWNSTREAM), self._pushed_args(svc))


@unittest.skipUnless(_HAS_RUN_TEST, "pipecat.tests.utils.run_test not available")
class TestLifecycleThroughPipeline(unittest.IsolatedAsyncioTestCase):
    """End-to-end through a real pipeline: StartFrame -> start, EndFrame -> close."""

    async def test_start_starts_client_and_end_closes_it(self) -> None:
        fake = FakeSTVClient()
        svc = _adapter(fake)
        await run_test(
            svc,
            frames_to_send=[],
            expected_down_frames=None,
            send_end_frame=True,
        )
        self.assertIn("start", fake.calls)
        self.assertIn("close", fake.calls)


class TestStvConfigPassthrough(unittest.TestCase):
    """OjinVideoSettings.stv_config reaches the real OjinSTVClient.

    Construction is offline (no connect), so this exercises the production path
    where no ``stv_client`` is injected — the route that enables the otherwise
    off-by-default loop-stall diagnostics in deployment.
    """

    def test_config_forwarded_to_client(self) -> None:
        from ojin.stv import STVConfig

        cfg = STVConfig(stall_probe_ms=70.0, loop_stall_watchdog_ms=250.0)
        svc = OjinVideoService(OjinVideoSettings(stv_config=cfg))
        self.assertIs(svc._stv._config, cfg)
        self.assertEqual(svc._stv._config.stall_probe_ms, 70.0)
        self.assertEqual(svc._stv._config.loop_stall_watchdog_ms, 250.0)

    def test_default_leaves_watchdog_disabled(self) -> None:
        svc = OjinVideoService(OjinVideoSettings())
        # No config passed -> client builds STVConfig() defaults: diagnostics off.
        self.assertEqual(svc._stv._config.stall_probe_ms, 0.0)
        self.assertEqual(svc._stv._config.loop_stall_watchdog_ms, 0.0)


class TestFirstVideoFrameSignal(unittest.IsolatedAsyncioTestCase):
    """The adapter emits OjinFirstVideoFrame once, on the first real pushed frame."""

    async def test_first_real_frame_emits_once_both_directions(self) -> None:
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()

        # First real frame (rgb set) → one OjinFirstVideoFrame per direction.
        await svc._output.write_video(
            STVVideoFrame(
                rgb=b"rgb", source_bytes=b"jpg", width=2, height=2, frame_type=0, pts=0
            )
        )
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

        # Subsequent frames must NOT emit another OjinFirstVideoFrame.
        svc.push_frame.reset_mock()
        await svc._output.write_video(
            STVVideoFrame(
                rgb=b"rgb2", source_bytes=b"jpg", width=2, height=2, frame_type=1, pts=1
            )
        )
        again = [
            c
            for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OjinFirstVideoFrame)
        ]
        self.assertEqual(len(again), 0)

    async def test_no_signal_while_gate_closed(self) -> None:
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()
        svc.set_can_start_playback(False)
        await svc._output.write_video(
            STVVideoFrame(
                rgb=b"rgb", source_bytes=b"jpg", width=2, height=2, frame_type=0, pts=0
            )
        )
        firsts = [
            c
            for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OjinFirstVideoFrame)
        ]
        self.assertEqual(len(firsts), 0)


class _PlaybackSTVClient(FakeSTVClient):
    """FakeSTVClient that simulates real playback: after receiving an utterance's
    audio it fires BOT_STARTED_SPEAKING, then BOT_STOPPED_SPEAKING once "played" —
    exactly the events the real client emits when its buffer promotes and drains."""

    def __init__(self) -> None:
        super().__init__()
        self._playback_tasks: list = []

    async def send_tts_audio(self, pcm, sample_rate, num_channels) -> None:
        await super().send_tts_audio(pcm, sample_rate, num_channels)
        self._playback_tasks.append(asyncio.create_task(self._play()))

    async def _play(self) -> None:
        # Small delay so the TTS service's post-utterance pause engages BEFORE the
        # playback-finished event arrives — the real ordering (playback lags synthesis).
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
    This test runs a REAL Pipeline (real TTSService pause semantics, real
    OjinVideoService) and asserts the SECOND utterance is actually synthesized —
    i.e. the frame is delivered, not merely created. Before the fix this test
    deadlocks on the paused TTS (caught by the timeout).
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

        fake = _PlaybackSTVClient()
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
