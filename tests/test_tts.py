"""Tests for the OjinTTSService port.

Exercises construction and the not-connected path without a real WebSocket by
injecting a fake low-level client whose connect() always fails.
"""

import unittest

from pipecat.frames.frames import ErrorFrame

from pipecat_ojin.tts import OjinTTSService, OjinTTSServiceSettings


class _FailingClient:
    """Fake IOjinClient that never connects (no network in tests)."""

    async def connect(self) -> None:
        raise ConnectionError("test: refusing to connect")

    def is_connected(self) -> bool:
        return False

    async def close(self) -> None:
        pass


def _service() -> OjinTTSService:
    # retries=1 / delay=0 keeps connect_with_retry fast in the test.
    settings = OjinTTSServiceSettings(
        api_key="k",
        config_id="c",
        client_connect_max_retries=1,
        client_reconnect_delay=0.0,
    )
    return OjinTTSService(settings, client=_FailingClient())


class TestOjinTTSService(unittest.IsolatedAsyncioTestCase):
    def test_can_generate_metrics_is_true(self) -> None:
        self.assertTrue(_service().can_generate_metrics())

    async def test_connect_with_retry_returns_false_when_unreachable(self) -> None:
        self.assertFalse(await _service().connect_with_retry())

    async def test_run_tts_yields_error_frame_when_not_connected(self) -> None:
        svc = _service()
        frames = [frame async for frame in svc.run_tts("hello")]
        self.assertTrue(any(isinstance(f, ErrorFrame) for f in frames))
