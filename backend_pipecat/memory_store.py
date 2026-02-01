#!/usr/bin/env python3
"""
HAL 9000 Memory Store

Persistent per-person memory storage for conversations and facts.

Directory structure:
  memory/
    people/
      {name}/
        profile.json         # Facts, preferences, metadata
        conversations/
          {timestamp}.json   # Timestamped transcripts
        summary.json         # Rolling relationship summary
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
import threading
import uuid


class MemoryStore:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent

        self.memory_dir = base_dir / "memory" / "people"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Active conversations: conv_id -> conversation data
        self.active_conversations: Dict[str, Dict] = {}
        self.lock = threading.Lock()

    def _get_person_dir(self, name: str) -> Path:
        """Get the directory for a person's data"""
        # Normalize name for filesystem (lowercase, replace spaces)
        safe_name = name.lower().replace(" ", "_")
        person_dir = self.memory_dir / safe_name
        person_dir.mkdir(parents=True, exist_ok=True)
        return person_dir

    def _get_conversations_dir(self, name: str) -> Path:
        """Get the conversations directory for a person"""
        conv_dir = self._get_person_dir(name) / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        return conv_dir

    # ============== Profile Management ==============

    def load_profile(self, name: str) -> Dict[str, Any]:
        """Load a person's profile"""
        profile_path = self._get_person_dir(name) / "profile.json"

        if profile_path.exists():
            try:
                with open(profile_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading profile for {name}: {e}")

        # Return default profile
        return {
            "name": name,
            "first_seen": datetime.now().isoformat(),
            "last_seen": None,
            "facts": [],
            "preferences": {},
            "conversation_count": 0
        }

    def save_profile(self, name: str, data: Dict[str, Any]) -> bool:
        """Save a person's profile"""
        profile_path = self._get_person_dir(name) / "profile.json"

        try:
            with open(profile_path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving profile for {name}: {e}")
            return False

    def add_fact(self, name: str, fact: str) -> bool:
        """Add a new fact to a person's profile"""
        profile = self.load_profile(name)

        # Avoid duplicates
        if fact not in profile.get("facts", []):
            if "facts" not in profile:
                profile["facts"] = []
            profile["facts"].append(fact)
            return self.save_profile(name, profile)
        return True

    def add_facts(self, name: str, facts: List[str]) -> bool:
        """Add multiple facts to a person's profile"""
        profile = self.load_profile(name)

        if "facts" not in profile:
            profile["facts"] = []

        for fact in facts:
            if fact and fact not in profile["facts"]:
                profile["facts"].append(fact)

        return self.save_profile(name, profile)

    def update_last_seen(self, name: str) -> bool:
        """Update the last_seen timestamp for a person"""
        profile = self.load_profile(name)
        profile["last_seen"] = datetime.now().isoformat()
        return self.save_profile(name, profile)

    # ============== Conversation Management ==============

    def start_conversation(self, name: str) -> str:
        """Start a new conversation with a person, returns conversation ID"""
        conv_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now()

        with self.lock:
            self.active_conversations[conv_id] = {
                "person_name": name,
                "started_at": timestamp.isoformat(),
                "ended_at": None,
                "utterances": [],
                "end_reason": None,
                "extracted_facts": [],
                "summary": None
            }

        # Update profile
        profile = self.load_profile(name)
        profile["conversation_count"] = profile.get("conversation_count", 0) + 1
        profile["last_seen"] = timestamp.isoformat()
        self.save_profile(name, profile)

        print(f"Started conversation {conv_id} with {name}")
        return conv_id

    def add_utterance(self, conv_id: str, speaker: str, text: str) -> bool:
        """Add an utterance to an active conversation"""
        with self.lock:
            if conv_id not in self.active_conversations:
                print(f"Warning: Conversation {conv_id} not found")
                return False

            self.active_conversations[conv_id]["utterances"].append({
                "speaker": speaker,
                "text": text,
                "timestamp": datetime.now().isoformat()
            })
            return True

    def get_conversation(self, conv_id: str) -> Optional[Dict]:
        """Get an active conversation by ID"""
        with self.lock:
            return self.active_conversations.get(conv_id)

    def end_conversation(self, conv_id: str, reason: str,
                        facts: Optional[List[str]] = None,
                        summary: Optional[str] = None) -> bool:
        """End an active conversation and save it to disk"""
        with self.lock:
            if conv_id not in self.active_conversations:
                print(f"Warning: Conversation {conv_id} not found")
                return False

            conv = self.active_conversations[conv_id]
            conv["ended_at"] = datetime.now().isoformat()
            conv["end_reason"] = reason
            conv["extracted_facts"] = facts or []
            conv["summary"] = summary

            # Save to disk
            name = conv["person_name"]
            timestamp = datetime.fromisoformat(conv["started_at"])
            filename = timestamp.strftime("%Y-%m-%d_%H%M%S") + ".json"

            conv_path = self._get_conversations_dir(name) / filename
            try:
                with open(conv_path, 'w') as f:
                    json.dump(conv, f, indent=2)
                print(f"Saved conversation to {conv_path}")
            except Exception as e:
                print(f"Error saving conversation: {e}")
                return False

            # Add extracted facts to profile
            if facts:
                self.add_facts(name, facts)

            # Update relationship summary
            if summary:
                self._update_summary(name, summary)

            # Remove from active conversations
            del self.active_conversations[conv_id]
            return True

    def _update_summary(self, name: str, new_summary: str) -> bool:
        """Update the rolling relationship summary"""
        summary_path = self._get_person_dir(name) / "summary.json"

        summaries = []
        if summary_path.exists():
            try:
                with open(summary_path, 'r') as f:
                    data = json.load(f)
                    summaries = data.get("summaries", [])
            except:
                pass

        # Add new summary with timestamp
        summaries.append({
            "timestamp": datetime.now().isoformat(),
            "summary": new_summary
        })

        # Keep only last 10 summaries
        summaries = summaries[-10:]

        try:
            with open(summary_path, 'w') as f:
                json.dump({"summaries": summaries}, f, indent=2)
            return True
        except Exception as e:
            print(f"Error updating summary: {e}")
            return False

    # ============== Context Retrieval ==============

    def get_context_for_claude(self, name: str, max_facts: int = 10,
                               max_summaries: int = 3) -> str:
        """
        Get formatted context about a person for Claude API
        Returns a string with facts and recent conversation summaries
        """
        profile = self.load_profile(name)

        context_parts = []

        # Basic info
        first_seen = profile.get("first_seen")
        if first_seen:
            try:
                dt = datetime.fromisoformat(first_seen)
                context_parts.append(f"First met: {dt.strftime('%B %d, %Y')}")
            except:
                pass

        conv_count = profile.get("conversation_count", 0)
        if conv_count > 0:
            context_parts.append(f"Previous conversations: {conv_count}")

        # Known facts
        facts = profile.get("facts", [])
        if facts:
            recent_facts = facts[-max_facts:]
            context_parts.append(f"Known facts about {name}:")
            for fact in recent_facts:
                context_parts.append(f"  - {fact}")

        # Recent conversation summaries
        summary_path = self._get_person_dir(name) / "summary.json"
        if summary_path.exists():
            try:
                with open(summary_path, 'r') as f:
                    data = json.load(f)
                    summaries = data.get("summaries", [])[-max_summaries:]

                    if summaries:
                        context_parts.append(f"Recent conversation summaries:")
                        for s in summaries:
                            try:
                                dt = datetime.fromisoformat(s["timestamp"])
                                date_str = dt.strftime("%m/%d")
                                context_parts.append(f"  [{date_str}] {s['summary']}")
                            except:
                                context_parts.append(f"  - {s['summary']}")
            except:
                pass

        return "\n".join(context_parts)

    def get_recent_conversations(self, name: str, limit: int = 5) -> List[Dict]:
        """Get the most recent conversations for a person"""
        conv_dir = self._get_conversations_dir(name)

        # List all conversation files
        conv_files = sorted(conv_dir.glob("*.json"), reverse=True)[:limit]

        conversations = []
        for conv_file in conv_files:
            try:
                with open(conv_file, 'r') as f:
                    conversations.append(json.load(f))
            except:
                pass

        return conversations

    def person_exists(self, name: str) -> bool:
        """Check if we have memory data for a person"""
        profile_path = self._get_person_dir(name) / "profile.json"
        return profile_path.exists()

    def list_known_people(self) -> List[str]:
        """List all people we have memory data for"""
        people = []
        if self.memory_dir.exists():
            for person_dir in self.memory_dir.iterdir():
                if person_dir.is_dir():
                    profile_path = person_dir / "profile.json"
                    if profile_path.exists():
                        try:
                            with open(profile_path, 'r') as f:
                                data = json.load(f)
                                people.append(data.get("name", person_dir.name))
                        except:
                            people.append(person_dir.name)
        return people


# Global instance
_memory_store = None

def get_memory_store() -> MemoryStore:
    """Get or create the global memory store instance"""
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store
