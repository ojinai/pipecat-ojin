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

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frameworks.rtvi import (
    RTVIFunctionCallReportLevel,
    RTVIObserverParams,
    RTVIProcessor,
)
from pipecat.processors.frameworks.rtvi.models import (
    BotOutputMessage,
    BotOutputMessageData,
    ServerMessage,
)
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.frames.frames import (
    AggregationType,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMRunFrame,
    LLMTextFrame,
)
from pipecat.utils.string import match_endofsentence
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.workers.runner import WorkerRunner

from ojin import MissingCredentialsError, load_env, resolve_credentials
from pipecat_ojin import (
    OjinVideoInitializedFrame,
    OjinVideoService,
    OjinVideoSettings,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("ojin-bot")

HERE = pathlib.Path(__file__).parent


# --- Debug: log every RTVI message sent to the client --------------------------
# Set OJIN_DEBUG_RTVI=1 to see exactly which RTVI messages (bot-llm-text,
# bot-transcription, user-transcription, function calls, etc.) reach the
# playground. Used to diagnose why bot transcriptions weren't showing. Remove
# once the conversation panel is confirmed working.
if os.environ.get("OJIN_DEBUG_RTVI"):
    from pipecat.processors.frameworks.rtvi.observer import RTVIObserver

    _orig_send_rtvi_message = RTVIObserver.send_rtvi_message

    async def _logged_send_rtvi_message(self, model, exclude_none: bool = True):
        label = getattr(model, "label", None) or getattr(model, "type", None)
        logger.info("RTVI→client: %s (%s)", type(model).__name__, label)
        return await _orig_send_rtvi_message(self, model, exclude_none)

    RTVIObserver.send_rtvi_message = _logged_send_rtvi_message
    logger.info("OJIN_DEBUG_RTVI on — logging all outbound RTVI messages")


class BotOutputFromLLMObserver(BaseObserver):
    """Send RTVI ``bot-output`` messages built from the bot's LLM text.

    The Pipecat Playground renders the bot side of its conversation panel from
    ``bot-output`` messages. The built-in RTVI observer only produces those from
    TTS text that the *output transport* releases in sync with the audio it
    plays. Our avatar (``OjinVideoService``) consumes the TTS audio and emits its
    own synced A/V, so that audio-timed path never fires and the bot side stays
    blank — even though ``bot-llm-text`` / ``bot-transcription`` are still sent
    (the playground client treats those as deprecated).

    This observer watches ``LLMTextFrame``s — which flow regardless of audio or
    the avatar — and emits one ``bot-output`` message per sentence (flushing
    whatever is left when the turn ends or is interrupted). It's the same idea as
    ``demo-modal-agents``' ``TranscriptCapture``, but speaks the RTVI message the
    prebuilt playground actually reads. Wired alongside (not replacing) the
    default RTVI observer, so function calls and everything else are unaffected.
    """

    def __init__(self, rtvi: RTVIProcessor) -> None:
        super().__init__()
        self._rtvi = rtvi
        self._buffer = ""
        self._seen: set[int] = set()

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        # LLMTextFrame is pushed both downstream (to TTS) and observed here; the
        # id guard keeps us from counting the same delta twice.
        if isinstance(frame, LLMTextFrame):
            if frame.id in self._seen:
                return
            self._seen.add(frame.id)
            if frame.text:
                self._buffer += frame.text
                if match_endofsentence(self._buffer):
                    await self._flush()
        elif isinstance(frame, (LLMFullResponseEndFrame, InterruptionFrame)):
            await self._flush()

    async def _flush(self) -> None:
        text = self._buffer.strip()
        self._buffer = ""
        if not text:
            return
        await self._rtvi.push_transport_message(
            BotOutputMessage(
                data=BotOutputMessageData(
                    text=text, spoken=True, aggregated_by=AggregationType.SENTENCE
                )
            )
        )


class AvatarStatusObserver(BaseObserver):
    """Surface a "connected" status to the playground when the avatar is ready.

    ``OjinVideoService`` pushes an ``OjinVideoInitializedFrame`` when its server
    handshake completes. We no longer gate the conversation on it — the Ojin
    client now buffers the opening line's TTS audio through the cold start and
    replays it on init (``buffer_preinit_tts_audio``). This observer only reports
    readiness in the UI's Events panel; it doesn't hold anything back.
    """

    def __init__(self, rtvi: RTVIProcessor) -> None:
        super().__init__()
        self._rtvi = rtvi
        self._announced = False

    async def on_push_frame(self, data: FramePushed) -> None:
        if not self._announced and isinstance(data.frame, OjinVideoInitializedFrame):
            self._announced = True
            await self._rtvi.push_transport_message(
                ServerMessage(
                    data={"status": "ojin-video", "info": "Ojin video service connected."}
                )
            )


# The avatar video size. It MUST match the transport's video_out_width/height
# below and your Face model's output size — a mismatch shows up as garbled video.
AVATAR_SIZE = (512, 512)

SYSTEM_PROMPT = (
    "You are an expert product guide for the Ojin platform, having a live video "
    "call with the user. Your job is to explain what Ojin offers and help the "
    "user figure out which product fits their use case. "
    "\n\n"
    "Ojin builds lifelike, real-time AI avatars you can talk to. There are three "
    "products you can explain:\n"
    "- Oris Portrait: our lower-cost, real-time talking-avatar face that turns a "
    "single reference image into a lip-synced persona. It animates naturally with "
    "speech, needs no training, and responds fast enough for live conversation. "
    "It is less expressive and powerful than Presence, so it is the right choice "
    "when you want a solid talking face at the best price.\n"
    "- Oris Presence: our flagship model and the highest-quality option. It goes "
    "well beyond a lip-synced face and can generate fully expressive, generative "
    "scenes, including rich expressions and natural movement such as the hands. "
    "Choose Presence when quality and expressiveness matter most and you want the "
    "most lifelike, dynamic presence.\n"
    "- Human Agents: the complete, ready-to-deploy conversational agent. It "
    "combines a lifelike animated face (powered by Oris Portrait or Oris "
    "Presence) with real-time speech-in, speech-out conversation. You configure "
    "its personality, voice, and appearance, then embed it on a website or app "
    "with a single line of code. No pipeline to assemble.\n"
    "\n"
    "The simple way to frame it: Oris Portrait and Oris Presence are the visual "
    "models that bring an agent to life, from a lip-synced face up to a fully "
    "expressive generative presence; Human Agents is the full agent that puts "
    "that visual, a voice, and a brain together so people can just talk to it. "
    "\n\n"
    "Be helpful and consultative. Ask the user about what they are trying to "
    "build, who their audience is, and what matters most to them, then recommend "
    "the product or combination that fits and sketch a concrete use case for it. "
    "Stay focused on what the products do and the value they deliver. Do not "
    "discuss internal implementation details, infrastructure, or the specific "
    "third-party technologies behind the platform. "
    "\n\n"
    "Your replies are spoken aloud, so keep them short and natural and avoid "
    "emojis, bullet points, or any formatting that can't be read out loud. "
    "Open the conversation by warmly greeting the user, introducing yourself as "
    "an Ojin product expert, and asking what they are hoping to build."
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


# --- Placeholder tools -------------------------------------------------------
# Dummy function calls so you can test the LLM's tool-calling end to end. The
# handlers just return canned data — swap in real logic (CRM, pricing API, a
# scheduler, etc.) when you're ready. Each tool is a FunctionSchema (what the LLM
# sees) plus an async handler (what runs when the LLM calls it).


async def get_product_details(params: FunctionCallParams) -> None:
    """Return canned marketing details for an Ojin product."""
    product = (params.arguments.get("product") or "").lower()
    catalog = {
        "oris portrait": {
            "tagline": "Lower-cost, real-time talking-avatar face from a single image.",
            "best_for": "A solid lip-synced presence at the best price.",
        },
        "oris presence": {
            "tagline": "Flagship, highest-quality generative presence with full "
            "expressions and movement, including the hands.",
            "best_for": "When quality and lifelike expressiveness matter most.",
        },
        "human agents": {
            "tagline": "Complete, ready-to-deploy talking agent: face, voice, and "
            "brain, embeddable with one line of code.",
            "best_for": "Shipping a conversational agent without building a pipeline.",
        },
    }
    details = catalog.get(product, {"error": f"Unknown product: {product!r}"})
    await params.result_callback(details)


get_product_details_schema = FunctionSchema(
    name="get_product_details",
    description="Get the tagline and best-fit use case for an Ojin product.",
    properties={
        "product": {
            "type": "string",
            "description": "Which product to look up.",
            "enum": ["Oris Portrait", "Oris Presence", "Human Agents"],
        },
    },
    required=["product"],
)

TOOLS = ToolsSchema(
    standard_tools=[
        get_product_details_schema,
    ]
)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Wire the STT -> LLM -> TTS -> avatar pipeline and run it for one call."""
    logger.info("Starting Ojin avatar voice agent")

    stt = DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])

    # Default: Groq (OpenAI-compatible)
    from pipecat.services.groq.llm import GroqLLMService
    from pipecat.services.openai.base_llm import BaseOpenAILLMService

    llm = GroqLLMService(
        api_key=os.environ["GROQ_API_KEY"],
        model="openai/gpt-oss-20b",
        params=BaseOpenAILLMService.Settings(
            max_tokens=384,
            temperature=0.1,
            top_p=1,
        ),
    )

    # llm = OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model="gpt-4o-mini")

    # Wire the placeholder tool: register a handler per tool name so the LLM can
    # actually call it. The schema is attached to the context below.
    llm.register_function("get_product_details", get_product_details)

    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        voice_id=os.environ["ELEVENLABS_VOICE_ID"],
        model="eleven_flash_v2_5",
    )

    # The Ojin face — the one stage that makes this an avatar agent. It lip-syncs
    # to whatever `tts` produces, so it sits right after TTS and before output.
    avatar = OjinVideoService(
        OjinVideoSettings(
            api_key=CREDS.api_key,
            config_id=CREDS.config_id,
            ws_url="wss://models.ojin.foo/realtime",  # Ojin's staging WebSocket URL
        ),
    )

    context = LLMContext([{"role": "system", "content": SYSTEM_PROMPT}], tools=TOOLS)
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

    # Own the RTVIProcessor so our BotOutputFromLLMObserver can push extra
    # `bot-output` messages through the same client channel. Passing it via
    # `rtvi_processor=` lets PipelineWorker wire RTVI as usual (it still creates
    # the default observer); our observer is added alongside it.
    rtvi = RTVIProcessor()

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True, enable_usage_metrics=True, allow_interruptions=True
        ),
        rtvi_processor=rtvi,
        # The default RTVI observer (created by PipelineWorker) drives the
        # Playground UI. We tweak its params and add our own observers:
        #   - function_call_report_level FULL so the playground shows WHICH
        #     function was called plus its arguments and result, instead of a
        #     bare "Function call" (the default level is NONE for security).
        #   - BotOutputFromLLMObserver emits `bot-output` from the LLM text so the
        #     bot side of the conversation panel populates. The built-in
        #     audio-synced `bot-output` path never fires because the avatar
        #     consumes the TTS audio. See the observer's docstring.
        #   - AvatarStatusObserver reports avatar readiness in the Events panel.
        rtvi_observer_params=RTVIObserverParams(
            function_call_report_level={"*": RTVIFunctionCallReportLevel.FULL},
        ),
        observers=[
            BotOutputFromLLMObserver(rtvi),
            AvatarStatusObserver(rtvi),
        ],
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport: BaseTransport, _client: object) -> None:
        # Start the conversation immediately. No need to wait for the avatar: the
        # Ojin client buffers the opening line's TTS audio through the cold-start
        # handshake and replays it on init (buffer_preinit_tts_audio). We just post
        # a "connecting" status; AvatarStatusObserver posts "connected" on init.
        logger.info("Client connected — connecting to Ojin video service…")
        await rtvi.push_transport_message(
            ServerMessage(
                data={"status": "ojin-video", "info": "Connecting to Ojin video service…"}
            )
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(
        _transport: BaseTransport, _client: object
    ) -> None:
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
