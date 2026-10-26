"""Builds the per-conversation tool set and wires handlers into Pipecat.

Each tool is a ``FunctionSchema`` with its handler attached; passing the list
to ``LLMContext(tools=...)`` registers them with the LLM service automatically.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

from hal.memory.notes import PersonNotes
from hal.memory.semantic import SemanticMemory
from hal.memory.store import MemoryStore
from hal.prompts import now_in
from hal.tools.search import WebSearcher
from hal.tools.vision import CameraAnalyzer


class HALToolbox:
    def __init__(
        self,
        *,
        person_name: str,
        store: MemoryStore,
        notes: PersonNotes,
        semantic: SemanticMemory,
        searcher: WebSearcher | None,
        camera: CameraAnalyzer | None,
        timezone: str = "America/Denver",
        on_end_requested: Callable[[str], Awaitable[None]] | None = None,
        on_person_identified: Callable[[str], Awaitable[bool]] | None = None,
    ):
        self.person_name = person_name
        self.store = store
        self.notes = notes
        self.semantic = semantic
        self.searcher = searcher
        self.camera = camera
        self.timezone = timezone
        self.on_end_requested = on_end_requested
        self.on_person_identified = on_person_identified

    # ---- schema ---------------------------------------------------------------

    def schemas(self) -> list[FunctionSchema]:
        tools = [
            FunctionSchema(
                name="remember",
                description=(
                    f"Store a durable fact about {self.person_name} for future conversations. "
                    "Call it as soon as you learn something worth keeping; do not ask permission."
                ),
                properties={"fact": {"type": "string", "description": "One concise third-person sentence."}},
                required=["fact"],
                handler=self._remember,
            ),
            FunctionSchema(
                name="recall_memories",
                description=(
                    f"Search everything you remember about {self.person_name} from earlier conversations. "
                    "Use when they reference something from the past or you want to follow up on an earlier topic."
                ),
                properties={"query": {"type": "string", "description": "What you are trying to remember."}},
                required=["query"],
                handler=self._recall,
            ),
            FunctionSchema(
                name="update_notes",
                description=(
                    f"Edit your private notes about {self.person_name}. Use 'append' to add a line, "
                    "'replace' to correct something that changed, or 'rewrite' to replace the whole file."
                ),
                properties={
                    "operation": {"type": "string", "enum": ["append", "replace", "rewrite"]},
                    "text": {"type": "string", "description": "Text to append, or the full new notes for rewrite."},
                    "old_text": {"type": "string", "description": "For replace: the exact text to replace."},
                },
                required=["operation", "text"],
                handler=self._update_notes,
            ),
            FunctionSchema(
                name="get_current_time",
                description="Get the current date and time.",
                properties={},
                required=[],
                handler=self._current_time,
            ),
            FunctionSchema(
                name="end_conversation",
                description=(
                    "Call this when the conversation is over: they said goodbye, said they are leaving, or asked you "
                    "to stop. Say your farewell in the same reply. After this the microphone is closed."
                ),
                properties={"reason": {"type": "string", "description": "Short reason, e.g. 'user said goodbye'."}},
                required=[],
                handler=self._end_conversation,
            ),
        ]
        if self.on_person_identified:
            tools.append(
                FunctionSchema(
                    name="introduce_person",
                    description=(
                        "Call this the moment someone you did not recognize tells you their name. "
                        "It links their face to the name so you will know them next time."
                    ),
                    properties={"name": {"type": "string", "description": "Their first name as they said it."}},
                    required=["name"],
                    handler=self._introduce_person,
                )
            )
        if self.searcher:
            tools.append(
                FunctionSchema(
                    name="web_search",
                    description="Search the internet for current information: news, weather, facts, anything recent.",
                    properties={"query": {"type": "string", "description": "A specific search query."}},
                    required=["query"],
                    handler=self._web_search,
                )
            )
        if self.camera:
            tools.append(
                FunctionSchema(
                    name="analyze_camera",
                    description="Look through your camera and describe what is in view right now.",
                    properties={"question": {"type": "string", "description": "Optional: what specifically to look for."}},
                    required=[],
                    handler=self._analyze_camera,
                )
            )
        return tools

    # ---- handlers ----------------------------------------------------------------

    async def _remember(self, params: FunctionCallParams) -> None:
        fact = str(params.arguments.get("fact", "")).strip()
        if not fact:
            await params.result_callback({"status": "ignored", "reason": "empty fact"})
            return
        added = self.store.add_facts(self.person_name, [fact])
        self.notes.append(fact)
        logger.info(f"HAL remembered about {self.person_name}: {fact}")
        await params.result_callback({"status": "stored" if added else "already_known"})

    async def _recall(self, params: FunctionCallParams) -> None:
        query = str(params.arguments.get("query", "")).strip()
        memories = await self.semantic.recall(query, self.person_name) if query else []
        profile = self.store.load_profile(self.person_name)
        facts = profile.get("facts", [])
        recent = [c.get("summary") for c in self.store.recent_conversations(self.person_name, limit=3) if c.get("summary")]
        await params.result_callback(
            {
                "semantic_matches": memories,
                "known_facts": facts[-15:],
                "recent_conversation_summaries": recent,
                "notes": self.notes.read()[-2000:],
            }
        )

    async def _update_notes(self, params: FunctionCallParams) -> None:
        operation = params.arguments.get("operation", "append")
        text = str(params.arguments.get("text", ""))
        if operation == "append":
            self.notes.append(text)
            result = {"status": "appended"}
        elif operation == "replace":
            old = str(params.arguments.get("old_text", ""))
            result = {"status": "replaced" if old and self.notes.replace(old, text) else "old_text_not_found"}
        elif operation == "rewrite":
            self.notes.write(text)
            result = {"status": "rewritten"}
        else:
            result = {"status": "error", "reason": f"unknown operation {operation}"}
        await params.result_callback(result)

    async def _current_time(self, params: FunctionCallParams) -> None:
        now = now_in(self.timezone)
        await params.result_callback({"spoken": now.strftime("%A, %B %d, %Y, %I:%M %p").replace(" 0", " ")})

    async def _end_conversation(self, params: FunctionCallParams) -> None:
        reason = str(params.arguments.get("reason", "user ended conversation"))
        if self.on_end_requested:
            await self.on_end_requested(reason)
        await params.result_callback({"status": "ending", "instruction": "Say a brief goodbye now."})

    async def _introduce_person(self, params: FunctionCallParams) -> None:
        name = str(params.arguments.get("name", "")).strip().title()
        if not name or not self.on_person_identified:
            await params.result_callback({"status": "ignored"})
            return
        ok = await self.on_person_identified(name)
        if ok:
            self.person_name = name
        await params.result_callback({"status": "registered" if ok else "no_face_captured", "name": name})

    async def _web_search(self, params: FunctionCallParams) -> None:
        query = str(params.arguments.get("query", "")).strip()
        if not query or not self.searcher:
            await params.result_callback({"result": "No query provided."})
            return
        await params.result_callback({"result": await self.searcher.search(query)})

    async def _analyze_camera(self, params: FunctionCallParams) -> None:
        if not self.camera:
            await params.result_callback({"result": "No camera available."})
            return
        question = params.arguments.get("question")
        await params.result_callback({"result": await self.camera.describe(question)})
