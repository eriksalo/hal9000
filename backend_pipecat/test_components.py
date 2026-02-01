#!/usr/bin/env python3
"""
Component Testing Script

Test individual HAL components before running the full pipeline.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, level="INFO")

# Load environment
load_dotenv()


async def test_memory_store():
    """Test memory store functionality."""
    logger.info("=" * 60)
    logger.info("Testing Memory Store")
    logger.info("=" * 60)

    try:
        from memory_store import MemoryStore

        store = MemoryStore()

        # Test profile access
        profile = store.load_profile("TestUser")
        logger.info(f"Profile: {profile}")

        # Test conversation management
        conv_id = store.start_conversation("TestUser")
        logger.info(f"Started conversation: {conv_id}")

        # Add a fact
        store.add_fact("TestUser", "Likes testing HAL")
        logger.info("Added fact to profile")

        # End conversation
        store.end_conversation(conv_id, "test_complete")
        logger.info("Ended conversation")

        logger.info("✓ Memory Store OK")
        return True

    except Exception as e:
        logger.error(f"✗ Memory Store failed: {e}")
        return False


async def test_prompts():
    """Test prompt generation."""
    logger.info("=" * 60)
    logger.info("Testing Prompts")
    logger.info("=" * 60)

    try:
        from prompts import get_conversation_system_prompt, get_greeting_prompt

        # Test system prompt
        system_prompt = get_conversation_system_prompt("TestUser", "Test context")
        logger.info(f"System prompt length: {len(system_prompt)} chars")
        logger.info(f"Preview: {system_prompt[:200]}...")

        # Test greeting
        greeting = get_greeting_prompt("Dave", "First conversation", 1)
        logger.info(f"Greeting: {greeting}")

        logger.info("✓ Prompts OK")
        return True

    except Exception as e:
        logger.error(f"✗ Prompts failed: {e}")
        return False


async def test_tools():
    """Test HAL tools (web search, memory, etc.)."""
    logger.info("=" * 60)
    logger.info("Testing HAL Tools")
    logger.info("=" * 60)

    try:
        from hal_tools import create_tool_handler
        from memory_store import MemoryStore

        memory_store = MemoryStore()
        tools = create_tool_handler(memory_store=memory_store, person_name="Dave")

        # Get tool definitions
        definitions = tools.get_tool_definitions()
        logger.info(f"Available tools: {len(definitions)}")
        for tool in definitions:
            logger.info(f"  - {tool['name']}: {tool['description'][:60]}...")

        # Test get_current_time
        result = await tools.execute_tool("get_current_time", {})
        logger.info(f"Current time: {result}")

        # Test recall_memory
        try:
            result = await tools.execute_tool("recall_memory", {})
            logger.info(f"Memory recall: {result[:100]}...")
        except Exception as e:
            logger.warning(f"Memory recall test skipped: {e}")

        # Test web search (if available)
        try:
            result = await tools.execute_tool("web_search", {
                "query": "HAL 9000",
                "max_results": 3
            })
            logger.info(f"Web search: {result[:200]}...")
        except Exception as e:
            logger.warning(f"Web search not available: {e}")

        logger.info("✓ HAL Tools OK")
        return True

    except Exception as e:
        logger.error(f"✗ HAL Tools failed: {e}")
        return False


async def test_tts_http():
    """Test HAL TTS HTTP service."""
    logger.info("=" * 60)
    logger.info("Testing HAL TTS (HTTP)")
    logger.info("=" * 60)

    try:
        from hal_piper_tts import HALPiperTTSServiceHTTP

        tts = HALPiperTTSServiceHTTP(
            base_url=os.getenv("FLASK_BASE_URL", "http://localhost:5000"),
            sample_rate=22050
        )

        await tts.start()
        logger.info("Connected to TTS service")

        # Generate test audio
        test_text = "Good evening, Dave. All systems are operational."
        logger.info(f"Synthesizing: {test_text}")

        frame_count = 0
        async for frame in tts.run_tts(test_text):
            frame_count += 1
            logger.debug(f"Received frame: {type(frame).__name__}")

        logger.info(f"Received {frame_count} frames")

        await tts.stop()
        logger.info("✓ HAL TTS (HTTP) OK")
        return True

    except Exception as e:
        logger.error(f"✗ HAL TTS (HTTP) failed: {e}")
        logger.error("Make sure Flask backend is running: cd ../backend && python app.py")
        return False


async def test_stt_vosk():
    """Test Vosk STT service."""
    logger.info("=" * 60)
    logger.info("Testing Vosk STT")
    logger.info("=" * 60)

    try:
        from hal_whisper_stt import HALVoskSTTService

        stt = HALVoskSTTService(
            model_path="/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15",
            sample_rate=16000
        )

        logger.info("Vosk STT initialized")
        logger.info("✓ Vosk STT OK (full test requires audio input)")
        return True

    except Exception as e:
        logger.error(f"✗ Vosk STT failed: {e}")
        logger.error("Make sure Vosk model exists at /home/erik/hal9000/vosk_model/")
        return False


async def test_anthropic_api():
    """Test Anthropic API connection."""
    logger.info("=" * 60)
    logger.info("Testing Anthropic API")
    logger.info("=" * 60)

    try:
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_api_key_here":
            logger.error("ANTHROPIC_API_KEY not set in .env")
            return False

        client = anthropic.Anthropic(api_key=api_key)

        # Simple test message
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=100,
            messages=[
                {"role": "user", "content": "Say 'API connection successful' and nothing else."}
            ]
        )

        response = message.content[0].text
        logger.info(f"Claude response: {response}")

        logger.info("✓ Anthropic API OK")
        return True

    except Exception as e:
        logger.error(f"✗ Anthropic API failed: {e}")
        logger.error("Check your ANTHROPIC_API_KEY in .env")
        return False


async def main():
    """Run all component tests."""
    logger.info("HAL 9000 Component Tests")
    logger.info("=" * 60)

    results = {}

    # Run tests
    results["Memory Store"] = await test_memory_store()
    results["Prompts"] = await test_prompts()
    results["HAL Tools"] = await test_tools()
    results["Anthropic API"] = await test_anthropic_api()
    results["Vosk STT"] = await test_stt_vosk()
    results["HAL TTS (HTTP)"] = await test_tts_http()

    # Summary
    logger.info("=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{test_name:20s} {status}")

    # Overall result
    all_passed = all(results.values())
    logger.info("=" * 60)

    if all_passed:
        logger.info("All tests passed! ✓")
        logger.info("You can now run: python hal_pipeline_local.py")
        return 0
    else:
        logger.warning("Some tests failed. Fix the issues above before running the pipeline.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
