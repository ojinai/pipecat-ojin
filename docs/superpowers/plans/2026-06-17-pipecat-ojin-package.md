# pipecat-ojin Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fresh, standalone `pipecat-ojin` Python package that provides Ojin's Pipecat integration (`OjinVideoService` avatar face + `OjinTTSService`) on top of upstream `pipecat-ai` + `ojin-client[stv]`, plus a runnable example agent.

**Architecture:** A thin `src/`-layout package. `OjinVideoService` is a Pipecat `FrameProcessor` that maps Pipecat frames onto `ojin.stv.OjinSTVClient` (all avatar behaviour lives in the SDK client). `OjinTTSService` is a Pipecat `TTSService` over the SDK's low-level `ojin.ojin_client.OjinClient`. Session tracing is consumed directly from `ojin.stv` — the package ships no tracing module. The package is not a fork of Pipecat.

**Tech Stack:** Python ≥3.10, `pipecat-ai` ≥1.3.0, `ojin-client[stv]` ≥0.6.7, `pydantic` ≥2, setuptools build backend, pytest + `unittest.IsolatedAsyncioTestCase` for tests, ruff for lint/format.

## Global Constraints

These apply to every task; copy values verbatim.

- **Repo / branch:** work in `/home/ubuntu/pipecat-ojin` on branch `feat/initial-pipecat-ojin-package`. NEVER commit to `main`.
- **Package name:** distribution `pipecat-ojin`; import package `pipecat_ojin`; `__version__ = "0.1.0"`.
- **Python:** `requires-python = ">=3.10"`.
- **Core dependencies:** `pipecat-ai>=1.3.0`, `ojin-client[stv]>=0.6.7`, `pydantic>=2,<3`.
- **License:** Apache-2.0 — keep the existing `/home/ubuntu/pipecat-ojin/LICENSE` (do not replace it).
- **WebSocket URL default:** `wss://models.ojin.ai/realtime` (both services).
- **Tracing:** NO tracing module in this package. `OjinSessionTrace` is imported from `ojin.stv` and is NOT re-exported by `pipecat_ojin`.
- **Playback gate:** `OjinVideoService.set_can_start_playback` defaults **open** (`_can_start_playback = True`).
- **Config surface:** constructors take encapsulated settings objects (`OjinVideoSettings`, `OjinTTSServiceSettings`), not many bare kwargs.
- **Out of scope:** PyPI publish CI workflow; migrating `demo-modal-agents`; touching the legacy fork or python-sdk.
- **Example directory:** `examples/ojin-bot/`.
- **Local dev prerequisite:** `ojin-client` may not be on PyPI yet. Before installing this package editable, install the local SDK editable so pip can satisfy the dependency: `pip install -e "/home/ubuntu/python-sdk[stv]"`. (Once `ojin-client` is on PyPI this step is unnecessary.)

---

### Task 1: Package skeleton — buildable + importable

Creates the package metadata, an importable `pipecat_ojin` package exposing only `__version__` (modules land in Tasks 2–3), the dev tooling config, and a smoke test proving install + import.

**Files:**
- Create: `pyproject.toml`
- Create: `src/pipecat_ojin/__init__.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_smoke.py`
- Create: `CHANGELOG.md`
- Create: `.gitignore` is already present — do NOT recreate it.

**Interfaces:**
- Produces: importable package `pipecat_ojin` with attribute `__version__ == "0.1.0"`.

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_smoke.py`:

```python
"""Smoke test: the package installs and imports with the expected version."""


def test_package_imports_with_version():
    import pipecat_ojin

    assert pipecat_ojin.__version__ == "0.1.0"
```

Create empty `tests/__init__.py`:

```python
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/ubuntu/pipecat-ojin && python -m pytest tests/test_smoke.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'pipecat_ojin'`.

- [ ] **Step 3: Create the package metadata**

Create `pyproject.toml`:

```toml
[project]
name = "pipecat-ojin"
version = "0.1.0"
description = "Ojin avatar (Speech-To-Video) and TTS services for Pipecat"
readme = "README.md"
requires-python = ">=3.10"
authors = [{ name = "Journee" }]
license = { text = "Apache-2.0" }
classifiers = [
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Topic :: Multimedia :: Sound/Audio",
    "Topic :: Multimedia :: Video",
]
dependencies = [
    "pipecat-ai>=1.3.0",
    "ojin-client[stv]>=0.6.7",
    "pydantic>=2,<3",
]

[build-system]
requires = ["setuptools>=42", "wheel"]
build-backend = "setuptools.build_meta"

[project.urls]
Homepage = "https://ojin.ai"
Repository = "https://github.com/ojinai/pipecat-ojin"
Documentation = "https://docs.ojin.ai"
Issues = "https://github.com/ojinai/pipecat-ojin/issues"

[project.optional-dependencies]
dev = [
    "pytest>=8.3.5",
    "pytest-asyncio>=0.26.0",
    "ruff>=0.11.4",
    "build>=0.10.0",
]

[tool.setuptools]
package-dir = { "" = "src" }
packages = ["pipecat_ojin"]

[tool.ruff]
target-version = "py310"
lint.select = ["E", "F", "I", "B", "SIM", "RUF"]
lint.ignore = ["E501"]

[tool.ruff.lint.isort]
known-first-party = ["pipecat_ojin"]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "auto"
```

Create `src/pipecat_ojin/__init__.py`:

```python
"""pipecat-ojin: Ojin avatar (Speech-To-Video) and TTS services for Pipecat."""

__version__ = "0.1.0"
```

Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to `pipecat-ojin` are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-17

Initial release. Standalone Pipecat integration for Ojin, built on upstream
`pipecat-ai` and `ojin-client[stv]`.
```

- [ ] **Step 4: Install the package (editable) and its dev extras**

Run:
```bash
cd /home/ubuntu/pipecat-ojin
pip install -e "/home/ubuntu/python-sdk[stv]"   # local SDK until ojin-client is on PyPI
pip install -e ".[dev]"
```
Expected: both installs succeed; `pip show pipecat-ojin` reports version `0.1.0`.

- [ ] **Step 5: Run the smoke test to verify it passes**

Run: `cd /home/ubuntu/pipecat-ojin && python -m pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
cd /home/ubuntu/pipecat-ojin
git add pyproject.toml src/pipecat_ojin/__init__.py tests/__init__.py tests/test_smoke.py CHANGELOG.md
git commit -m "feat: scaffold pipecat-ojin package skeleton"
```

---

### Task 2: `OjinVideoService` — the avatar face

The core adapter: a `FrameProcessor` mapping Pipecat frames onto `ojin.stv.OjinSTVClient`, with the playback-start gate, lifecycle-event → frame mapping, TTFB metrics, and per-session trace dump on close. Test approach is adapted from the legacy fork's proven `test_ojin_video_adapter.py` (a `FakeSTVClient` using the SDK's real `EventEmitter`).

**Files:**
- Create: `src/pipecat_ojin/video.py`
- Create: `tests/test_video.py`
- Modify: `src/pipecat_ojin/__init__.py`

**Interfaces:**
- Consumes: `ojin.stv.{OjinSTVClient, OjinSessionTrace, STVAudioFrame, STVVideoFrame, STVEvent}`; `pipecat.frames.frames.*`; `pipecat.processors.frame_processor.{FrameDirection, FrameProcessor}`.
- Produces:
  - `OjinVideoSettings(api_key="", config_id="", image_size=(512, 512), ws_url="wss://models.ojin.ai/realtime")` — dataclass.
  - `OjinVideoService(settings: OjinVideoSettings, *, session_trace: OjinSessionTrace | None = None, stv_client: OjinSTVClient | None = None)`.
    - `.set_can_start_playback(value: bool) -> None`
    - `.can_generate_metrics() -> bool`
    - `async .connect_with_retry() -> bool`
    - `async .process_frame(frame, direction) -> None`
  - Frames: `OjinVideoInitializedFrame(session_data=None)`, `OjinBotStartedSpeakingFrame`, `OjinBotStoppedSpeakingFrame`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_video.py`:

```python
"""Tests for the OjinVideoService adapter over ojin.stv.OjinSTVClient.

The adapter only (a) translates Pipecat frames into OjinSTVClient calls,
(b) implements the STVOutput sink (pushing Output*RawFrame downstream) behind
the playback-start gate, and (c) maps client events to Pipecat frames + TTFB
metrics. All avatar behaviour lives in ojin.stv and is tested there.
"""

import unittest
from unittest.mock import AsyncMock

from ojin.stv import STVAudioFrame, STVEvent, STVVideoFrame
from ojin.stv.events import EventEmitter

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
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
                rgb=b"rgbrgb", source_bytes=b"jpg", width=1, height=2, frame_type=1, pts=0
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

    async def test_closed_gate_drops_audio_and_video(self) -> None:
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()
        svc.set_can_start_playback(False)
        await svc._output.write_audio(
            STVAudioFrame(pcm=b"\x01\x00", sample_rate=24000, num_channels=1, pts=0)
        )
        await svc._output.write_video(
            STVVideoFrame(rgb=b"rgb", source_bytes=b"jpg", width=4, height=4, frame_type=1, pts=0)
        )
        svc.push_frame.assert_not_called()

    async def test_open_but_no_rgb_drops_video(self) -> None:
        svc = _adapter(FakeSTVClient())
        svc.push_frame = AsyncMock()
        await svc._output.write_video(
            STVVideoFrame(rgb=None, source_bytes=b"jpg", width=1, height=1, frame_type=0, pts=0)
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
            c for c in svc.push_frame.call_args_list
            if isinstance(c.args[0], OjinVideoInitializedFrame)
        ]
        self.assertEqual(len(init), 2)
        self.assertEqual(init[0].args[0].session_data, {"foo": 1})
        dirs = {c.args[1] for c in init}
        self.assertEqual(dirs, {FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM})

    async def test_started_speaking_emits_frame_and_stops_ttfb(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.BOT_STARTED_SPEAKING)
        pushed = [type(c.args[0]) for c in svc.push_frame.call_args_list]
        self.assertIn(OjinBotStartedSpeakingFrame, pushed)
        svc.stop_ttfb_metrics.assert_awaited_once()

    async def test_stopped_speaking_emits_frame(self) -> None:
        fake, svc = self._wired()
        await fake.emit(STVEvent.BOT_STOPPED_SPEAKING)
        pushed = [type(c.args[0]) for c in svc.push_frame.call_args_list]
        self.assertIn(OjinBotStoppedSpeakingFrame, pushed)

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
        sends = [c for c in fake.calls if isinstance(c, tuple) and c[0] == "send_tts_audio"]
        self.assertEqual(len(sends), 2)
        self.assertEqual(
            sends[0], ("send_tts_audio", first.audio, first.sample_rate, first.num_channels)
        )
        svc.start_ttfb_metrics.assert_awaited_once()

    async def test_tts_audio_not_pushed_downstream(self) -> None:
        # The adapter never passes the TTS audio frame through; the client's
        # output sink emits the played audio instead.
        fake, svc = self._svc()
        frame = _audio()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        pushed = [c.args[0] for c in svc.push_frame.call_args_list]
        self.assertNotIn(frame, pushed)

    async def test_user_started_speaking_interrupts(self) -> None:
        fake, svc = self._svc()
        await svc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        self.assertIn("interrupt", fake.calls)

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
        self.assertNotIn("send_tts_audio", [c[0] for c in fake.calls if isinstance(c, tuple)])
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
        fake, svc = self._svc()
        frame = TTSStartedFrame()
        await svc.process_frame(frame, FrameDirection.DOWNSTREAM)
        self.assertIn((frame, FrameDirection.DOWNSTREAM), self._pushed_args(svc))

    async def test_unknown_frame_passes_through(self) -> None:
        fake, svc = self._svc()
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ubuntu/pipecat-ojin && python -m pytest tests/test_video.py -v`
Expected: FAIL / collection error — `ModuleNotFoundError: No module named 'pipecat_ojin.video'`.

- [ ] **Step 3: Implement `video.py`**

Create `src/pipecat_ojin/video.py`:

```python
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
from typing import Optional, Tuple

from ojin.stv import (
    OjinSessionTrace,
    OjinSTVClient,
    STVAudioFrame,
    STVEvent,
    STVVideoFrame,
)

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
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


@dataclass
class OjinVideoInitializedFrame(Frame):
    """Frame indicating the avatar session is ready (server handshake complete)."""

    session_data: Optional[dict] = None


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
    image_size: Tuple[int, int] = (512, 512)
    ws_url: str = "wss://models.ojin.ai/realtime"


def _is_trailing_silence(pcm: bytes, sample_rate: int, num_channels: int) -> bool:
    """True for the ~0.5 s all-zero sentinel the client discards in send_tts_audio."""
    if not pcm:
        return False
    duration = len(pcm) / (sample_rate * num_channels * 2)
    return abs(duration - 0.5) < 0.01 and pcm == b"\x00" * len(pcm)


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
            await self._svc.push_frame(
                OutputImageRawFrame(
                    image=frame.rgb,
                    size=(frame.width, frame.height),
                    format=frame.format,
                )
            )

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
        self._waiting_for_first_tts = False
        self._trace = session_trace
        self._output = _PushFrameOutput(self)
        self._stv = stv_client or OjinSTVClient(
            api_key=settings.api_key,
            config_id=settings.config_id,
            ws_url=settings.ws_url,
            image_size=settings.image_size,
            output=self._output,
            tracer=session_trace,
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
            if _is_trailing_silence(frame.audio, frame.sample_rate, frame.num_channels):
                return
            if self._waiting_for_first_tts:
                self._waiting_for_first_tts = False
                await self.start_ttfb_metrics()
            await self._stv.send_tts_audio(frame.audio, frame.sample_rate, frame.num_channels)
        elif isinstance(frame, UserStartedSpeakingFrame):
            await self._stv.interrupt()
            await self.push_frame(frame, direction)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stv.close()
            self._write_trace()
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

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
```

- [ ] **Step 4: Update `__init__.py` to export the video symbols**

Replace `src/pipecat_ojin/__init__.py` with:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/ubuntu/pipecat-ojin && python -m pytest tests/test_video.py tests/test_smoke.py -v`
Expected: PASS. `TestLifecycleThroughPipeline` either passes or is skipped (if `pipecat.tests.utils` isn't packaged); all other tests pass.

- [ ] **Step 6: Lint**

Run: `cd /home/ubuntu/pipecat-ojin && ruff check src/pipecat_ojin/video.py tests/test_video.py`
Expected: no errors (fix any reported, then re-run).

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/pipecat-ojin
git add src/pipecat_ojin/video.py src/pipecat_ojin/__init__.py tests/test_video.py
git commit -m "feat: add OjinVideoService avatar adapter"
```

---

### Task 3: `OjinTTSService` — Ojin text-to-speech

A faithful port of the legacy fork's `OjinTTSService` (a `pipecat.services.tts_service.TTSService` subclass over the SDK's low-level `ojin.ojin_client.OjinClient`). The source file imports only `ojin.*` and upstream `pipecat.*` symbols, so it ports without code changes.

**Files:**
- Create: `src/pipecat_ojin/tts.py` (copied verbatim from the legacy file, see Step 3)
- Create: `tests/test_tts.py`
- Modify: `src/pipecat_ojin/__init__.py`

**Interfaces:**
- Consumes: `ojin.entities.interaction_messages.ErrorResponseMessage`; `ojin.ojin_client.OjinClient`; `ojin.ojin_client_messages.*`; `pipecat.services.tts_service.TTSService`; `pipecat.frames.frames.*`; `pydantic.BaseModel`; `loguru`.
- Produces:
  - `OjinTTSServiceSettings(api_key="", ws_url="wss://models.ojin.ai/realtime", config_id="", sample_rate=24000, client_connect_max_retries=3, client_reconnect_delay=1.0)`.
  - `OjinTTSService(settings: OjinTTSServiceSettings, client: IOjinClient | None = None, **kwargs)` with `.can_generate_metrics()`, `async .connect_with_retry()`, `async .run_tts(text)`, `async .start/stop/cancel(...)`.
  - `OjinTTSServiceInitializedFrame(session_data=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tts.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ubuntu/pipecat-ojin && python -m pytest tests/test_tts.py -v`
Expected: FAIL / collection error — `ModuleNotFoundError: No module named 'pipecat_ojin.tts'`.

- [ ] **Step 3: Create `tts.py` by copying the legacy file verbatim**

The legacy file ports as-is (its imports are all SDK + upstream Pipecat). Copy it:

```bash
cp /home/ubuntu/pipecat-ojin-legacy/src/pipecat/services/ojin/tts.py \
   /home/ubuntu/pipecat-ojin/src/pipecat_ojin/tts.py
```

Then verify the file's imports are exactly these (no `pipecat.services.ojin.*` import — there must be none):

```bash
cd /home/ubuntu/pipecat-ojin
grep -n "pipecat.services.ojin" src/pipecat_ojin/tts.py && echo "UNEXPECTED fork import" || echo "OK: no fork imports"
```
Expected: `OK: no fork imports`. The file's external imports must be limited to `ojin.*`, `pipecat.frames.frames`, `pipecat.services.tts_service`, `pydantic`, `loguru`, and stdlib (`asyncio`, `os`, `dataclasses`, `typing`).

- [ ] **Step 4: Update `__init__.py` to export the TTS symbols**

Replace `src/pipecat_ojin/__init__.py` with:

```python
"""pipecat-ojin: Ojin avatar (Speech-To-Video) and TTS services for Pipecat."""

from pipecat_ojin.tts import (
    OjinTTSService,
    OjinTTSServiceInitializedFrame,
    OjinTTSServiceSettings,
)
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
    "OjinTTSService",
    "OjinTTSServiceInitializedFrame",
    "OjinTTSServiceSettings",
    "OjinVideoInitializedFrame",
    "OjinVideoService",
    "OjinVideoSettings",
    "__version__",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/ubuntu/pipecat-ojin && python -m pytest tests/ -v`
Expected: PASS (all tests across `test_smoke.py`, `test_video.py`, `test_tts.py`; the pipeline lifecycle test may be skipped).

- [ ] **Step 6: Lint**

Run: `cd /home/ubuntu/pipecat-ojin && ruff check src/pipecat_ojin tests`
Expected: no errors. If the copied `tts.py` reports lint issues (e.g. unused imports), fix them minimally without changing behaviour, then re-run.

- [ ] **Step 7: Commit**

```bash
cd /home/ubuntu/pipecat-ojin
git add src/pipecat_ojin/tts.py src/pipecat_ojin/__init__.py tests/test_tts.py
git commit -m "feat: add OjinTTSService text-to-speech service"
```

---

### Task 4: Example agent — `examples/ojin-bot/`

A runnable Pipecat voice+avatar agent that imports `OjinVideoService` from the installed package (proving end-to-end usage). Pipeline: `transport.input() -> STT -> LLM -> TTS -> OjinVideoService -> transport.output()`. Uses Deepgram (STT), OpenAI (LLM), Cartesia (TTS) so the env keys match the example's `env.example`. No automated test — verification is a manual run.

**Files:**
- Create: `examples/ojin-bot/bot.py`
- Create: `examples/ojin-bot/requirements.txt`
- Create: `examples/ojin-bot/env.example`
- Create: `examples/ojin-bot/README.md`

**Interfaces:**
- Consumes: `pipecat_ojin.{OjinVideoService, OjinVideoSettings}`; `ojin.{MissingCredentialsError, load_env, resolve_credentials}`; upstream Pipecat services/transports/runner.

- [ ] **Step 1: Create `examples/ojin-bot/bot.py`**

```python
"""Pipecat voice agent with an Ojin talking-avatar face.

Have a live, lip-synced video conversation with an AI in your browser. Your mic
and the avatar's video run over WebRTC; speech-to-text, an LLM, and text-to-speech
drive the words, and the Ojin avatar lip-syncs to them.

    transport.input() -> STT -> LLM -> TTS -> [OjinVideoService] -> transport.output()

The face is one line in the pipeline: ``OjinVideoService`` (from the installed
``pipecat-ojin`` package), dropped in after TTS and before ``transport.output()``.

Run (after installing requirements.txt and filling in .env):

    python bot.py              # all transports; open http://localhost:7860/client
    python bot.py -t webrtc    # local WebRTC only — no external account needed
    python bot.py -t daily     # join a Daily room instead (needs a Daily account)
"""

import logging
import os
import pathlib

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.workers.runner import WorkerRunner

from ojin import MissingCredentialsError, load_env, resolve_credentials
from pipecat_ojin import OjinVideoService, OjinVideoSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ojin-bot")

HERE = pathlib.Path(__file__).parent

# The avatar video size. It MUST match the transport's video_out_width/height
# below and your Face model's output size — a mismatch shows up as garbled video.
AVATAR_SIZE = (512, 512)

SYSTEM_PROMPT = (
    "You are a friendly AI assistant having a live video call with the user. "
    "Your replies are spoken aloud, so keep them short and natural and avoid "
    "emojis, bullet points, or any formatting that can't be read out loud. "
    "Open the conversation by greeting the user warmly and asking how you can help."
)

# Load the .env beside this file: the Ojin keys plus the STT/LLM/TTS keys.
load_env(base_dir=HERE)
try:
    CREDS = resolve_credentials(load_env_file=False)  # OJIN_API_KEY + OJIN_CONFIG_ID
except MissingCredentialsError as exc:
    raise SystemExit(str(exc)) from None


# Only the selected transport (via -t) is built, so the Daily path needs a Daily
# account only when you actually run `-t daily`.
transport_params = {
    "daily": lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        video_out_enabled=True,
        video_out_is_live=True,
        video_out_width=AVATAR_SIZE[0],
        video_out_height=AVATAR_SIZE[1],
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        video_out_enabled=True,
        video_out_is_live=True,
        video_out_width=AVATAR_SIZE[0],
        video_out_height=AVATAR_SIZE[1],
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Wire the STT -> LLM -> TTS -> avatar pipeline and run it for one call."""
    logger.info("Starting Ojin avatar voice agent")

    stt = DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])
    llm = OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model="gpt-4o-mini")
    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(
            voice="71a7ad14-091c-4e8e-a314-022ece01c121",  # Cartesia "British Lady"
            model="sonic-3",
        ),
    )

    # The Ojin face — the one stage that makes this an avatar agent. It lip-syncs
    # to whatever `tts` produces, so it sits right after TTS and before output.
    avatar = OjinVideoService(
        OjinVideoSettings(
            api_key=CREDS.api_key,
            config_id=CREDS.config_id,
            image_size=AVATAR_SIZE,
        )
    )

    context = LLMContext([{"role": "system", "content": SYSTEM_PROMPT}])
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            avatar,  # <-- the only line that adds the face
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport: BaseTransport, _client: object) -> None:
        logger.info("Client connected — starting the conversation")
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport: BaseTransport, _client: object) -> None:
        logger.info("Client disconnected — ending the call")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments) -> None:
    """Runner entry point: build the chosen transport, then run the pipeline."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
```

- [ ] **Step 2: Create `examples/ojin-bot/requirements.txt`**

```text
# The Ojin Pipecat integration (this repo). While developing locally, install
# the repo editable instead: pip install -e ..
pipecat-ojin

# Pipecat + the services this agent uses. Verified against pipecat-ai 1.3.x.
#   runner   -> dev runner + prebuilt browser UI (http://localhost:7860/client)
#   webrtc   -> local WebRTC call in the browser (default, no account needed)
#   daily    -> optional: join a Daily room (`-t daily`, needs an account)
#   silero   -> on-device voice-activity detection (turn-taking + barge-in)
#   deepgram -> speech-to-text
#   openai   -> the LLM
#   cartesia -> text-to-speech
pipecat-ai[runner,webrtc,daily,silero,deepgram,openai,cartesia]~=1.3.0
```

- [ ] **Step 3: Create `examples/ojin-bot/env.example`**

```text
# Copy this file to ".env" and fill in the values.

# --- Ojin (the avatar / face) -------------------------------------------------
# Get these from your Ojin account: https://ojin.ai  (docs: https://docs.ojin.ai)
OJIN_API_KEY=
OJIN_CONFIG_ID=

# --- The voice pipeline (STT / LLM / TTS) -------------------------------------
# Speech-to-text. https://console.deepgram.com  (free tier available)
DEEPGRAM_API_KEY=

# The LLM. https://platform.openai.com/api-keys
OPENAI_API_KEY=

# Text-to-speech. https://play.cartesia.ai  (free tier available)
CARTESIA_API_KEY=
```

- [ ] **Step 4: Create `examples/ojin-bot/README.md`**

```markdown
# ojin-bot — Pipecat voice agent with an Ojin avatar face

A standard [Pipecat](https://github.com/pipecat-ai/pipecat) voice agent with one
extra line: the `OjinVideoService` face, dropped in after TTS.

```
browser mic ─▶ WebRTC ─▶ STT ─▶ LLM ─▶ TTS ─▶ [Ojin avatar] ─▶ WebRTC ─▶ browser video
```

## What you need

1. Python 3.10+ and a Chromium-based browser (Chrome / Edge) for the call.
2. An Ojin account → [ojin.ai](https://ojin.ai): an API key (`OJIN_API_KEY`) and
   a Face model config id (`OJIN_CONFIG_ID`).
3. Keys for the voice pipeline: `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`,
   `CARTESIA_API_KEY`.

## Setup & run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ..                    # the pipecat-ojin package from this repo
pip install -r requirements.txt      # this example's pipeline deps
cp env.example .env                   # paste your keys into .env
python bot.py                         # -> open http://localhost:7860/client
```

> While `ojin-client` is not yet on PyPI, also run
> `pip install -e "/home/ubuntu/python-sdk[stv]"` first so pip can resolve the
> `pipecat-ojin` dependency.

| Command | What it does |
|---|---|
| `python bot.py` | All transports; browser client at `http://localhost:7860/client` |
| `python bot.py -t webrtc` | Local WebRTC only — no external account needed |
| `python bot.py -t daily` | Join a [Daily](https://daily.co) room (needs an account) |

> **On WSL2:** run `python bot.py` inside WSL and open
> `http://localhost:7860/client` in your Windows browser.
```

- [ ] **Step 5: Verify the example imports resolve (no live call)**

Run:
```bash
cd /home/ubuntu/pipecat-ojin/examples/ojin-bot
python -c "import ast; ast.parse(open('bot.py').read()); print('bot.py parses OK')"
python -c "from pipecat_ojin import OjinVideoService, OjinVideoSettings; print('pipecat_ojin imports OK')"
```
Expected: both print OK. (A full live run needs real API keys and is a manual step, documented in the README.)

- [ ] **Step 6: Commit**

```bash
cd /home/ubuntu/pipecat-ojin
git add examples/ojin-bot
git commit -m "docs: add ojin-bot example agent"
```

---

### Task 5: README, root env.example, and changelog finalize

Replace the placeholder root `README.md` with original, Ojin-flavored package docs (not anam's wording/order), add a minimal root `env.example`, and confirm the changelog.

**Files:**
- Modify: `README.md` (overwrite placeholder)
- Create: `env.example`
- Modify: `CHANGELOG.md` (already created in Task 1 — verify it lists the public surface; no edit needed if accurate)

**Interfaces:** none (docs only).

- [ ] **Step 1: Overwrite `README.md`**

```markdown
# pipecat-ojin

Ojin's [Pipecat](https://github.com/pipecat-ai/pipecat) integration: drop a
**lip-synced talking-avatar face** (`OjinVideoService`) and Ojin's
**text-to-speech** (`OjinTTSService`) into any Pipecat pipeline.

`OjinVideoService` is the one stage that turns a voice agent into a video-call
avatar — it lip-syncs to whatever your TTS produces and streams the avatar video
back. It sits in the same slot as Pipecat's Simli / Tavus / HeyGen avatars:

```
transport.input() -> STT -> LLM -> TTS -> [OjinVideoService] -> transport.output()
```

This package is a thin adapter over the framework-agnostic
[`ojin-client`](https://github.com/ojinai/python-sdk) SDK — all avatar behaviour
(A/V sync, audio-as-clock playback, barge-in re-sync) lives in the SDK. It is
**not** a fork of Pipecat.

## Install

```bash
pip install pipecat-ojin
```

This pulls in `pipecat-ai` and `ojin-client[stv]`. You provide the STT / LLM /
TTS services for your pipeline (e.g. `pip install "pipecat-ai[deepgram,openai,cartesia]"`).

## Quickstart — the avatar face

```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat_ojin import OjinVideoService, OjinVideoSettings

avatar = OjinVideoService(
    OjinVideoSettings(
        api_key="OJIN_API_KEY",
        config_id="OJIN_CONFIG_ID",   # the Face model to drive
        image_size=(512, 512),         # must match the transport's video_out size
    )
)

pipeline = Pipeline(
    [transport.input(), stt, llm, tts, avatar, transport.output()]
)
```

Get your `OJIN_API_KEY` and a Face model `OJIN_CONFIG_ID` from
[ojin.ai](https://ojin.ai) (docs: [docs.ojin.ai](https://docs.ojin.ai)).

### Session tracing (optional)

Pass an `ojin.stv.OjinSessionTrace` to record a per-call Perfetto trace; the
service dumps it on close:

```python
from ojin.stv import OjinSessionTrace

trace = OjinSessionTrace(session_id="my-call", config_id="OJIN_CONFIG_ID")
avatar = OjinVideoService(OjinVideoSettings(...), session_trace=trace)
```

## Ojin text-to-speech

```python
from pipecat_ojin import OjinTTSService, OjinTTSServiceSettings

tts = OjinTTSService(
    OjinTTSServiceSettings(api_key="OJIN_API_KEY", config_id="OJIN_CONFIG_ID")
)
```

## Example

A complete, runnable voice + avatar agent (browser WebRTC or Daily) lives in
[`examples/ojin-bot/`](examples/ojin-bot/).

## Compatibility

| Requirement | Version |
|---|---|
| Python | ≥ 3.10 |
| `pipecat-ai` | ≥ 1.3.0 |
| `ojin-client[stv]` | ≥ 0.6.7 |

## License

Apache-2.0. See [LICENSE](LICENSE).
```

- [ ] **Step 2: Create root `env.example`**

```text
# Copy to ".env" for local development. The runnable example has its own,
# fuller env file at examples/ojin-bot/env.example.

# Your Ojin API key and the Face model (avatar) config id.
# Get them from https://ojin.ai (docs: https://docs.ojin.ai).
OJIN_API_KEY=
OJIN_CONFIG_ID=
```

- [ ] **Step 3: Verify the changelog reflects the shipped surface**

Confirm `CHANGELOG.md`'s `[0.1.0]` entry mentions the two services. If not, replace its body with:

```markdown
## [0.1.0] - 2026-06-17

Initial release. Standalone Pipecat integration for Ojin, built on upstream
`pipecat-ai` and `ojin-client[stv]`:

- `OjinVideoService` — lip-synced talking-avatar face (`FrameProcessor` over
  `ojin.stv.OjinSTVClient`), with an optional playback-start gate and per-session
  Perfetto tracing.
- `OjinTTSService` — Ojin text-to-speech (`TTSService`).
- `examples/ojin-bot/` — a runnable browser/Daily voice + avatar agent.
```

- [ ] **Step 4: Final full test + lint pass**

Run:
```bash
cd /home/ubuntu/pipecat-ojin
python -m pytest tests/ -v
ruff check src/pipecat_ojin tests
python -m build  # confirms the package builds a wheel + sdist cleanly
```
Expected: all tests pass (lifecycle test may skip), no lint errors, `dist/pipecat_ojin-0.1.0-*.whl` and `.tar.gz` produced.

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/pipecat-ojin
git add README.md env.example CHANGELOG.md
git commit -m "docs: write package README, env example, and changelog"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Covered by |
|---|---|
| §2 Repo layout (`src/pipecat_ojin`, `examples/`, `tests/`, `pyproject.toml`, `README`, `CHANGELOG`, `env.example`) | Tasks 1, 4, 5 |
| §3.1 `OjinVideoService` + `OjinVideoSettings` + frames + gate + `connect_with_retry` + dump-on-close | Task 2 |
| §3.2 `OjinTTSService` + settings + initialized frame | Task 3 |
| §3.3 Tracing from SDK only, no module, not re-exported | Task 2 (uses `ojin.stv.OjinSessionTrace`, no tracing module created; `__init__` omits it) |
| §3.4 `__init__` public surface | Tasks 2–3 |
| §4 Dependencies / pyproject (`pipecat-ai`, `ojin-client[stv]`, `pydantic`, src layout, dev extra, no transport extras) | Task 1 |
| §5 Example `examples/ojin-bot/` importing from the package | Task 4 |
| §6 Testing (frame-mapping, gate, smoke, no network) | Tasks 1–3 |
| §7 Original README & uniqueness | Task 5 |
| §8 Migration impact (out of scope, documented) | n/a — no task, by design |
| §9.1 resampler/decoder: prefer SDK default | Task 2 — `OjinSTVClient` built without a `resampler` arg, so the SDK default (streaming Soxr) is used; no `pipecat.audio.utils` import |
| §9.2 `pipecat-ai` symbol availability | Task 2 Step 5 / Task 3 Step 5 (tests import the symbols); `run_test` guarded |
| §9.3 `ws_url` default `.ai` | Global Constraints + Task 2/3 settings |

No gaps.

**2. Placeholder scan:** No `TBD`/`TODO`/"implement later". The only `cp` (Task 3 Step 3) names an exact source path and is followed by a verification grep — concrete, not a placeholder.

**3. Type consistency:** `OjinVideoService(settings, *, session_trace=None, stv_client=None)` is used identically in `tests/test_video.py` (`_adapter`) and the example. `OjinVideoSettings` fields (`api_key`, `config_id`, `image_size`, `ws_url`) match across `video.py`, tests, example, and README. `OjinTTSService(settings, client=None)` matches `tests/test_tts.py`. `__all__` names in `__init__` match the classes defined in `video.py` / `tts.py`. `set_can_start_playback`, `connect_with_retry`, `can_generate_metrics` names are consistent across implementation and tests.
