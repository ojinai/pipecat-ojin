"""Pipecat voice agent with an Ojin talking-avatar face.

Have a live, lip-synced video conversation with an AI in your browser. Your mic
and the avatar's video run over WebRTC; speech-to-text, an LLM, and text-to-speech
drive the words, and the Ojin avatar lip-syncs to them.

    transport.input() -> STT -> LLM -> TTS -> [OjinVideoService] -> transport.output()

The face is one line in the pipeline: ``OjinVideoService`` (from the installed
``pipecat-ojin`` package), dropped in after TTS and before ``transport.output()``.

Run (after installing requirements.txt and filling in .env):

    python bot.py              # all transports; open http://localhost:7860/client
    python bot.py -t webrtc    # local WebRTC only — no external account needed
    python bot.py -t daily     # join a Daily room instead (needs a Daily account)
"""

import logging
import os
import pathlib

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.workers.runner import WorkerRunner

from ojin import MissingCredentialsError, load_env, resolve_credentials
from pipecat_ojin import OjinVideoService, OjinVideoSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ojin-bot")

HERE = pathlib.Path(__file__).parent

# The avatar video size. It MUST match the transport's video_out_width/height
# below and your Face model's output size — a mismatch shows up as garbled video.
AVATAR_SIZE = (512, 512)

SYSTEM_PROMPT = (
    "You are a friendly AI assistant having a live video call with the user. "
    "Your replies are spoken aloud, so keep them short and natural and avoid "
    "emojis, bullet points, or any formatting that can't be read out loud. "
    "Open the conversation by greeting the user warmly and asking how you can help."
)

# Load the .env beside this file: the Ojin keys plus the STT/LLM/TTS keys.
load_env(base_dir=HERE)
try:
    CREDS = resolve_credentials(load_env_file=False)  # OJIN_API_KEY + OJIN_CONFIG_ID
except MissingCredentialsError as exc:
    raise SystemExit(str(exc)) from None


# Only the selected transport (via -t) is built, so the Daily path needs a Daily
# account only when you actually run `-t daily`.
transport_params = {
    "daily": lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        video_out_enabled=True,
        video_out_is_live=True,
        video_out_width=AVATAR_SIZE[0],
        video_out_height=AVATAR_SIZE[1],
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        video_out_enabled=True,
        video_out_is_live=True,
        video_out_width=AVATAR_SIZE[0],
        video_out_height=AVATAR_SIZE[1],
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Wire the STT -> LLM -> TTS -> avatar pipeline and run it for one call."""
    logger.info("Starting Ojin avatar voice agent")

    stt = DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])
    llm = OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model="gpt-4o-mini")
    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(
            voice="71a7ad14-091c-4e8e-a314-022ece01c121",  # Cartesia "British Lady"
            model="sonic-3",
        ),
    )

    # The Ojin face — the one stage that makes this an avatar agent. It lip-syncs
    # to whatever `tts` produces, so it sits right after TTS and before output.
    avatar = OjinVideoService(
        OjinVideoSettings(
            api_key=CREDS.api_key,
            config_id=CREDS.config_id,
            image_size=AVATAR_SIZE,
        )
    )

    context = LLMContext([{"role": "system", "content": SYSTEM_PROMPT}])
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
            avatar,  # <-- the only line that adds the face
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport: BaseTransport, _client: object) -> None:
        logger.info("Client connected — starting the conversation")
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport: BaseTransport, _client: object) -> None:
        logger.info("Client disconnected — ending the call")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments) -> None:
    """Runner entry point: build the chosen transport, then run the pipeline."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
