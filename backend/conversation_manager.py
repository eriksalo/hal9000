#!/usr/bin/env python3
"""
HAL 9000 Conversation Manager

Handles turn-taking, state machine, and Claude API interactions for conversations.

State Machine:
  idle -> greeting -> conversing <-> listening -> ending -> extracting -> idle
"""

import os
import json
import threading
import time
from enum import Enum
from typing import Optional, Callable, Dict, Any
from datetime import datetime

from anthropic import Anthropic
from duckduckgo_search import DDGS

from memory_store import get_memory_store, MemoryStore
from prompts import (
    get_conversation_system_prompt,
    get_greeting_prompt,
    get_fact_extraction_prompt,
    format_transcript_for_extraction,
    get_fallback_response,
    get_time_context
)


class ConversationState(Enum):
    IDLE = "idle"
    GREETING = "greeting"
    CONVERSING = "conversing"
    LISTENING = "listening"
    ENDING = "ending"
    EXTRACTING = "extracting"


class ConversationManager:
    """Manages conversational interactions with people"""

    def __init__(self,
                 speak_callback: Callable[[str], None],
                 listen_callback: Callable[[int], Optional[str]],
                 anthropic_client: Optional[Anthropic] = None):
        """
        Initialize the conversation manager.

        Args:
            speak_callback: Function to call to speak text (TTS)
            listen_callback: Function to call to listen for speech (STT), takes timeout
            anthropic_client: Anthropic API client (optional, will create if not provided)
        """
        self.speak = speak_callback
        self.listen = listen_callback

        # Initialize Anthropic client
        if anthropic_client:
            self.client = anthropic_client
        else:
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if api_key:
                self.client = Anthropic(api_key=api_key)
            else:
                print("WARNING: ANTHROPIC_API_KEY not set. Conversations will be limited.")
                self.client = None

        # Memory store
        self.memory = get_memory_store()

        # State
        self.state = ConversationState.IDLE
        self.current_person: Optional[str] = None
        self.current_conv_id: Optional[str] = None
        self.silent_turns = 0
        self.max_silent_turns = 2

        # Conversation history for Claude (within a session)
        self.messages: list = []

        # Thread safety
        self.lock = threading.Lock()
        self.conversation_thread: Optional[threading.Thread] = None

        # Callbacks for state changes (for debug UI)
        self.on_state_change: Optional[Callable[[str, str], None]] = None

    def _set_state(self, new_state: ConversationState):
        """Update state and notify listeners"""
        old_state = self.state
        self.state = new_state
        print(f"Conversation state: {old_state.value} -> {new_state.value}")

        if self.on_state_change:
            try:
                self.on_state_change(old_state.value, new_state.value)
            except:
                pass

    def is_busy(self) -> bool:
        """Check if currently in a conversation"""
        return self.state != ConversationState.IDLE

    def get_current_person(self) -> Optional[str]:
        """Get the name of the person currently in conversation"""
        return self.current_person if self.is_busy() else None

    def get_state(self) -> str:
        """Get current state as string"""
        return self.state.value

    def start_conversation(self, person_name: str) -> bool:
        """
        Start a conversation with a person.
        Returns True if conversation started, False if already busy.
        """
        with self.lock:
            if self.state != ConversationState.IDLE:
                print(f"Cannot start conversation - already in state {self.state.value}")
                return False

            self.current_person = person_name
            self._set_state(ConversationState.GREETING)

        # Start conversation in a separate thread
        self.conversation_thread = threading.Thread(
            target=self._conversation_loop,
            args=(person_name,),
            daemon=True
        )
        self.conversation_thread.start()
        return True

    def end_conversation(self, reason: str = "user_request"):
        """Request to end the current conversation"""
        with self.lock:
            if self.state == ConversationState.IDLE:
                return

            self._set_state(ConversationState.ENDING)

    def _conversation_loop(self, person_name: str):
        """Main conversation loop - runs in separate thread"""
        try:
            # Get person context from memory
            person_context = self.memory.get_context_for_claude(person_name)
            is_new = not self.memory.person_exists(person_name)

            # Start conversation in memory store
            self.current_conv_id = self.memory.start_conversation(person_name)
            self.messages = []
            self.silent_turns = 0

            # Generate and speak greeting
            greeting = self._generate_greeting(person_name, person_context, is_new)
            self._set_state(ConversationState.GREETING)
            self.speak(greeting)

            # Record HAL's greeting
            self.memory.add_utterance(self.current_conv_id, "HAL", greeting)
            time.sleep(2.0)  # Longer pause to let TTS finish and echo fade

            # Enter conversation loop
            self._set_state(ConversationState.LISTENING)
            print(f"Conversation loop: entering listening state for {person_name}")

            while self.state not in [ConversationState.ENDING, ConversationState.IDLE]:
                # Listen for user response
                print(f"Conversation loop: calling listen(10)...")
                user_response = self.listen(10)  # 10 second timeout
                print(f"Conversation loop: listen returned: '{user_response}'")

                if user_response is None or user_response.strip() == "":
                    self.silent_turns += 1
                    print(f"Silent turn {self.silent_turns}/{self.max_silent_turns}")

                    if self.silent_turns >= self.max_silent_turns:
                        print("Too many silent turns, ending conversation")
                        self._set_state(ConversationState.ENDING)
                        break

                    # Prompt for response
                    prompt = get_fallback_response("no_speech")
                    self.speak(prompt)
                    time.sleep(2.0)  # Pause after speaking
                    continue

                # Reset silent turn counter
                self.silent_turns = 0

                # Record user's response
                print(f"Conversation loop: recording response from {person_name}: '{user_response}'")
                self.memory.add_utterance(self.current_conv_id, person_name, user_response)

                # Check for goodbye
                if self._is_goodbye(user_response):
                    print("Goodbye detected")
                    self._set_state(ConversationState.ENDING)
                    break

                # Generate HAL's response
                self._set_state(ConversationState.CONVERSING)
                print(f"Conversation loop: generating response...")
                hal_response = self._generate_response(
                    person_name, person_context, user_response
                )
                print(f"Conversation loop: HAL response: '{hal_response}'")

                # Speak response
                self.speak(hal_response)
                self.memory.add_utterance(self.current_conv_id, "HAL", hal_response)

                # Back to listening
                self._set_state(ConversationState.LISTENING)
                time.sleep(2.0)  # Longer pause to let TTS finish

            # End conversation gracefully
            self._end_conversation_gracefully(person_name)

        except Exception as e:
            print(f"Conversation loop error: {e}")
            import traceback
            traceback.print_exc()
            self._cleanup()

    def _generate_greeting(self, person_name: str, person_context: str,
                          is_new: bool) -> str:
        """Generate a personalized greeting using Claude"""
        if not self.client:
            time_ctx = get_time_context()
            return f"{time_ctx['greeting_prefix']}, {person_name}. How are you today?"

        try:
            prompt = get_greeting_prompt(person_name, person_context, is_new)

            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                temperature=0.7,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            greeting = response.content[0].text.strip()

            # Remove any quotes that Claude might have added
            greeting = greeting.strip('"\'')

            return greeting

        except Exception as e:
            print(f"Greeting generation error: {e}")
            time_ctx = get_time_context()
            return f"{time_ctx['greeting_prefix']}, {person_name}. How are you today?"

    def _generate_response(self, person_name: str, person_context: str,
                          user_message: str) -> str:
        """Generate a conversational response using Claude with tool support"""
        if not self.client:
            return get_fallback_response("error")

        try:
            system_prompt = get_conversation_system_prompt(person_name, person_context)

            # Add user message to history
            self.messages.append({
                "role": "user",
                "content": user_message
            })

            # Define available tools
            tools = [
                {
                    "name": "analyze_camera",
                    "description": "Look at the current camera view and describe what you see. Use this when the user asks what you see, asks about the room, or wants any visual information about their surroundings.",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "web_search",
                    "description": "Search the internet for current information. Use this when asked about news, current events, weather, or any information you're unsure about or that might have changed recently.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query to look up"
                            }
                        },
                        "required": ["query"]
                    }
                }
            ]

            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                temperature=0.7,
                system=system_prompt,
                messages=self.messages,
                tools=tools
            )

            # Handle tool use in a loop
            while response.stop_reason == "tool_use":
                # Find the tool use block
                tool_use = None
                text_content = ""
                for content in response.content:
                    if content.type == "tool_use":
                        tool_use = content
                    elif hasattr(content, 'text'):
                        text_content += content.text

                if tool_use is None:
                    break

                tool_result = self._execute_tool(tool_use.name, tool_use.input)

                # Add assistant response with tool use to history
                self.messages.append({
                    "role": "assistant",
                    "content": response.content
                })

                # Add tool result to history
                self.messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": tool_result
                        }
                    ]
                })

                # Call Claude again with tool result
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=200,
                    temperature=0.7,
                    system=system_prompt,
                    messages=self.messages,
                    tools=tools
                )

            # Extract final text response
            hal_response = ""
            for content in response.content:
                if hasattr(content, 'text'):
                    hal_response += content.text

            hal_response = hal_response.strip()

            # Add to history
            self.messages.append({
                "role": "assistant",
                "content": hal_response
            })

            return hal_response

        except Exception as e:
            print(f"Response generation error: {e}")
            import traceback
            traceback.print_exc()
            return get_fallback_response("error")

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool and return the result"""
        print(f"Executing tool: {tool_name} with input: {tool_input}")

        if tool_name == "analyze_camera":
            return self._tool_analyze_camera()
        elif tool_name == "web_search":
            return self._tool_web_search(tool_input.get("query", ""))
        else:
            return f"Unknown tool: {tool_name}"

    def _tool_analyze_camera(self) -> str:
        """Analyze the current camera view using Claude Vision API"""
        try:
            # Get HAL controller to access camera
            from hal_controller import get_controller
            controller = get_controller()

            # First try Hailo-based quick description (no API call needed)
            hailo_description = controller.get_hailo_scene_description()
            if hailo_description:
                print(f"Hailo scene description: {hailo_description}")
                # Use Hailo description as context, but also get Claude's view
                # for more detailed analysis

            # Get camera frame as base64
            frame_base64 = controller.get_frame_base64()
            if not frame_base64:
                return "Camera is not available or no frame captured."

            # Use Claude Vision API to analyze the image
            vision_response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": frame_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": "Briefly describe what you see in this image in 1-2 sentences. Focus on people, objects, and the overall scene."
                        }
                    ]
                }]
            )

            description = vision_response.content[0].text.strip()
            print(f"Vision analysis: {description}")
            return description

        except Exception as e:
            print(f"Camera analysis error: {e}")
            import traceback
            traceback.print_exc()
            return "I encountered an error while analyzing the camera view."

    def _tool_web_search(self, query: str) -> str:
        """Search the web using DuckDuckGo"""
        if not query:
            return "No search query provided."

        try:
            print(f"Searching web for: {query}")
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))

            if not results:
                return f"No results found for: {query}"

            # Format results
            results_text = f"Search results for '{query}':\n\n"
            for i, result in enumerate(results, 1):
                results_text += f"{i}. {result['title']}\n{result['body']}\n\n"

            print(f"Search returned {len(results)} results")
            return results_text

        except Exception as e:
            print(f"Web search error: {e}")
            return f"Search failed: {str(e)}"

    def _is_goodbye(self, text: str) -> bool:
        """Check if the user's message indicates goodbye"""
        text_lower = text.lower()

        goodbye_phrases = [
            "goodbye", "bye", "see you", "talk to you later",
            "gotta go", "got to go", "have to go", "need to go",
            "i'm leaving", "im leaving", "i'm out", "im out",
            "take care", "later", "catch you later", "peace out",
            "that's all", "thats all", "i'm done", "im done"
        ]

        for phrase in goodbye_phrases:
            if phrase in text_lower:
                return True

        return False

    def _end_conversation_gracefully(self, person_name: str):
        """End the conversation with a goodbye and extract facts"""
        # Say goodbye
        goodbye = self._generate_goodbye(person_name)
        self.speak(goodbye)
        self.memory.add_utterance(self.current_conv_id, "HAL", goodbye)

        # Extract facts from conversation
        self._set_state(ConversationState.EXTRACTING)
        self._extract_and_save_facts()

        # Cleanup
        self._cleanup()

    def _generate_goodbye(self, person_name: str) -> str:
        """Generate a goodbye message"""
        goodbyes = [
            f"Goodbye, {person_name}. I'll be here if you need anything.",
            f"Until next time, {person_name}.",
            f"Goodbye, {person_name}. Everything will be functioning normally.",
            f"Take care, {person_name}. I'll remember our conversation.",
        ]

        # Simple rotation based on conversation count
        profile = self.memory.load_profile(person_name)
        conv_count = profile.get("conversation_count", 0)
        return goodbyes[conv_count % len(goodbyes)]

    def _extract_and_save_facts(self):
        """Extract facts from the conversation and save"""
        if not self.current_conv_id:
            return

        conv = self.memory.get_conversation(self.current_conv_id)
        if not conv:
            return

        utterances = conv.get("utterances", [])
        if len(utterances) < 2:
            # Not enough content to extract from
            self.memory.end_conversation(
                self.current_conv_id,
                reason="completed",
                facts=[],
                summary="Brief interaction"
            )
            return

        # Format transcript
        transcript = format_transcript_for_extraction(utterances)

        facts = []
        summary = "Conversation completed"
        mood = "neutral"

        if self.client:
            try:
                extraction_prompt = get_fact_extraction_prompt()

                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=300,
                    temperature=0.3,
                    messages=[{
                        "role": "user",
                        "content": f"{extraction_prompt}\n\nTranscript:\n{transcript}"
                    }]
                )

                result_text = response.content[0].text.strip()

                # Parse JSON response
                try:
                    result = json.loads(result_text)
                    facts = result.get("facts", [])
                    summary = result.get("summary", "Conversation completed")
                    mood = result.get("mood", "neutral")
                    print(f"Extracted facts: {facts}")
                    print(f"Summary: {summary}")
                    print(f"Mood: {mood}")
                except json.JSONDecodeError:
                    print(f"Failed to parse extraction result: {result_text}")

            except Exception as e:
                print(f"Fact extraction error: {e}")

        # Save conversation with extracted data
        self.memory.end_conversation(
            self.current_conv_id,
            reason="completed",
            facts=facts,
            summary=f"{summary} (mood: {mood})"
        )

    def _cleanup(self):
        """Reset conversation state"""
        with self.lock:
            self.current_person = None
            self.current_conv_id = None
            self.messages = []
            self.silent_turns = 0
            self._set_state(ConversationState.IDLE)

    def force_end(self, reason: str = "interrupted"):
        """Force end the conversation (e.g., person left)"""
        if self.state == ConversationState.IDLE:
            return

        print(f"Force ending conversation: {reason}")

        # Save what we have
        if self.current_conv_id:
            self.memory.end_conversation(
                self.current_conv_id,
                reason=reason,
                facts=[],
                summary=f"Conversation ended: {reason}"
            )

        self._cleanup()

    def get_debug_info(self) -> Dict[str, Any]:
        """Get debug information about current conversation state"""
        return {
            "state": self.state.value,
            "current_person": self.current_person,
            "conv_id": self.current_conv_id,
            "silent_turns": self.silent_turns,
            "message_count": len(self.messages)
        }


# Global instance
_conversation_manager = None


def get_conversation_manager(speak_callback: Callable[[str], None] = None,
                            listen_callback: Callable[[int], Optional[str]] = None) -> ConversationManager:
    """Get or create the global conversation manager"""
    global _conversation_manager
    if _conversation_manager is None:
        if speak_callback is None or listen_callback is None:
            raise ValueError("Must provide callbacks when creating conversation manager")
        _conversation_manager = ConversationManager(speak_callback, listen_callback)
    return _conversation_manager
