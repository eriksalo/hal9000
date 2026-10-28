"""One HAL conversation = one :class:`HALSession` wrapping a Pipecat pipeline.

    transport.input -> STT -> user aggregator -> LLM -> TTS -> transport.output -> assistant aggregator

Everything per-person (prompt, tools, transcript, memory write-back) lives here.
Long-lived resources (config, memory store, camera, API clients) are passed in
via :class:`SessionDeps` and shared across sessions.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import aiohttp
import anthropic
from loguru import logger
from pipecat.frames.frames import EndFrame, LLMMessagesAppendFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.base_transport import BaseTransport
from pipecat.utils.types import NOT_GIVEN

from hal.config import HALConfig, STTProvider, TTSProvider
from hal.memory.extraction import ConversationReflector
from hal.memory.notes import PersonNotes
from hal.memory.semantic import SemanticMemory
from hal.memory.store import ConversationRecord, MemoryStore
from hal.prompts import (
    conversation_system_prompt,
    greeting_instruction,
    presence_update,
    unknown_person_instruction,
)
from hal.services.llm import build_claude, build_offline_llm
from hal.services.audio_gain import InputGainProcessor
from hal.services.stt import build_stt, build_user_turn_strategies, build_vad, stt_provides_turn_detection
from hal.services.tts import build_tts
from hal.state import HALState
from hal.tools.registry import HALToolbox
from hal.tools.search import WebSearcher
from hal.tools.vision import CameraAnalyzer
from hal.vision.camera import Camera
from hal.vision.faces import UNKNOWN

MAX_IDLE_NUDGES = 2


@dataclass(frozen=True)
class ServiceProfile:
    """Which concrete services a session uses; chosen per session from connectivity."""

    stt: STTProvider
    tts: TTSProvider
    offline: bool = False

    @staticmethod
    def select(config: HALConfig, *, online: bool) -> "ServiceProfile":
        if online:
            return ServiceProfile(stt=config.stt.provider, tts=config.tts.provider)
        stt = "hailo" if config.hailo.enabled else config.stt.fallback_provider
        return ServiceProfile(stt=stt, tts="piper", offline=True)

    def as_dict(self) -> dict:
        return {"stt": self.stt, "tts": self.tts, "offline": self.offline}


@dataclass
class SessionDeps:
    config: HALConfig
    store: MemoryStore
    semantic: SemanticMemory
    anthropic: anthropic.AsyncAnthropic
    http: aiohttp.ClientSession
    state: HALState
    camera: Camera | None = None
    identify_person: Callable[[str], Awaitable[bool]] | None = None


class HALSession:
    def __init__(
        self,
        deps: SessionDeps,
        transport: BaseTransport,
        *,
        person_name: str,
        profile: ServiceProfile,
    ):
        self.deps = deps
        self.config = deps.config
        self.transport = transport
        self.person_name = person_name
        self.profile = profile
        self.record: ConversationRecord | None = None
        self.task: PipelineTask | None = None
        self._runner: PipelineRunner | None = None
        self._ending = False
        self._end_reason = "completed"
        self._idle_nudges = 0
        self._toolbox: HALToolbox | None = None
        self._done = asyncio.Event()

    @property
    def is_unknown(self) -> bool:
        return self.person_name == UNKNOWN

    # ---- lifecycle -----------------------------------------------------------

    async def run(self) -> None:
        """Build, run to completion, then write memory. Safe to call once."""
        state = self.deps.state
        try:
            task = await self._build()
            state.person = None if self.is_unknown else self.person_name
            state.in_conversation = True
            state.online = not self.profile.offline
            state.set_mode("thinking")
            await task.queue_frames([self._opening_frame()])
            self._runner = PipelineRunner(handle_sigint=False)
            await self._runner.run(task)
        except Exception as exc:
            logger.exception(f"Session with {self.person_name} crashed: {exc}")
            self._end_reason = f"error: {exc}"
        finally:
            await self._finish()
            state.in_conversation = False
            state.person = None
            state.set_mode("idle")
            self._done.set()

    async def wait(self) -> None:
        await self._done.wait()

    async def end(self, reason: str = "requested") -> None:
        if self._ending:
            return
        self._ending = True
        self._end_reason = reason
        if self.task:
            logger.info(f"Ending conversation with {self.person_name}: {reason}")
            await self.task.queue_frame(EndFrame())

    async def say(self, text: str) -> None:
        if self.task:
            await self.task.queue_frame(TTSSpeakFrame(text=text))

    async def notify_presence(self, arrived: list[str], departed: list[str]) -> None:
        """Tell HAL the camera saw people change, without forcing a reply."""
        if not self.task or self._ending:
            return
        note = presence_update(arrived, departed)
        await self.task.queue_frame(
            LLMMessagesAppendFrame(messages=[{"role": "user", "content": f"[Camera note] {note}"}], run_llm=False)
        )

    # ---- build ---------------------------------------------------------------

    async def _build(self) -> PipelineTask:
        cfg = self.config
        deps = self.deps

        notes = PersonNotes(deps.store.person_dir(self.person_name))
        if not self.is_unknown:
            self.record = deps.store.start_conversation(self.person_name)
            seed_memories = await deps.semantic.recall(f"important things about {self.person_name}", self.person_name)
            profile_summary = deps.store.profile_summary(self.person_name)
        else:
            self.record = ConversationRecord(person_name=UNKNOWN, started_at=datetime.now())
            seed_memories, profile_summary = [], ""

        system_prompt = conversation_system_prompt(
            self.person_name,
            notes=notes.read(),
            profile_summary=profile_summary,
            semantic_memories=seed_memories,
            timezone=cfg.timezone,
        )

        searcher = WebSearcher(deps.anthropic, model=cfg.llm.side_model) if (cfg.llm.enable_web_search and not self.profile.offline) else None
        camera = (
            CameraAnalyzer(deps.anthropic, deps.camera, model=cfg.llm.side_model)
            if (deps.camera and cfg.llm.enable_vision and not self.profile.offline)
            else None
        )
        self._toolbox = HALToolbox(
            person_name=self.person_name,
            store=deps.store,
            notes=notes,
            semantic=deps.semantic,
            searcher=searcher,
            camera=camera,
            timezone=cfg.timezone,
            on_end_requested=self._on_end_requested,
            on_person_identified=self._on_person_identified if (self.is_unknown and deps.identify_person) else None,
        )

        context = LLMContext(
            messages=[{"role": "system", "content": system_prompt}],
            # The small offline model gets no tools; NOT_GIVEN keeps `tools` out of the request entirely.
            tools=self._toolbox.schemas() if not self.profile.offline else NOT_GIVEN,
        )

        stt = build_stt(cfg, provider=self.profile.stt)
        llm = build_offline_llm(cfg) if self.profile.offline else build_claude(cfg)
        tts = build_tts(cfg, session=deps.http, provider=self.profile.tts)

        aggregators = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=None if stt_provides_turn_detection(self.profile.stt) else build_vad(cfg),
                user_turn_strategies=build_user_turn_strategies(cfg, provider=self.profile.stt),
                user_idle_timeout=cfg.turn.idle_timeout_secs,
            ),
        )
        self._wire_events(aggregators)

        input_stage = [self.transport.input()]
        a = cfg.audio
        if a.input_gain != 1.0 or a.input_gate_rms > 0.0 or a.input_target_rms > 0.0:
            input_stage.append(
                InputGainProcessor(
                    gain=a.input_gain,
                    gate_rms=a.input_gate_rms,
                    target_rms=a.input_target_rms,
                    max_gain=a.input_max_gain,
                )
            )
        pipeline = Pipeline(
            [
                *input_stage,
                stt,
                aggregators.user(),
                llm,
                tts,
                self.transport.output(),
                aggregators.assistant(),
            ]
        )
        self.task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
                audio_in_sample_rate=cfg.audio.sample_rate,
                audio_out_sample_rate=cfg.audio.output_sample_rate,
            ),
            idle_timeout_secs=cfg.turn.idle_timeout_secs * (MAX_IDLE_NUDGES + 2),
            cancel_on_idle_timeout=True,
        )

        @self.task.event_handler("on_idle_timeout")
        async def _on_idle(task: PipelineTask) -> None:
            logger.info("Pipeline idle timeout; ending conversation")
            self._end_reason = "idle_timeout"

        return self.task

    def _opening_frame(self) -> LLMMessagesAppendFrame:
        if self.is_unknown:
            instruction = unknown_person_instruction(self.config.timezone)
        else:
            first = self.deps.store.load_profile(self.person_name).get("conversation_count", 0) <= 1
            instruction = greeting_instruction(self.person_name, is_first_meeting=first, timezone=self.config.timezone)
        return LLMMessagesAppendFrame(messages=[{"role": "user", "content": f"[System] {instruction}"}], run_llm=True)

    # ---- events --------------------------------------------------------------

    def _wire_events(self, aggregators: LLMContextAggregatorPair) -> None:
        state = self.deps.state
        user = aggregators.user()
        assistant = aggregators.assistant()

        @user.event_handler("on_user_turn_started")
        async def _user_started(*_) -> None:
            self._idle_nudges = 0
            state.set_mode("listening")

        @user.event_handler("on_user_turn_stopped")
        async def _user_stopped(*_) -> None:
            state.set_mode("thinking")

        @user.event_handler("on_user_turn_message_added")
        async def _user_message(_, message) -> None:
            text = (message.content or "").strip()
            if text and not text.startswith("[System]") and not text.startswith("[Camera note]"):
                logger.info(f"{self.person_name}: {text}")
                state.last_user_text = text
                if self.record:
                    self.record.add(self.person_name, text)

        @user.event_handler("on_user_turn_idle")
        async def _user_idle(*_) -> None:
            await self._handle_idle()

        @assistant.event_handler("on_assistant_turn_started")
        async def _hal_started(*_) -> None:
            state.set_mode("speaking")

        @assistant.event_handler("on_assistant_turn_stopped")
        async def _hal_stopped(_, message) -> None:
            text = (message.content or "").strip()
            if text:
                logger.info(f"HAL: {text}" + (" (interrupted)" if getattr(message, "interrupted", False) else ""))
                state.last_hal_text = text
                if self.record:
                    self.record.add("HAL", text)
            state.set_mode("idle" if self._ending else "listening")
            # A tool-only turn can stop with empty content before the goodbye is spoken; wait for text.
            if self._ending and text and self.task:
                await self.task.queue_frame(EndFrame())

    async def _handle_idle(self) -> None:
        if self._ending or not self.task:
            return
        self._idle_nudges += 1
        if self._idle_nudges > MAX_IDLE_NUDGES:
            logger.info(f"{self.person_name} silent too long; ending")
            await self.end("silence")
            return
        prompt = (
            f"[System] {self.person_name} has been silent for a while. Briefly check whether they are still there, "
            "or say goodbye if it seems they have left. One sentence."
        )
        await self.task.queue_frame(LLMMessagesAppendFrame(messages=[{"role": "user", "content": prompt}], run_llm=True))

    async def _on_end_requested(self, reason: str) -> None:
        # HAL will speak its goodbye in the same turn; the EndFrame goes out when that turn stops.
        self._ending = True
        self._end_reason = reason
        logger.info(f"HAL requested end of conversation: {reason}")
        asyncio.create_task(self._forced_end_after(15.0), name="hal-forced-end")

    async def _forced_end_after(self, delay: float) -> None:
        """Safety net: if the goodbye never materialises, close the session anyway."""
        await asyncio.sleep(delay)
        if self.task and not self._done.is_set():
            logger.warning("Goodbye turn did not complete in time; forcing EndFrame")
            await self.task.queue_frame(EndFrame())

    async def _on_person_identified(self, name: str) -> bool:
        if not self.deps.identify_person:
            return False
        ok = await self.deps.identify_person(name)
        if ok:
            logger.info(f"Unknown person identified as {name}")
            self.person_name = name
            self.deps.state.person = name
            if self.record:
                self.record.person_name = name
            if self._toolbox:
                self._toolbox.notes = PersonNotes(self.deps.store.person_dir(name))
            self.deps.store.start_conversation(name)
        return ok

    # ---- memory write-back -----------------------------------------------------------

    async def _finish(self) -> None:
        record = self.record
        if record is None or not record.utterances or record.person_name == UNKNOWN:
            if record and record.person_name == UNKNOWN:
                logger.info("Conversation with an unidentified person; nothing persisted")
            return
        deps = self.deps
        notes = PersonNotes(deps.store.person_dir(record.person_name))
        if not self.profile.offline:
            reflector = ConversationReflector(deps.anthropic, model=self.config.llm.side_model)
            reflection = await reflector.reflect(record.person_name, record.transcript(), notes.read())
            record.extracted_facts = reflection.facts
            record.summary = reflection.summary
            record.mood = reflection.mood
            record.open_threads = reflection.open_threads
            for fact in reflection.facts:
                notes.append(fact)
        deps.store.finish_conversation(record, self._end_reason)
        deps.state.conversation_count += 1
        if not self.profile.offline:
            asyncio.create_task(deps.semantic.ingest(record.as_messages(), record.person_name), name="hal-mem0-ingest")
