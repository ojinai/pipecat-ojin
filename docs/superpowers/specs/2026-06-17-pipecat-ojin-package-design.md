# Design: `pipecat-ojin` — standalone Pipecat integration package

**Date:** 2026-06-17
**Status:** Approved (pending written-spec review)
**Repo:** `github.com/ojinai/pipecat-ojin` (local: `/home/ubuntu/pipecat-ojin`)

## 1. Goal & non-goals

### Goal

Build a fresh, self-contained `pipecat-ojin` package that provides Ojin's Pipecat
integration on top of **upstream `pipecat-ai` + `ojin-client[stv]`** — the way
[`pipecat-anam`](https://github.com/anam-org/pipecat-anam) sits on upstream
Pipecat plus the Anam SDK. It is **not** a fork of Pipecat.

The package ships three things:

- `OjinVideoService` — a Pipecat `FrameProcessor` that turns a TTS audio stream
  into a lip-synced Ojin avatar (the "face" stage), built on
  `ojin.stv.OjinSTVClient`.
- `OjinTTSService` — a Pipecat `TTSService` backed by Ojin's low-level client.
- A runnable example agent under `examples/ojin-bot/`.

### Non-goals (this task)

- **Migrating `demo-modal-agents`** off the legacy fork — separate follow-up.
- **PyPI publish CI** (GitHub Actions release workflow) — wired up later. This
  task produces a buildable package (`pyproject.toml`) only.
- Changing the legacy fork (`/home/ubuntu/pipecat-ojin-legacy`) or the
  python-sdk.

### Background / why this exists

The current `pipecat-ojin` (now `/home/ubuntu/pipecat-ojin-legacy`) is a **full
fork of `pipecat-ai`** — the package is literally named `pipecat-ai` and is
installed by `demo-modal-agents` via
`pipecat-ai[...,ojin,...] @ git+https://github.com/journee-live/pipecat-ojin.git@staging`.
Carrying an entire fork to ship three Ojin-specific modules is heavy and drifts
from upstream. The Ojin adapter is already SDK-based and thin (the legacy fork
declares `ojin-client>=0.6.7`), so it can be lifted into a standalone package on
top of upstream Pipecat. The new repo lives in a different GitHub org
(`ojinai/` vs `journee-live/`), so there is no clash with the legacy install URL.

The reference implementation for the clean adapter is the python-sdk example at
`/home/ubuntu/python-sdk/examples/03-pipecat-example` (`OjinAvatarService` in
`ojin_avatar.py`).

## 2. Repository layout

```
pipecat-ojin/
├── src/pipecat_ojin/
│   ├── __init__.py          # public exports + __version__
│   ├── video.py             # OjinVideoService + OjinVideoSettings + frames
│   └── tts.py               # OjinTTSService + OjinTTSServiceSettings
├── examples/
│   └── ojin-bot/            # runnable Daily/WebRTC voice+avatar agent
│       ├── bot.py
│       ├── requirements.txt
│       ├── env.example
│       └── README.md
├── tests/                   # unit tests for the frame-mapping logic
├── pyproject.toml           # build + dependencies
├── README.md                # original, Ojin-flavored (overwrites placeholder)
├── CHANGELOG.md             # new
├── LICENSE                  # keep existing (Apache-2.0, matches the SDK)
├── env.example              # new
└── .gitignore               # keep existing
```

Inspired by anam's layout (`src/`, `examples/`, `pyproject.toml`,
`env.example`, `CHANGELOG.md`) but not a copy — see §7.

## 3. Package API (`pipecat_ojin`)

### 3.1 `video.py` — `OjinVideoService` (the core)

A Pipecat `FrameProcessor` based on the **clean python-sdk example adapter**
(`OjinAvatarService`), renamed to `OjinVideoService` and kept minimal. All avatar
behavior (connect/retry, audio-as-clock playback, A/V sync, re-sync after
barge-in) lives in `ojin.stv.OjinSTVClient`; this class is only the Pipecat
frame ↔ client mapping. Place it after TTS and before `transport.output()`:

```
transport.input() -> STT -> LLM -> TTS -> [OjinVideoService] -> transport.output()
```

**Constructor (settings-object, per [[feedback_model_pattern]]):**

```python
OjinVideoService(
    settings: OjinVideoSettings,
    *,
    session_trace: OjinSessionTrace | None = None,  # from ojin.stv
)
```

`session_trace` is a runtime object (not config), passed separately and typed
against `ojin.stv.OjinSessionTrace` — see §3.3. The constructor wires the
client's lifecycle events (`BOT_STARTED_SPEAKING` → stop TTFB; `ERROR` →
`push_error`).

**`OjinVideoSettings` (dataclass):** minimal surface — the dead/unused legacy
knobs are dropped.

| Field | Default | Purpose |
|---|---|---|
| `api_key` | `""` | Ojin API key |
| `config_id` | `""` | Ojin Face-model config id (the avatar) |
| `image_size` | `(512, 512)` | Avatar frame size; must match transport `video_out_width/height` |
| `ws_url` | `"wss://models.ojin.ai/realtime"` | Ojin realtime websocket URL |

This is exactly the python-sdk example's surface (the four identity/size fields).
Dropped from the legacy `OjinVideoSettings` (unused, fork-internal, or
not in the clean example): `tts_audio_passthrough`,
`client_connect_max_retries`/`client_reconnect_delay` (kept as `STVConfig`
defaults inside the client), `started/stopped_speaking_delay_s`,
`frame_debugging_enabled`, `start_frame_cls`, `max_buffered_video_frames`,
`idle_buffer_target_frames`, `lipsync_trace_enabled`, `align_audio_*`,
`interrupt_audio_fade_s`, and the `OJIN_LOOP_STALL_WATCHDOG_MS` /
`OJIN_TICK_WARN_MS` / `OJIN_STALL_PROBE_MS` env escape hatches. If a later
migration needs any of these (most likely `tts_audio_passthrough`), they are
re-added behind the settings object then.

**Frame mapping (`process_frame`):**

| Inbound frame | Action |
|---|---|
| `StartFrame` | push through, then `client.start()` (connect + run playback loops) |
| `TTSStartedFrame` | `client.start_turn()` (open a buffer); arm "waiting for first TTS" |
| `TTSAudioRawFrame` | drop ~0.5 s trailing-silence sentinel; else arm TTFB on first real audio, `client.send_tts_audio(...)` |
| `UserStartedSpeakingFrame` | `client.interrupt()` (barge-in; no-op if idle), push through |
| `EndFrame` / `CancelFrame` | `client.close()`, flush session trace, push through |
| everything else | passthrough (stay transparent) |

**Output:** a push-model `STVOutput` sink forwards the client's synced A/V
downstream as `OutputAudioRawFrame` / `OutputImageRawFrame`. The client returns
the **original** TTS audio to play (only a 16 kHz copy is sent to Ojin) plus the
decoded avatar video (repeats the last frame on held ticks).

**Production hooks retained** (per design decision — small, load-bearing, keep
the future `demo-modal-agents` migration near drop-in):

- `set_can_start_playback(value: bool)` — gate that drops A/V until the
  participant has joined (keeps the connect→join idle backlog out of the
  transport). The `STVOutput` sink checks this before pushing. **Defaults to
  open (`True`)** so the example bot and any simple pipeline work without gate
  management — this inverts the legacy default (which started closed). Callers
  that want join-gating (e.g. `demo-modal-agents`) close it explicitly after
  construction and re-open at participant join; that is a one-line change at
  migration time.
- `connect_with_retry() -> bool` — explicit connect for callers that connect
  before `StartFrame`.

**Custom frames exported** (referenced by `demo-modal-agents`):
`OjinBotStartedSpeakingFrame`, `OjinVideoInitializedFrame`.

**Trailing-silence helper:** `_is_trailing_silence(pcm, sample_rate,
num_channels)` mirrors the client's discard (≈0.5 s all-zero) so the adapter
neither arms TTFB nor forwards a frame the client will drop.

### 3.2 `tts.py` — `OjinTTSService`

Port of the legacy `OjinTTSService` (a `pipecat.services.tts_service.TTSService`
subclass) and `OjinTTSServiceSettings`, plus `OjinTTSServiceInitializedFrame`.
Built on the SDK's low-level `ojin.ojin_client.OjinClient` and
`ojin.entities`/`ojin.ojin_client_messages` types — all upstream-Pipecat + SDK
symbols, nothing fork-internal. Independent of the video service. Settings stay
an encapsulated object (`OjinTTSServiceSettings`), consistent with
[[feedback_model_pattern]].

### 3.3 Session tracing — **from the SDK only, no module here**

The package ships **no tracing module**. `ojin.stv.OjinSessionTrace` is fully
self-contained (it has its own `dump(path)` that writes the Perfetto JSON), so
the fork's duplicate tracer, `trace_sinks` (`PerfettoFileSink`/`TraceSink`),
`new_session_id`, lane helpers, and `session_trace_enabled` are **not** ported.

Callers construct and pass `ojin.stv.OjinSessionTrace` directly (as the example
does). `OjinVideoService` accepts it as the optional `session_trace` parameter
and, on `End`/`Cancel`, dumps it to disk (the example's `_write_trace` helper:
`<root>/<date>/<time>_<session_id>/session.json`, root via `OJIN_STV_TRACE_DIR`,
toggle via `OJIN_STV_SESSION_TRACE`). `pipecat_ojin` does **not** re-export
`OjinSessionTrace`.

### 3.4 `__init__.py` — public surface

Exports: `OjinVideoService`, `OjinVideoSettings`, `OjinBotStartedSpeakingFrame`,
`OjinVideoInitializedFrame`, `OjinTTSService`, `OjinTTSServiceSettings`,
`OjinTTSServiceInitializedFrame`, and `__version__`. Session tracing is **not**
re-exported (use `ojin.stv` directly).

## 4. Dependencies (`pyproject.toml`)

Anam-style: the package bundles everything needed to `import pipecat_ojin` and
run the two services. Service-specific STT/LLM/TTS extras live in the example,
not the core package.

- **Core deps:** `pipecat-ai>=1.3.0`, `ojin-client[stv]>=0.6.7`, `pydantic`
  (TTS settings). `loguru` comes transitively via `pipecat-ai`.
- **Build:** `setuptools` backend, `src/` layout (`package-dir = {"" = "src"}`,
  `packages = ["pipecat_ojin"]`).
- **Metadata:** `name = "pipecat-ojin"`, `version = "0.1.0"`,
  `requires-python = ">=3.10"`, `license = Apache-2.0`, project URLs to the
  GitHub repo / ojin.ai / docs.
- **No** `[project.optional-dependencies]` for transports in the core package
  (those belong to the example). A `dev` extra (pytest, pytest-asyncio, ruff,
  build) is included for local development.

`pipecat-ai>=1.3.0` matches the version the python-sdk example is verified
against; the plan must confirm the upstream `pipecat-ai` exposes every symbol
the two services import (`TTSService`, frame classes, `FrameProcessor`,
`create_default_resampler` from `pipecat.audio.utils`).

## 5. Example: `examples/ojin-bot/`

A trimmed port of python-sdk `03-pipecat-example/bot.py`:
`transport.input() → STT → LLM → TTS → OjinVideoService → transport.output()`,
runnable via Pipecat's dev runner (WebRTC default, Daily optional via `-t
daily`). Key difference from the python-sdk example: it imports
`from pipecat_ojin import OjinVideoService` (proving the installed package),
**not** a local `ojin_avatar.py`.

- `requirements.txt` — `pipecat-ojin` (or `-e ..` while developing) plus the
  pipeline service extras: `pipecat-ai[runner,webrtc,daily,silero,deepgram,
  google,cartesia]~=1.3.0`.
- `env.example` — `OJIN_API_KEY`, `OJIN_CONFIG_ID`, and STT/LLM/TTS keys.
- `README.md` — short run instructions (uv + plain-pip), transport table, WSL2
  note.

## 6. Testing

- Unit tests for `OjinVideoService` frame-mapping: mock `OjinSTVClient`, assert
  each inbound frame triggers the right client call, that trailing-silence is
  dropped, and that the `set_can_start_playback` gate suppresses output until
  opened.
- A smoke import test (`import pipecat_ojin` resolves and re-exports the public
  symbols).
- No live websocket/network in CI.

## 7. README & uniqueness

Original copy, not anam's wording or section order. Sections: a short "what is
Ojin" intro, the one-line-in-the-pipeline framing (the avatar is a single
stage), install (`pip install pipecat-ojin`), a minimal `OjinVideoService`
snippet, an `OjinTTSService` snippet, a pointer to `examples/ojin-bot/`, and a
compatibility table (Python ≥3.10, `pipecat-ai` ≥1.3.0, `ojin-client[stv]`
≥0.6.7).

## 8. Migration impact (follow-up, out of scope here)

`demo-modal-agents` currently imports from the fork:

- `pipecat.services.ojin.video` → `OjinVideoService`, `OjinVideoSettings`,
  `OjinBotStartedSpeakingFrame`, `OjinVideoInitializedFrame`
- `pipecat.services.ojin.tts` → `OjinTTSService`, `OjinTTSServiceSettings`
- `pipecat.services.ojin.session_trace` → `OjinSessionTrace`, `new_session_id`

The eventual migration will: depend on upstream `pipecat-ai` + `pipecat-ojin`
instead of the fork; rewrite imports to `from pipecat_ojin import ...` (and
`from ojin.stv import OjinSessionTrace`); and replace `new_session_id` with a
local id or the SDK equivalent. Retaining `set_can_start_playback` /
`connect_with_retry` and the settings-object constructor keeps that migration
close to a drop-in. This design does not implement the migration.

## 9. Open reconciliation points for the implementation plan

1. **TTS resampler / decoder defaults:** confirm whether `OjinTTSService` (or the
   video path) needs `create_default_resampler` from `pipecat.audio.utils` vs the
   SDK's own resampler; prefer the SDK's where it exists to minimize Pipecat
   coupling.
2. **`pipecat-ai` symbol availability:** verify upstream `pipecat-ai>=1.3.0`
   exports every imported symbol (the legacy code ran against the fork, which may
   have had local additions).
3. **`OjinVideoSettings.ws_url` default:** the example uses
   `wss://models.ojin.foo/realtime`; the legacy used `wss://models.ojin.ai/realtime`.
   Use the production `.ai` host as the default.
```
