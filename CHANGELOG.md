# Changelog

All notable changes to `pipecat-ojin` are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.1.4] - 2026-07-17

- `OjinSTVWebRTCService` — direct-WebRTC avatar adapter (`FrameProcessor` over
  `ojin.stv.OjinSTVWebRTCClient`). The inference server publishes the avatar's
  A/V into the room itself, so the service pushes no audio/video frames
  downstream: it forwards TTS audio to the client and maps the client's
  metadata-derived lifecycle events onto the same Pipecat frames
  `OjinVideoService` emits (including the stock speaking-boundary frames and
  the per-session trace dump on End/Cancel).
- Re-export `WebRTCSettings` from `ojin.stv` for caller convenience.
- Fixed the stale `__version__` (reported "0.1.0" since 0.1.1).
- Dependency floor raised: `ojin-client[stv]>=0.9.2` (first release with
  `OjinSTVWebRTCClient`).

## [0.1.0] - 2026-06-17

Initial release. Standalone Pipecat integration for Ojin, built on upstream
`pipecat-ai` and `ojin-client[stv]`:

- `OjinVideoService` — lip-synced talking-avatar face (`FrameProcessor` over
  `ojin.stv.OjinSTVClient`), with an optional playback-start gate and per-session
  Perfetto tracing.
- `examples/ojin-bot/` — a runnable browser/Daily voice + avatar agent.
