# Changelog

All notable changes to `pipecat-ojin` are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-17

Initial release. Standalone Pipecat integration for Ojin, built on upstream
`pipecat-ai` and `ojin-client[stv]`:

- `OjinVideoService` — lip-synced talking-avatar face (`FrameProcessor` over
  `ojin.stv.OjinSTVClient`), with an optional playback-start gate and per-session
  Perfetto tracing.
- `examples/ojin-bot/` — a runnable browser/Daily voice + avatar agent.
