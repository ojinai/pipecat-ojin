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

The SDK also **shapes the audio it forwards** to Ojin — priming a lead, then
coalescing your TTS into large chunks — so the inference head never starves and
lip-sync stays stable, whatever cadence your TTS produces. You don't manage
input buffering, the playback clock, or frame-dropping; `OjinVideoService` just
sits after your TTS and lip-syncs to it.

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

## Deployment

`OjinVideoService` connects to Ojin over a WebSocket built for **server-to-server**
use on a stable connection. Run your pipeline on a backend — ideally in **US East**,
near Ojin's inference — for the lowest latency, and deliver the final media to your
users over a realtime transport such as WebRTC or Daily.

## Troubleshooting

- **Avatar's mouth barely moves** — confirm TTS audio is actually flowing into
  `OjinVideoService`. The SDK shapes the feed for you, so this usually means the
  pipeline isn't producing audio rather than a chunking problem.
- **Garbled or stretched video** — your transport's `video_out_width` /
  `video_out_height` must match the Face model's frame size (`image_size`, e.g. `512×512`).
- **Higher latency than expected** — run the pipeline server-side in US East over a
  stable connection; don't run it on an end-user device.
- **`No backend servers available`** — inference capacity is momentarily exhausted; retry shortly.

Full guidance lives at **[docs.ojin.ai](https://docs.ojin.ai)** → Guides → Optimizing Performance / Troubleshooting.

## Compatibility

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| `pipecat-ai` | ≥ 1.3.0 |
| `ojin-client[stv]` | ≥ 0.7.1 |

## License

BSD-2-Clause. See [LICENSE](LICENSE).
