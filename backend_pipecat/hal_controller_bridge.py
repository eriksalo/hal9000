#!/usr/bin/env python3
"""
HAL Controller Bridge

Integrates face recognition and person tracking with Pipecat pipeline.
This bridges the original hal_controller.py autonomous detection with
the new Pipecat-based conversation system.
"""

import asyncio
import os
import sys
from typing import Optional, Callable
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from face_recognition_service import FaceRecognitionService
from person_tracker import PersonTracker
from vision_service import VisionService
from memory_store import MemoryStore

# Load environment
load_dotenv()


class HALControllerBridge:
    """
    Bridge between face recognition system and Pipecat pipeline.

    Monitors camera for faces, tracks arrivals/departures, and triggers
    Pipecat conversations when people are detected.
    """

    def __init__(
        self,
        on_person_arrived: Optional[Callable] = None,
        on_person_departed: Optional[Callable] = None,
    ):
        """
        Initialize HAL controller bridge.

        Args:
            on_person_arrived: Callback when person arrives (person_name: str)
            on_person_departed: Callback when person departs (person_name: str)
        """
        # Callbacks
        self.on_person_arrived = on_person_arrived
        self.on_person_departed = on_person_departed

        # Initialize services
        logger.info("Initializing HAL Controller Bridge")

        # Vision service
        self.vision_service = VisionService()
        logger.info("Vision service initialized")

        # Face recognition service
        self.face_recognition_service = FaceRecognitionService()
        logger.info("Face recognition service initialized")

        # Person tracker
        self.person_tracker = PersonTracker(
            presence_threshold=3.0,  # 3 seconds before greeting
            departure_threshold=5.0,  # 5 seconds without detection
            greeting_cooldown=300.0   # 5 minutes between greetings
        )

        # Register callbacks with person tracker
        self.person_tracker.on_arrival = self._handle_arrival
        self.person_tracker.on_departure = self._handle_departure

        logger.info("Person tracker initialized")

        # Memory store
        self.memory_store = MemoryStore()

        # State
        self.running = False
        self.current_person = None

    async def start(self):
        """Start the controller bridge."""
        logger.info("Starting HAL Controller Bridge")
        self.running = True

        # Start vision service
        self.vision_service.start()

        # Run detection loop
        await self._detection_loop()

    async def stop(self):
        """Stop the controller bridge."""
        logger.info("Stopping HAL Controller Bridge")
        self.running = False

        # Stop vision service
        self.vision_service.stop()

    async def _detection_loop(self):
        """Main detection loop for face recognition."""
        logger.info("Face detection loop started")

        while self.running:
            try:
                # Get frame from camera
                with self.vision_service.lock:
                    frame = self.vision_service.latest_frame

                if frame is None:
                    await asyncio.sleep(0.1)
                    continue

                # Detect faces
                face_encodings, face_locations = self.face_recognition_service.detect_faces(frame)

                # Format detections for person tracker
                # PersonTracker expects List[Tuple[name, location]]
                detected_faces = []
                for encoding, location in zip(face_encodings, face_locations):
                    # Try to match with known faces
                    name = self.face_recognition_service.match_face(encoding)
                    detected_faces.append((name, location))

                # Update person tracker with detections
                self.person_tracker.update(detected_faces)

                # Sleep briefly to avoid overwhelming CPU
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Detection loop error: {e}")
                await asyncio.sleep(1.0)

        logger.info("Face detection loop stopped")

    def _handle_arrival(self, person_name: str):
        """
        Handle person arrival event.

        Args:
            person_name: Name of person who arrived
        """
        logger.info(f"Person arrived: {person_name}")

        # Update current person
        self.current_person = person_name

        # Get profile to see if we should greet
        profile = self.memory_store.get_profile(person_name)
        logger.info(f"Profile: {profile}")

        # Trigger callback
        if self.on_person_arrived:
            asyncio.create_task(self.on_person_arrived(person_name))

    def _handle_departure(self, person_name: str):
        """
        Handle person departure event.

        Args:
            person_name: Name of person who departed
        """
        logger.info(f"Person departed: {person_name}")

        # Clear current person
        if self.current_person == person_name:
            self.current_person = None

        # Trigger callback
        if self.on_person_departed:
            asyncio.create_task(self.on_person_departed(person_name))

    def get_current_person(self) -> Optional[str]:
        """
        Get the name of the currently detected person.

        Returns:
            Person name or None
        """
        return self.current_person

    def get_latest_frame(self):
        """
        Get the latest camera frame.

        Returns:
            Latest frame from vision service
        """
        return self.vision_service.get_frame()


async def test_bridge():
    """Test the controller bridge."""
    logger.info("Testing HAL Controller Bridge")

    async def on_arrival(person_name: str):
        logger.info(f"CALLBACK: {person_name} arrived!")

    async def on_departure(person_name: str):
        logger.info(f"CALLBACK: {person_name} departed!")

    bridge = HALControllerBridge(
        on_person_arrived=on_arrival,
        on_person_departed=on_departure
    )

    try:
        # Run for 30 seconds
        logger.info("Running bridge for 30 seconds...")
        await asyncio.wait_for(bridge.start(), timeout=30.0)

    except asyncio.TimeoutError:
        logger.info("Test timeout reached")

    finally:
        await bridge.stop()
        logger.info("Bridge stopped")


if __name__ == "__main__":
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    # Run test
    try:
        asyncio.run(test_bridge())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
