#!/usr/bin/env python3
"""
HAL 9000 Autonomous Controller (Pipecat Version)

Fully autonomous HAL system that:
1. Monitors camera for faces
2. Detects and tracks people
3. Initiates conversations using Pipecat pipeline
4. Manages conversation lifecycle
5. Persists memories

This replaces the original hal_controller.py with Pipecat-based implementation.
"""

import asyncio
import os
import sys
from typing import Optional, Dict
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

# Import Pipecat components
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import (
    LLMAssistantResponseAggregator,
    LLMUserResponseAggregator
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import Frame, TextFrame, EndFrame
from pipecat.services.anthropic import AnthropicLLMService
from pipecat.transports.local.audio import LocalAudioTransport
from pipecat.transports.base_transport import TransportParams

# Import HAL services
from hal_piper_tts import HALPiperTTSServiceHTTP
from hal_whisper_stt import HALVoskSTTService
from hal_tools import create_tool_handler
from hal_controller_bridge import HALControllerBridge

# Import shared components
from memory_store import MemoryStore
from prompts import get_conversation_system_prompt, get_greeting_prompt

# Load environment
load_dotenv()

# Configure logger
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("/home/erik/hal9000/backend_pipecat/hal_autonomous.log", level="DEBUG", rotation="10 MB")


class ConversationFrameProcessor(FrameProcessor):
    """
    Frame processor for conversation management.
    Handles memory persistence and conversation state.
    """

    def __init__(self, memory_store: MemoryStore, person_name: str):
        super().__init__()
        self.memory_store = memory_store
        self.person_name = person_name
        self.conversation_transcript = []
        self.conversation_active = True

        logger.info(f"Conversation started with {person_name}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames and capture conversation."""

        # Capture user messages
        if isinstance(frame, TextFrame) and direction == FrameDirection.UPSTREAM:
            self.conversation_transcript.append({
                "role": "user",
                "content": frame.text,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"{self.person_name}: {frame.text}")

        # Capture assistant messages
        elif isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            self.conversation_transcript.append({
                "role": "assistant",
                "content": frame.text,
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"HAL: {frame.text}")

        # Save conversation on end
        elif isinstance(frame, EndFrame):
            await self._save_conversation()

        # Pass frame through
        await self.push_frame(frame, direction)

    async def _save_conversation(self):
        """Save conversation to memory store."""
        if not self.conversation_transcript:
            logger.info("No conversation to save")
            return

        try:
            messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in self.conversation_transcript
            ]

            self.memory_store.save_conversation(self.person_name, messages)
            logger.info(f"Saved conversation: {len(messages)} messages")

        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")


class HALAutonomous:
    """
    Autonomous HAL system with face recognition and Pipecat conversations.
    """

    def __init__(self):
        """Initialize HAL autonomous system."""
        logger.info("Initializing HAL 9000 Autonomous System")

        # Configuration
        self.use_vosk = os.getenv("USE_VOSK", "1") == "1"
        self.flask_url = os.getenv("FLASK_BASE_URL", "http://localhost:5000")

        # Services
        self.memory_store = MemoryStore()

        # Active conversations
        self.active_conversations: Dict[str, PipelineTask] = {}

        # Controller bridge
        self.controller = HALControllerBridge(
            on_person_arrived=self._on_person_arrived,
            on_person_departed=self._on_person_departed
        )

        logger.info("HAL 9000 initialized")

    async def start(self):
        """Start the autonomous HAL system."""
        logger.info("Starting HAL 9000 Autonomous System")
        logger.info("=" * 60)
        logger.info("HAL is now watching and listening...")
        logger.info("=" * 60)

        # Start controller bridge
        await self.controller.start()

    async def stop(self):
        """Stop the autonomous HAL system."""
        logger.info("Stopping HAL 9000 Autonomous System")

        # Stop all active conversations
        for person_name, task in self.active_conversations.items():
            logger.info(f"Ending conversation with {person_name}")
            # TODO: Send EndFrame to task

        # Stop controller
        await self.controller.stop()

        logger.info("HAL 9000 stopped")

    async def _on_person_arrived(self, person_name: str):
        """
        Handle person arrival - start conversation.

        Args:
            person_name: Name of person who arrived
        """
        logger.info(f"Person arrived: {person_name}")

        # Check if already in conversation
        if person_name in self.active_conversations:
            logger.info(f"Already in conversation with {person_name}")
            return

        # Get person's profile
        profile = self.memory_store.load_profile(person_name)
        context = self.memory_store.get_context_for_claude(person_name)

        logger.info(f"Profile: {profile}")
        logger.debug(f"Context: {context}")

        # Start conversation
        await self._start_conversation(person_name, profile, context)

    async def _on_person_departed(self, person_name: str):
        """
        Handle person departure - end conversation.

        Args:
            person_name: Name of person who departed
        """
        logger.info(f"Person departed: {person_name}")

        # End active conversation if exists
        if person_name in self.active_conversations:
            logger.info(f"Ending conversation with {person_name}")
            # TODO: Send EndFrame to gracefully end conversation
            del self.active_conversations[person_name]

    async def _start_conversation(
        self,
        person_name: str,
        profile: dict,
        context: str
    ):
        """
        Start a Pipecat conversation with the person.

        Args:
            person_name: Name of person
            profile: Person's profile from memory store
            context: Conversation context
        """
        try:
            logger.info(f"Starting conversation with {person_name}")

            # Create tool handler
            tools = create_tool_handler(
                memory_store=self.memory_store,
                person_name=person_name
            )

            # Configure transport (local audio)
            transport = LocalAudioTransport(
                TransportParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                )
            )

            # Configure STT
            if self.use_vosk:
                stt = HALVoskSTTService(
                    model_path="/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15",
                    sample_rate=16000
                )
            else:
                stt = HALVoskSTTService(
                    model_path="/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15",
                    sample_rate=16000
                )

            # Configure LLM
            llm = AnthropicLLMService(
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                model="claude-sonnet-4-20250514",
            )

            # Configure TTS
            tts = HALPiperTTSServiceHTTP(
                base_url=self.flask_url,
                sample_rate=22050
            )
            await tts.start()

            # Generate personalized system prompt
            system_prompt = get_conversation_system_prompt(person_name, context)

            # Build message context with greeting
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                }
            ]

            # Add personalized greeting
            greeting = get_greeting_prompt(person_name, context)
            messages.append({
                "role": "assistant",
                "content": greeting
            })

            logger.info(f"Greeting: {greeting}")

            # Speak the greeting immediately
            await tts.say(greeting)

            # Create conversation processor
            conversation_processor = ConversationFrameProcessor(
                self.memory_store,
                person_name
            )

            # Create aggregators
            llm_user_aggregator = LLMUserResponseAggregator(messages)
            llm_assistant_aggregator = LLMAssistantResponseAggregator(messages)

            # Build pipeline
            pipeline = Pipeline([
                transport.input(),
                stt,
                llm_user_aggregator,
                llm,
                llm_assistant_aggregator,
                tts,
                transport.output(),
                conversation_processor,
            ])

            # Create task
            task = PipelineTask(
                pipeline,
                PipelineParams(
                    allow_interruptions=True,
                    enable_metrics=True,
                )
            )

            # Store active conversation
            self.active_conversations[person_name] = task

            # Create runner and run task in background
            runner = PipelineRunner()

            # Run in background task
            asyncio.create_task(self._run_conversation(person_name, runner, task, tts))

        except Exception as e:
            logger.error(f"Failed to start conversation: {e}", exc_info=True)

    async def _run_conversation(
        self,
        person_name: str,
        runner: PipelineRunner,
        task: PipelineTask,
        tts
    ):
        """
        Run a conversation task in the background.

        Args:
            person_name: Name of person
            runner: Pipeline runner
            task: Pipeline task
            tts: TTS service to clean up
        """
        try:
            logger.info(f"Running conversation with {person_name}")
            await runner.run(task)

        except Exception as e:
            logger.error(f"Conversation error: {e}", exc_info=True)

        finally:
            # Cleanup
            await tts.stop()
            if person_name in self.active_conversations:
                del self.active_conversations[person_name]
            logger.info(f"Conversation with {person_name} ended")


async def main():
    """Main entry point for autonomous HAL."""

    # Create HAL instance
    hal = HALAutonomous()

    try:
        # Start HAL
        await hal.start()

    except KeyboardInterrupt:
        logger.info("HAL interrupted by user")

    except Exception as e:
        logger.error(f"HAL error: {e}", exc_info=True)

    finally:
        # Stop HAL
        await hal.stop()


if __name__ == "__main__":
    asyncio.run(main())
