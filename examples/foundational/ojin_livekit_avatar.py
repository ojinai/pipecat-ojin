"""Foundational example: a Pipecat voice agent with an Ojin avatar in a LiveKit room.

Pipeline:

    transport.input() -> STT -> user aggregator -> LLM -> TTS -> [OjinVideoService]
        -> transport.output() -> assistant aggregator

``OjinVideoService`` sits after TTS. Because ``OjinVideoSettings.webrtc`` is set, the
Ojin inference server joins your LiveKit room as the ``ojin-avatar`` participant and
publishes the avatar's audio and video there itself. The bot only sends TTS audio and
control messages to Ojin, so the transport's audio and video out are disabled.

Install (from the repository root, with Python 3.11 or newer):

    pip install pipecat-ojin "pipecat-ai[livekit,silero,deepgram,groq,elevenlabs]" python-dotenv

Configure a ``.env`` file in the directory you run from (never commit it):

    OJIN_API_KEY, OJIN_CONFIG_ID          from https://ojin.ai
    DEEPGRAM_API_KEY, GROQ_API_KEY        speech-to-text and LLM
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID    text-to-speech
    LIVEKIT_URL                           wss://<your-project>.livekit.cloud
    LIVEKIT_API_KEY, LIVEKIT_API_SECRET   used here to mint the bot and avatar tokens
    LIVEKIT_ROOM_NAME                     optional, defaults to "ojin-demo"

Run:

    python ojin_livekit_avatar.py

Then join the same room from any LiveKit client with a token for your own participant
(for example one created in your LiveKit project). The bot greets you when you join.
The LiveKit server must be reachable by Ojin, so a server on ``localhost`` will not
work. Tested with Pipecat 1.3.0 and 1.16.0 (unit tests only; see the README).

This example is maintained by Ojin, the company behind the avatar service.
"""

import asyncio
import os
from datetime import timedelta

from dotenv import load_dotenv
from livekit import api as livekit_api
from ojin import is_avatar_identity
from ojin.stv import WebRTCProvider, WebRTCSettings
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport
from pipecat.workers.runner import WorkerRunner

from pipecat_ojin import OjinVideoService, OjinVideoSettings

load_dotenv(override=True)

# Must match the sample rate your TTS emits (Pipecat's default output rate is 24000).
AUDIO_SAMPLE_RATE = 24000


def mint_token(identity: str, room: str, *, avatar: bool = False) -> str:
    """Create a short-lived LiveKit access token for ``identity`` in ``room``.

    The avatar token only needs to join and publish, so it cannot subscribe or send
    data. Its identity must be ``ojin-avatar`` so the bot can tell it apart.
    """
    grants = livekit_api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=not avatar,
        can_publish_data=not avatar,
    )
    return (
        livekit_api.AccessToken(
            os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]
        )
        .with_identity(identity)
        .with_grants(grants)
        .with_ttl(timedelta(hours=1))
        .to_jwt()
    )


async def main() -> None:
    """Build the pipeline and run it until the user leaves the room."""
    url = os.environ["LIVEKIT_URL"]
    room = os.getenv("LIVEKIT_ROOM_NAME", "ojin-demo")

    # The bot is a normal LiveKit participant. It publishes nothing itself: the
    # avatar's media comes from Ojin straight into the room.
    transport = LiveKitTransport(
        url,
        mint_token("pipecat-bot", room),
        room,
        params=LiveKitParams(audio_in_enabled=True, audio_out_enabled=False),
    )

    stt = DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])
    llm = GroqLLMService(api_key=os.environ["GROQ_API_KEY"], model="openai/gpt-oss-20b")
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        voice_id=os.environ["ELEVENLABS_VOICE_ID"],
    )

    # The one line that adds the face. Ojin joins the room as "ojin-avatar" with
    # the token below; give it a long join timeout because a cold start can be slow.
    avatar = OjinVideoService(
        OjinVideoSettings(
            api_key=os.environ["OJIN_API_KEY"],
            config_id=os.environ["OJIN_CONFIG_ID"],
            webrtc=WebRTCSettings(
                provider=WebRTCProvider.LIVEKIT,
                room_url=url,
                token=mint_token("ojin-avatar", room, avatar=True),
                audio_sample_rate=AUDIO_SAMPLE_RATE,
                webrtc_join_timeout_s=90.0,
            ),
        )
    )

    context = LLMContext(
        [
            {
                "role": "system",
                "content": (
                    "You are a friendly assistant with a video avatar. Your replies "
                    "are spoken aloud, so keep them short and natural and avoid "
                    "emojis, lists or formatting. Greet the user and ask how you "
                    "can help."
                ),
            }
        ]
    )
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
            avatar,
            transport.output(),
            assistant_aggregator,
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_out_sample_rate=AUDIO_SAMPLE_RATE, allow_interruptions=True
        ),
    )

    started = False

    @transport.event_handler("on_audio_track_subscribed")
    async def on_audio_track_subscribed(_transport, participant_id: str) -> None:
        if is_avatar_identity(participant_id):
            # Do not let the bot hear the avatar's own voice.
            await transport.mute_participant(participant_id)

    @transport.event_handler("on_participant_connected")
    async def on_participant_connected(_transport, participant_id: str) -> None:
        nonlocal started
        if not started and not is_avatar_identity(participant_id):
            started = True
            await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_participant_disconnected")
    async def on_participant_disconnected(
        _transport, participant_id: str, *_args
    ) -> None:
        if not is_avatar_identity(participant_id):
            await worker.cancel()

    runner = WorkerRunner()
    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
