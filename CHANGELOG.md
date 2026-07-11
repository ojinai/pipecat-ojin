# Changelog

All notable changes to `pipecat-ojin` are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.1.4] - 2026-07-12

### Fixed
- `OjinVideoService` no longer feeds the avatar (or arms TTFB metrics) with a TTS
  turn that the client rejects — a turn whose `TTSStartedFrame` lands while a
  barge-in is still settling server-side. It now queries the new
  `OjinSTVClient.is_audio_input_enabled()`: when a turn is being discarded it skips
  first-TTS bookkeeping on `TTSStartedFrame` and drops every `TTSAudioRawFrame` of
  that turn (staying in effect even if the interruption clears mid-turn), so the
  client stays in sync with the server, which discards the same audio. Requires
  `ojin-client >= 0.8.3`. The discard decision itself lives in the SDK; the adapter
  only queries the flag.

## [0.1.0] - 2026-06-17

Initial release. Standalone Pipecat integration for Ojin, built on upstream
`pipecat-ai` and `ojin-client[stv]`:

- `OjinVideoService` — lip-synced talking-avatar face (`FrameProcessor` over
  `ojin.stv.OjinSTVClient`), with an optional playback-start gate and per-session
  Perfetto tracing.
- `examples/ojin-bot/` — a runnable browser/Daily voice + avatar agent.
