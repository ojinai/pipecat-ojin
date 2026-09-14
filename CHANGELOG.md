# Changelog

All notable changes to `pipecat-ojin` are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.1.5] - 2026-09-14

- **Direct WebRTC on `OjinVideoService`.** New `OjinVideoSettings.webrtc`
  (`ojin.stv.WebRTCSettings`): when set, the inference server publishes the
  avatar straight into your Daily or LiveKit room and the service pushes no
  audio/video frames downstream (disable the transport's audio/video out). Every
  lifecycle frame is unchanged; `OjinFirstVideoFrame` is pushed from the client's
  `FIRST_FRAME` event in this mode. Leave `webrtc` unset for the WebSocket path.
- A failed or unsupported WebRTC session is a fatal `push_error`
  (`WEBRTC_JOIN_FAILED` / `WEBRTC_UNSUPPORTED`) — ojin-client 0.11 removed the
  silent relay fallback.
- `OjinSTVWebRTCService` is kept for existing callers; new code should use
  `OjinVideoService` with `webrtc=`.
- Dependency floor raised: `ojin-client[stv]>=0.11.0`.

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
