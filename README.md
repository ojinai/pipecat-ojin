# pipecat-ojin

Ojin's [Pipecat](https://github.com/pipecat-ai/pipecat) integration: drop a
**lip-synced talking-avatar face** (`OjinVideoService`) into your existing pipeline in minutes.

`OjinVideoService` is the one stage that turns a voice agent into a video-call
avatar — it lip-syncs to whatever your TTS produces and streams the avatar video
back. It sits in the same slot as other video services in pipecat:

```
transport.input() -> STT -> LLM -> TTS -> [OjinVideoService] -> transport.output()
```

This package is a thin adapter over the framework-agnostic
[`ojin-client`](https://github.com/ojinai/python-sdk) SDK — all avatar behaviour
(A/V sync, audio-as-clock playback, barge-in re-sync) lives in the SDK. It is
**not** a fork of Pipecat — it depends on `pipecat-ai` as a library.

## Install

```bash
pip install pipecat-ojin
```

This pulls in `pipecat-ai` and `ojin-client[stv]`. You provide the STT / LLM /
TTS services for your pipeline (e.g. `pip install "pipecat-ai[deepgram,groq,elevenlabs]"`).

## Quickstart — the avatar face

```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat_ojin import OjinVideoService, OjinVideoSettings

avatar = OjinVideoService(
    OjinVideoSettings(
        api_key="OJIN_API_KEY",
        config_id="OJIN_CONFIG_ID",   # the Face model to drive
    )
)

pipeline = Pipeline(
    [transport.input(), stt, llm, tts, avatar, transport.output()]
)
```

The avatar's frame size comes from your Face model (`config_id`) — set your
transport's `video_out_width` / `video_out_height` to match it (the example uses
512×512).

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

## Example

A complete, runnable voice + avatar agent (browser WebRTC or Daily) lives in
[`examples/ojin-bot/`](examples/ojin-bot/).

## Compatibility

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| `pipecat-ai` | ≥ 1.3.0 |
| `ojin-client[stv]` | ≥ 0.7.1 |

## License

Apache-2.0. See [LICENSE](LICENSE).
