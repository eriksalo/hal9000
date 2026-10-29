"""Application context: long-lived resources plus conversation orchestration.

Used by every entry point. The autonomous controller adds the presence
monitor; the dev entry points just start a session for a named person.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable

import aiohttp
import anthropic
from loguru import logger
from pipecat.transports.base_transport import BaseTransport

from hal.config import HALConfig
from hal.connectivity import is_online
from hal.memory.semantic import SemanticMemory, build_mem0_config
from hal.memory.store import MemoryStore
from hal.pipeline import HALSession, ServiceProfile, SessionDeps, SessionOpening
from hal.state import HALState
from hal.vision.camera import Camera
from hal.vision.faces import UNKNOWN, FaceRecognizer
from hal.vision.presence import PresenceMonitor
from hal.vision.tracker import PresenceEvent
from hal.wake import WakeWordListener, choose_wake_person

TransportFactory = Callable[[], BaseTransport]


def configure_logging(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), enqueue=True)


class AppContext:
    def __init__(self, config: HALConfig, *, transport_factory: TransportFactory | None = None, enable_vision: bool = True):
        self.config = config
        self.state = HALState()
        self.store = MemoryStore(config.memory.base_dir)
        self.anthropic = anthropic.AsyncAnthropic(api_key=config.llm.api_key)
        self.http: aiohttp.ClientSession | None = None
        self.transport_factory = transport_factory
        self.semantic = SemanticMemory(
            build_mem0_config(
                qdrant_path=config.memory.qdrant_path,
                embedder_model=config.memory.embedder_model,
                anthropic_api_key=config.llm.api_key,
                llm_model=config.llm.side_model,
            ),
            enabled=config.memory.semantic_enabled,
            recall_limit=config.memory.recall_limit,
        )
        self.camera: Camera | None = None
        self.recognizer: FaceRecognizer | None = None
        self.presence: PresenceMonitor | None = None
        if enable_vision and config.vision.enabled:
            self.camera = Camera(config.vision)
            self.recognizer = FaceRecognizer(config.vision.face_database, tolerance=config.vision.face_tolerance)
            self.presence = PresenceMonitor(config.vision, camera=self.camera, recognizer=self.recognizer)
            self.presence.on_presence(self._on_presence)
        self.wake: WakeWordListener | None = None
        if config.wake.enabled:
            self.wake = WakeWordListener(
                config.wake, config.audio, on_wake=self._on_wake_word, on_armed_change=self._on_wake_armed
            )
        self.session: HALSession | None = None
        self._session_task: asyncio.Task | None = None
        self._session_lock = asyncio.Lock()
        self._departure_timer: asyncio.Task | None = None
        self._esp32_last_seen: tuple[str, float] | None = None
        self.current_profile: ServiceProfile | None = None
        self._display_name_until = 0.0
        self._display_task: asyncio.Task | None = None

    # ---- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        self.http = aiohttp.ClientSession()
        if self.presence:
            await self.presence.start()
            self._display_task = asyncio.create_task(self._display_name_loop(), name="hal-display-name")
        if self.wake:
            try:
                await self.wake.start(asyncio.get_running_loop())
            except Exception as exc:
                logger.error(f"Wake word unavailable ({exc}); HAL will greet on arrival instead")
                self.wake = None
        logger.info("HAL application context started")

    async def stop(self) -> None:
        await self.end_conversation("shutdown")
        if self._session_task:
            try:
                await asyncio.wait_for(self._session_task, timeout=20)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        if self.wake:
            await self.wake.stop()
        if self._display_task:
            self._display_task.cancel()
            try:
                await self._display_task
            except asyncio.CancelledError:
                pass
            self._display_task = None
        if self.presence:
            await self.presence.stop()
        elif self.camera:
            self.camera.stop()
        if self.http:
            await self.http.close()
        logger.info("HAL application context stopped")

    # ---- conversations -----------------------------------------------------------

    def _deps(self) -> SessionDeps:
        assert self.http is not None, "AppContext.start() not called"
        return SessionDeps(
            config=self.config,
            store=self.store,
            semantic=self.semantic,
            anthropic=self.anthropic,
            http=self.http,
            state=self.state,
            camera=self.camera,
            identify_person=self._identify_person if self.recognizer else None,
        )

    async def start_conversation(
        self,
        person_name: str,
        *,
        transport: BaseTransport | None = None,
        opening: SessionOpening = "presence",
    ) -> bool:
        """Start a session for ``person_name``; returns False if one is already running.

        ``opening`` selects HAL's first line: a greeting for someone who appeared on
        camera, or an acknowledgement for someone who said the wake phrase.
        """
        async with self._session_lock:
            if self.session is not None and not self.session._done.is_set():
                logger.info(f"Busy with {self.session.person_name}; not starting {person_name}")
                return False
            transport = transport or (self.transport_factory() if self.transport_factory else None)
            if transport is None:
                raise RuntimeError("No transport available for conversation")
            online = await is_online()
            self.current_profile = ServiceProfile.select(self.config, online=online)
            if not online and not self.config.hailo.enabled:
                logger.warning("Offline and Hailo fallback disabled; conversation will likely fail")
            self.session = HALSession(
                self._deps(), transport, person_name=person_name, profile=self.current_profile, opening=opening
            )
            if self.presence:
                self.presence.tracker.mark_in_conversation(person_name, True)
            if self.wake:
                self.wake.pause()
            self._session_task = asyncio.create_task(self._run_session(self.session), name=f"hal-session-{person_name}")
            return True

    async def _run_session(self, session: HALSession) -> None:
        try:
            await session.run()
        finally:
            if self.wake:
                self.wake.resume()
            if self.presence:
                self.presence.tracker.mark_in_conversation(session.person_name, False)
            if self.session is session:
                self.session = None

    async def end_conversation(self, reason: str) -> None:
        if self.session:
            await self.session.end(reason)

    async def say(self, text: str) -> bool:
        if not self.session:
            return False
        await self.session.say(text)
        return True

    async def wait_for_session(self) -> None:
        if self._session_task:
            await self._session_task

    # ---- presence --------------------------------------------------------------------

    async def _on_presence(self, event: PresenceEvent) -> None:
        tracker = self.presence.tracker if self.presence else None
        self.state.people_present = tracker.present() if tracker else []

        session = self.session
        if session is None:
            # With a wake word, conversations start on the wake phrase, not on
            # mere presence. Without one, greet whoever arrives.
            if self.wake is None:
                for name in event.arrived:
                    if await self.start_conversation(name):
                        break
            return

        if event.arrived or event.departed:
            await session.notify_presence(event.arrived, event.departed)

        partner = session.person_name
        if partner in event.departed and self._departure_timer is None:
            self._departure_timer = asyncio.create_task(self._end_after_departure(session), name="hal-departure")
        elif partner in event.arrived or (tracker and partner in tracker.present()):
            self._cancel_departure_timer()

    async def _end_after_departure(self, session: HALSession) -> None:
        grace = max(self.config.vision.departure_threshold_secs, 5.0)
        try:
            await asyncio.sleep(grace)
            tracker = self.presence.tracker if self.presence else None
            if tracker and session.person_name in tracker.present():
                return
            logger.info(f"{session.person_name} left the camera view; ending conversation")
            await session.end("person_departed")
        finally:
            self._departure_timer = None

    def _cancel_departure_timer(self) -> None:
        if self._departure_timer:
            self._departure_timer.cancel()
            self._departure_timer = None

    # ---- wake word -------------------------------------------------------------------

    async def _on_wake_word(self) -> None:
        self.state.last_wake_at = time.time()
        if self.session is not None and not self.session._done.is_set():
            return
        name = self._wake_person_name()
        logger.info(f"Wake word -> starting conversation with {name}")
        await self.start_conversation(name, opening="wake")

    def _wake_person_name(self) -> str:
        tracker = self.presence.tracker if self.presence else None
        return choose_wake_person(
            known_present=tracker.present_known() if tracker else [],
            present=tracker.present() if tracker else [],
            default_person=self.config.default_person,
        )

    def _on_wake_armed(self, armed: bool) -> None:
        self.state.wake_armed = armed

    # ---- display name hold -----------------------------------------------------------

    async def _display_name_loop(self) -> None:
        """Show a recognised person's name, holding it after they leave."""
        hold = self.config.vision.name_hold_secs
        while True:
            try:
                tracker = self.presence.tracker if self.presence else None
                known = tracker.present_known() if tracker else []
                now = time.time()
                if known:
                    self.state.display_name = known[0]
                    self._display_name_until = now + hold
                elif self.state.display_name and now >= self._display_name_until:
                    self.state.display_name = None
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(f"Display-name loop error: {exc}")
                await asyncio.sleep(1.0)

    # ---- faces ------------------------------------------------------------------------

    async def _identify_person(self, name: str) -> bool:
        return self.register_last_unknown_face(name)

    def register_last_unknown_face(self, name: str) -> bool:
        if not (self.presence and self.recognizer):
            return False
        encoding = self.presence.last_unknown_encoding
        if encoding is None:
            return False
        self.recognizer.register(name, encoding)
        tracker = self.presence.tracker
        if UNKNOWN in tracker.tracked:
            person = tracker.tracked.pop(UNKNOWN)
            person.name = name
            tracker.tracked[name] = person
        self.state.people_present = tracker.present()
        return True

    # ---- status helpers ------------------------------------------------------------------

    def note_esp32(self, remote: str | None) -> None:
        if remote:
            self._esp32_last_seen = (remote, time.time())

    def esp32_info(self) -> dict:
        if not self._esp32_last_seen:
            return {"connected": False}
        ip, seen = self._esp32_last_seen
        return {"connected": time.time() - seen < 15, "ip": ip, "last_seen_secs_ago": round(time.time() - seen, 1)}

    def service_profile_info(self) -> dict:
        profile = self.current_profile or ServiceProfile.select(self.config, online=True)
        return {**profile.as_dict(), "llm": self.config.llm.model, "side_model": self.config.llm.side_model}
