#!/usr/bin/env python3
"""
HAL 9000 Local Pipeline (No Daily.co Required)

Local testing version of HAL pipeline that uses stdin/stdout
or local audio devices instead of WebRTC.
"""

import asyncio
import os
import sys
from typing import Optional
from dotenv import load_dotenv
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import LLMAssistantResponseAggregator, LLMUserResponseAggregator
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    EndFrame,
)
from pipecat.services.anthropic import AnthropicLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.local.audio import LocalAudioTransport

# Import HAL-specific services
from hal_piper_tts import HALPiperTTSServiceHTTP
from hal_whisper_stt import HALVoskSTTService
from hal_tools import create_tool_handler

# Import reusable components
from memory_store import MemoryStore
from prompts import get_conversation_system_prompt, get_greeting_prompt

# Load environment variables
load_dotenv()

# Configure logger
logger.remove()
logger.add(sys.stderr, level="INFO")


class MemoryFrameProcessor(FrameProcessor):
    """Custom frame processor to integrate HAL's memory system."""

    def __init__(self, memory_store: MemoryStore, person_name: Optional[str] = None):
        super().__init__()
        self.memory_store = memory_store
        self.person_name = person_name or "Unknown"
        self.conversation_transcript = []
        logger.info(f"MemoryFrameProcessor initialized for {self.person_name}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames to capture conversation context."""

        # Capture user speech
        if isinstance(frame, TextFrame) and direction == FrameDirection.UPSTREAM:
            self.conversation_transcript.append({
                "role": "user",
                "content": frame.text,
            })
            logger.debug(f"User said: {frame.text}")

        # Capture assistant responses
        elif isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            self.conversation_transcript.append({
                "role": "assistant",
                "content": frame.text,
            })
            logger.debug(f"HAL said: {frame.text}")

        # On conversation end, save to memory
        elif isinstance(frame, EndFrame):
            await self._save_conversation()

        # Pass frame through
        await self.push_frame(frame, direction)

    async def _save_conversation(self):
        """Save conversation transcript to memory store."""
        if not self.conversation_transcript:
            logger.info("No conversation to save")
            return

        try:
            messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in self.conversation_transcript
            ]

            self.memory_store.save_conversation(self.person_name, messages)
            logger.info(f"Saved conversation with {self.person_name}: {len(messages)} messages")

        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")


async def main():
    """Main entry point for local HAL pipeline."""

    # Configuration
    person_name = os.getenv("PERSON_NAME", "Dave")
    use_vosk = os.getenv("USE_VOSK", "1") == "1"

    logger.info(f"Starting HAL 9000 Local Pipeline for {person_name}")

    # Initialize memory store
    memory_store = MemoryStore()

    # Get personalized greeting
    profile = memory_store.load_profile(person_name)
    context = memory_store.get_context_for_claude(person_name)

    # Get HAL personality prompt
    system_prompt = get_conversation_system_prompt(person_name, context)

    logger.info(f"Profile: {profile}")
    logger.debug(f"Context: {context}")

    # Create tool handler
    tools = create_tool_handler(memory_store=memory_store, person_name=person_name)
    tool_definitions = tools.get_tool_definitions()

    # Configure transport (local audio)
    transport = LocalAudioTransport(
        TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )

    # Configure STT
    if use_vosk:
        logger.info("Using Vosk STT")
        stt = HALVoskSTTService(
            model_path="/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15",
            sample_rate=16000
        )
    else:
        # For local testing, Vosk is recommended
        logger.warning("Whisper not configured for local pipeline, using Vosk")
        stt = HALVoskSTTService(
            model_path="/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15",
            sample_rate=16000
        )

    # Configure LLM (Claude with HAL personality and tools)
    llm = AnthropicLLMService(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        model="claude-sonnet-4-20250514",
    )

    # Configure TTS (HAL-9000 voice via HTTP)
    tts = HALPiperTTSServiceHTTP(
        base_url=os.getenv("FLASK_BASE_URL", "http://localhost:5000"),
        sample_rate=22050
    )
    await tts.start()

    # Build message context
    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
    ]

    # Add greeting if first conversation
    if profile.get("conversation_count", 0) == 0:
        greeting = get_greeting_prompt(person_name, context)
        messages.append({
            "role": "assistant",
            "content": greeting
        })
        logger.info(f"Greeting: {greeting}")

    # Create memory processor
    memory_processor = MemoryFrameProcessor(memory_store, person_name)

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
        memory_processor,
    ])

    # Create task
    task = PipelineTask(
        pipeline,
        PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        )
    )

    # Create runner
    runner = PipelineRunner()

    # Run pipeline
    logger.info("HAL 9000 is ready. Press Ctrl+C to exit.")
    await runner.run(task)

    # Cleanup
    await tts.stop()
    logger.info("HAL 9000 shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("HAL 9000 interrupted by user")
    except Exception as e:
        logger.error(f"HAL 9000 error: {e}", exc_info=True)
        sys.exit(1)
