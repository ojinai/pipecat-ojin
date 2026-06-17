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
