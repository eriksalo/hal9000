#!/usr/bin/env python3
"""
HAL 9000 Pipecat Pipeline

Full-duplex conversational AI pipeline using Pipecat framework.
Integrates Claude API, HAL-9000 voice, memory persistence, and natural turn-taking.
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
    LLMMessagesFrame,
    TextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    EndFrame,
)
from pipecat.services.anthropic import AnthropicLLMService
from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.transports.services.daily import DailyParams, DailyTransport

# Import HAL-specific services
from hal_piper_tts import HALPiperTTSService, HALPiperTTSServiceHTTP
from hal_whisper_stt import HALWhisperSTTService, HALVoskSTTService

# Import reusable components from original backend
from memory_store import MemoryStore
from prompts import get_conversation_system_prompt, get_greeting_prompt

# Load environment variables
load_dotenv()

# Configure logger
logger.remove()
logger.add(sys.stderr, level="DEBUG")


class MemoryFrameProcessor(FrameProcessor):
    """
    Custom frame processor to integrate HAL's memory system.
    Tracks conversations and extracts facts for persistence.
    """

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
                "timestamp": asyncio.get_event_loop().time()
            })
            logger.debug(f"User said: {frame.text}")

        # Capture assistant responses
        elif isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            self.conversation_transcript.append({
                "role": "assistant",
                "content": frame.text,
                "timestamp": asyncio.get_event_loop().time()
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
            # Format transcript for storage
            messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in self.conversation_transcript
            ]

            # Save to memory store
            self.memory_store.save_conversation(self.person_name, messages)
            logger.info(f"Saved conversation with {self.person_name}: {len(messages)} messages")

            # TODO: Extract facts using Claude API (similar to original conversation_manager.py)
            # This would call Claude to analyze the conversation and extract learnings

        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")


class HALPipeline:
    """
    Main HAL 9000 conversational pipeline.
    Manages the full-duplex audio conversation flow.
    """

    def __init__(
        self,
        daily_room_url: str,
        daily_token: str,
        person_name: Optional[str] = None
    ):
        self.daily_room_url = daily_room_url
        self.daily_token = daily_token
        self.person_name = person_name or "Unknown"

        # Initialize memory store
        self.memory_store = MemoryStore()

        # Get personalized greeting using memory context
        profile = self.memory_store.load_profile(self.person_name)
        context = self.memory_store.get_context_for_claude(self.person_name)

        # Get HAL personality prompt
        self.system_prompt = get_conversation_system_prompt(self.person_name, context)

        logger.info(f"Initializing HAL pipeline for {self.person_name}")
        logger.debug(f"Memory context: {context}")

    async def run(self):
        """Initialize and run the HAL pipeline."""

        # Configure Daily transport for WebRTC
        transport = DailyTransport(
            self.daily_room_url,
            self.daily_token,
            "HAL 9000",
            DailyParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                vad_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
            )
        )

        # Configure STT (Speech-to-Text)
        # Use Vosk for lightweight real-time recognition
        # Can switch to HALWhisperSTTService for better accuracy
        use_vosk = os.getenv("USE_VOSK", "1") == "1"

        if use_vosk:
            stt = HALVoskSTTService(
                model_path="/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15",
                sample_rate=16000
            )
        else:
            # Use Whisper (CPU or Hailo-accelerated)
            use_hailo = os.getenv("USE_HAILO", "0") == "1"
            stt = HALWhisperSTTService(
                model="base.en",
                use_hailo=use_hailo,
                language="en",
                sample_rate=16000
            )

        # Configure LLM (Claude with HAL personality)
        llm = AnthropicLLMService(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model="claude-sonnet-4-20250514",
        )

        # Configure TTS with HAL-9000 voice
        # Use HTTP service if Flask backend is already running
        # Otherwise use direct Piper service
        use_http_tts = os.getenv("USE_HTTP_TTS", "1") == "1"

        if use_http_tts:
            tts = HALPiperTTSServiceHTTP(
                base_url=os.getenv("FLASK_BASE_URL", "http://localhost:5000"),
                sample_rate=22050
            )
            await tts.start()
        else:
            tts = HALPiperTTSService(
                model_path="/home/erik/hal9000/hal_9000_model/hal.onnx",
                sample_rate=22050
            )

        # Build message context with HAL personality
        messages = [
            {
                "role": "system",
                "content": self.system_prompt
            },
        ]

        # Add personalized greeting if this is first interaction
        profile = self.memory_store.get_profile(self.person_name)
        if profile.get("conversation_count", 0) == 0:
            greeting = get_greeting_prompt(
                self.person_name,
                self.memory_store.get_conversation_context(self.person_name)
            )
            messages.append({
                "role": "assistant",
                "content": greeting
            })

        # Create memory processor
        memory_processor = MemoryFrameProcessor(self.memory_store, self.person_name)

        # Create response aggregators
        llm_user_aggregator = LLMUserResponseAggregator(messages)
        llm_assistant_aggregator = LLMAssistantResponseAggregator(messages)

        # Build the pipeline
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

        # Create and run the task
        task = PipelineTask(pipeline, PipelineParams(allow_interruptions=True))

        # Create runner
        runner = PipelineRunner()

        # Run the pipeline
        await runner.run(task)


async def main():
    """Main entry point for HAL pipeline."""

    # Get Daily room credentials
    daily_room_url = os.getenv("DAILY_ROOM_URL")
    daily_token = os.getenv("DAILY_TOKEN")
    person_name = os.getenv("PERSON_NAME", "Dave")

    if not daily_room_url or not daily_token:
        logger.error("DAILY_ROOM_URL and DAILY_TOKEN must be set")
        sys.exit(1)

    # Create and run pipeline
    hal = HALPipeline(daily_room_url, daily_token, person_name)
    await hal.run()


if __name__ == "__main__":
    asyncio.run(main())
