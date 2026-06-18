# ojin-bot — Pipecat voice agent with an Ojin avatar face

A standard [Pipecat](https://github.com/pipecat-ai/pipecat) voice agent with one
extra line: the `OjinVideoService` face, dropped in after TTS.

```
browser mic ─▶ WebRTC ─▶ Deepgram STT ─▶ Groq LLM ─▶ ElevenLabs TTS ─▶ [Ojin avatar] ─▶ WebRTC ─▶ browser video
```

## What you need

1. Python 3.10+ and a Chromium-based browser (Chrome / Edge) for the call.
2. An Ojin account → [ojin.ai](https://ojin.ai): an API key (`OJIN_API_KEY`) and
   a Face model config id (`OJIN_CONFIG_ID`).
3. Keys for the voice pipeline — see [`env.example`](env.example) for where to get each:
   - `DEEPGRAM_API_KEY` — speech-to-text
   - `GROQ_API_KEY` — the LLM (`gpt-oss-120b`)
   - `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` — text-to-speech

## Setup & run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../..                    # the pipecat-ojin package from this repo
pip install -r requirements.txt      # this example's pipeline deps
cp env.example .env                   # paste your keys into .env
python bot.py                         # -> open http://localhost:7860/client
```

> While `ojin-client` and `pipecat-ojin` are not yet on PyPI, first install the
> Ojin Python SDK from source so pip can resolve the dependency: clone
> https://github.com/ojinai/python-sdk and run `pip install -e "/path/to/python-sdk[stv]"`.
> Use **`ojin-client` 0.7.0+** — from 0.7.0 the avatar streams the server's native
> frame resolution (older builds rescaled to a fixed `image_size`).

| Command | What it does |
|---|---|
| `python bot.py` | All transports; browser client at `http://localhost:7860/client` |
| `python bot.py -t webrtc` | Local WebRTC only — no external account needed |
| `python bot.py -t daily` | Join a [Daily](https://daily.co) room (needs an account) |

`-t daily` also needs `DAILY_API_KEY` in your `.env` (see `env.example`).

> **Avatar resolution:** the avatar streams at your Face model's native size (e.g.
> 1024×1024). `AVATAR_SIZE` in `bot.py` sets the WebRTC **output track** size — set
> it to your model's native resolution so frames pass through without rescaling.

> **On WSL2:** run `python bot.py` inside WSL and open
> `http://localhost:7860/client` in your Windows browser.
