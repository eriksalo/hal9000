#!/usr/bin/env python3
"""
HAL 9000 Main Controller

Listens to Frigate for person detections, then:
- Runs face recognition on detected persons
- Detects new people and offers registration
- Greets known people
- Handles voice interaction
- Sends status to ESP32 display
"""

import cv2
import time
import threading
import subprocess
import json
import requests
import wave
from pathlib import Path
from datetime import datetime
import numpy as np

# Pi Camera support
from picamera2 import Picamera2

# Speech recognition - try Hailo Whisper first, fall back to Vosk
import webrtcvad

# Try Hailo transcription service (uses Hailo-10H accelerator)
HAILO_TRANSCRIPTION_AVAILABLE = False
try:
    from hailo_transcription_service import get_hailo_transcription_service
    HAILO_TRANSCRIPTION_AVAILABLE = True
    print("Hailo transcription service available")
except ImportError as e:
    print(f"Hailo transcription not available: {e}")

# Try Hailo detection service (uses Hailo-10H accelerator for person/object detection)
HAILO_DETECTION_AVAILABLE = False
try:
    from hailo_detection_service import get_hailo_detection_service
    HAILO_DETECTION_AVAILABLE = True
    print("Hailo detection service available")
except ImportError as e:
    print(f"Hailo detection not available: {e}")

# Vosk fallback
from vosk import Model, KaldiRecognizer

import face_recognition
from face_recognition_service import FaceRecognitionService
from memory_store import get_memory_store
from conversation_manager import ConversationManager, ConversationState
from person_tracker import PersonTracker

# Debug reporting - all run in separate threads to avoid blocking/deadlocks from circular imports
import threading as _debug_threading

def report_debug_event(message, event_type='mqtt'):
    def _report():
        try:
            from app import add_debug_event
            add_debug_event(message, event_type)
        except:
            pass
    _debug_threading.Thread(target=_report, daemon=True).start()

def report_debug_tts(text):
    def _report():
        try:
            from app import set_debug_tts
            set_debug_tts(text)
        except:
            pass
    _debug_threading.Thread(target=_report, daemon=True).start()

def report_debug_transcription(text):
    def _report():
        try:
            from app import set_debug_transcription
            set_debug_transcription(text)
        except Exception as e:
            print(f"report_debug_transcription error: {e}")
    _debug_threading.Thread(target=_report, daemon=True).start()

def report_debug_audio_level(level):
    def _report():
        try:
            from app import set_debug_audio_level
            set_debug_audio_level(level)
        except Exception as e:
            print(f"report_debug_audio_level error: {e}")
    _debug_threading.Thread(target=_report, daemon=True).start()

def report_debug_face(name, status):
    def _report():
        try:
            from app import set_debug_face
            set_debug_face(name, status)
        except:
            pass
    _debug_threading.Thread(target=_report, daemon=True).start()


class HALController:
    def __init__(self):
        # Paths
        self.base_dir = Path(__file__).parent.parent
        self.model_path = self.base_dir / "hal_9000_model" / "hal.onnx"
        self.output_dir = self.base_dir / "hal_9000_outputs"
        self.output_dir.mkdir(exist_ok=True)

        # Speech recognition - prefer Hailo Whisper, fall back to Vosk
        self.hailo_transcription = None
        self.vosk_model = None
        self.use_hailo = False

        # Hailo-accelerated detection
        self.hailo_detection = None
        self.use_hailo_detection = False

        if HAILO_DETECTION_AVAILABLE:
            try:
                self.hailo_detection = get_hailo_detection_service()
                if self.hailo_detection.is_available():
                    self.use_hailo_detection = True
                    print("Using Hailo for person/object detection (accelerated)")
            except Exception as e:
                print(f"Failed to initialize Hailo detection: {e}")

        if HAILO_TRANSCRIPTION_AVAILABLE:
            try:
                self.hailo_transcription = get_hailo_transcription_service()
                if self.hailo_transcription.is_available():
                    self.use_hailo = True
                    print("Using Hailo Whisper for speech recognition (accelerated)")
            except Exception as e:
                print(f"Failed to initialize Hailo transcription: {e}")

        # Detection settings
        self.hailo_detection_interval = 0.1  # Run Hailo detection frequently (10 FPS target)
        self.face_recognition_interval = 1.0  # Run face recognition less often (1 FPS)

        # Always load Vosk for continuous mic monitoring (Hailo is too slow for that)
        vosk_model_path = self.base_dir / "vosk_model" / "vosk-model-small-en-us-0.15"
        if vosk_model_path.exists():
            self.vosk_model = Model(str(vosk_model_path))
            if not self.use_hailo:
                print("Using Vosk for speech recognition (CPU)")
            else:
                print("Vosk loaded for continuous mic monitoring")

        # Audio devices - use card names for reliability
        self.audio_output_device = "plughw:CARD=Device,DEV=0"  # USB speaker (card 3)
        self.audio_input_device = "plughw:CARD=CMTECK,DEV=0"  # CMTECK USB microphone (card 2)
        self.mic_gain = 5  # Amplification for CMTECK mic

        # Camera settings - Pi Camera via picamera2
        self.picam = None
        self.detection_interval = 3  # Check for faces every 3 seconds
        self.camera_rotate_180 = True  # Rotate camera 180 degrees

        # Face recognition
        self.face_service = FaceRecognitionService()

        # Memory and conversation system
        self.memory_store = get_memory_store()
        self.person_tracker = PersonTracker(
            presence_threshold=3.0,      # 3 seconds before greeting
            departure_threshold=5.0,     # 5 seconds without seeing = departed
            greeting_cooldown=300.0      # 5 minute cooldown between greetings
        )

        # Conversation manager (initialized after _speak and _listen are available)
        self.conversation_manager = None

        # State machine states
        # idle -> asking_remember -> awaiting_yes_no -> asking_name -> awaiting_name -> confirming -> idle
        # Also: idle -> conversing (for known people)
        self.running = False
        self.current_state = "idle"
        self.last_person_seen = None
        self.last_person_time = 0
        self.greeting_cooldown = 60

        # Pending registration
        self.pending_face_encoding = None
        self.pending_snapshot = None
        self.conversation_lock = threading.Lock()

        # Detection thread
        self.detection_thread = None

        # Wire up person tracker callbacks
        self.person_tracker.on_arrival = self._on_person_arrival
        self.person_tracker.on_departure = self._on_person_departure

        # ESP32 status
        self.esp32_status = {
            "state": "pulsing",
            "message": "HAL 9000 Online"
        }

        # TTS cache for common phrases
        self.tts_cache_dir = self.output_dir / "tts_cache"
        self.tts_cache_dir.mkdir(exist_ok=True)
        self._precache_common_phrases()

        # Continuous mic monitoring
        self.mic_monitor_thread = None
        self.current_audio_level = 0
        self.current_transcription = ""
        self.mic_monitor_paused = False  # Pause during active listening

    def _precache_common_phrases(self):
        """Pre-generate TTS for common phrases"""
        common_phrases = [
            "I detect an unfamiliar face. Would you like me to remember you?",
            "What is your name?",
            "I did not hear a response. Perhaps another time.",
            "I could not understand the name. Please try again later.",
            "Very well. I will not remember this face.",
            "I did not catch your name. Please try again later.",
            "Everything is functioning normally.",
        ]
        print("Pre-caching common TTS phrases...")
        for phrase in common_phrases:
            cache_file = self._get_tts_cache_path(phrase)
            if not cache_file.exists():
                self._generate_tts(phrase, cache_file)
        print("TTS cache ready")

    def _get_tts_cache_path(self, text):
        """Get cache file path for a phrase"""
        import hashlib
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
        return self.tts_cache_dir / f"{text_hash}.wav"

    def _generate_tts(self, text, output_file):
        """Generate TTS audio file"""
        try:
            tts_text = text.replace("HAL", "Hal").replace("H.A.L.", "Hal")
            piper_path = Path.home() / ".local" / "bin" / "piper"

            process = subprocess.Popen(
                [str(piper_path), '--model', str(self.model_path), '--output_file', str(output_file)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=tts_text, timeout=30)
            return process.returncode == 0 and output_file.exists()
        except Exception as e:
            print(f"TTS generation error: {e}")
            return False

    def start(self):
        """Start the HAL controller"""
        self.running = True

        # Initialize conversation manager with our speak/listen methods
        self.conversation_manager = ConversationManager(
            speak_callback=self._speak,
            listen_callback=self._listen
        )

        # Initialize Pi Camera via picamera2
        print("Initializing Pi Camera...")
        try:
            self.picam = Picamera2()
            # Configure for 640x480 BGR output (what OpenCV/face_recognition expects)
            config = self.picam.create_still_configuration(
                main={"size": (640, 480), "format": "BGR888"}
            )
            self.picam.configure(config)
            self.picam.start()
            time.sleep(1)  # Give camera time to warm up
            print("Pi Camera initialized successfully")
        except Exception as e:
            print(f"Warning: Could not open Pi Camera: {e}")
            self.picam = None

        # Start continuous face detection thread
        self.detection_thread = threading.Thread(target=self._continuous_detection_loop, daemon=True)
        self.detection_thread.start()

        # Start continuous mic monitoring thread
        self.mic_monitor_thread = threading.Thread(target=self._mic_monitor_loop, daemon=True)
        self.mic_monitor_thread.start()

        print("HAL 9000 Controller started - face detection and audio transcription active")

    def _on_person_arrival(self, name: str):
        """Handle when a person arrives and stays long enough to greet"""
        print(f"Person arrival detected: {name}")

        # If it's an unknown person, trigger registration flow
        if name.startswith("Unknown"):
            print("Unknown person - checking for registration")
            # Find the frame with the unknown face for registration
            if self.pending_snapshot is not None and self.current_state == "idle":
                self._handle_unknown_face_for_registration()
            return

        # For known people, start a conversation
        if self.conversation_manager is None:
            print("Warning: conversation_manager not initialized yet")
            return

        if self.current_state == "idle" and not self.conversation_manager.is_busy():
            print(f"Starting conversation with {name}")
            self.person_tracker.mark_in_conversation(name)
            self.current_state = "conversing"
            report_debug_face(name, 'starting conversation')

            # Start conversation in conversation manager
            success = self.conversation_manager.start_conversation(name)
            if not success:
                print(f"Failed to start conversation with {name}")
                self.current_state = "idle"
                self.person_tracker.mark_conversation_ended(name)

    def _on_person_departure(self, name: str):
        """Handle when a person leaves during a conversation"""
        print(f"Person departure detected: {name}")

        # If this person was in conversation, end it
        if self.conversation_manager is None:
            return

        if self.conversation_manager.get_current_person() == name:
            print(f"Person {name} left during conversation, ending")
            self.conversation_manager.force_end("person_left")
            self.current_state = "idle"
            self.person_tracker.mark_conversation_ended(name)
            report_debug_face(name, 'departed')

    def _handle_unknown_face_for_registration(self):
        """Handle registration of an unknown face"""
        # Use existing _handle_unknown_face logic but get encoding from current frame
        if self.pending_snapshot is None:
            return

        frame = self.pending_snapshot
        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb_frame = np.ascontiguousarray(rgb_frame, dtype=np.uint8)
            face_locations = face_recognition.face_locations(rgb_frame)

            if face_locations:
                face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                if face_encodings:
                    self.pending_face_encoding = face_encodings[0]
                    threading.Thread(target=self._registration_conversation, daemon=True).start()
        except Exception as e:
            print(f"Error handling unknown face for registration: {e}")

    def _continuous_detection_loop(self):
        """Continuously check camera for faces using Hailo-accelerated detection"""
        print(f"Continuous detection thread started (hailo={self.use_hailo_detection})")
        import sys
        sys.stdout.flush()
        frames_without_face = 0
        last_face_recognition_time = 0
        last_detection_time = 0
        loop_count = 0

        while self.running:
            try:
                loop_count += 1
                if loop_count % 100 == 1:  # Log every 100 loops
                    conv_state = self.conversation_manager.get_state() if self.conversation_manager else "none"
                    print(f"Detection loop #{loop_count}, state={self.current_state}, conv={conv_state}, hailo={self.use_hailo_detection}")
                    sys.stdout.flush()

                # Capture frame from Pi Camera
                if self.picam is None:
                    print("Camera not available")
                    sys.stdout.flush()
                    time.sleep(self.detection_interval)
                    continue

                try:
                    frame = self.picam.capture_array()
                except Exception as e:
                    print(f"Failed to capture frame: {e}")
                    sys.stdout.flush()
                    time.sleep(self.detection_interval)
                    continue

                if frame is None:
                    print("Failed to capture frame (None)")
                    sys.stdout.flush()
                    time.sleep(self.detection_interval)
                    continue

                # Rotate frame if needed
                if self.camera_rotate_180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)

                # Store the latest frame for debug display
                self.pending_snapshot = frame.copy()

                # Sync current_state with conversation manager
                try:
                    if self.conversation_manager:
                        conv_state = self.conversation_manager.get_state()
                        if conv_state == "idle" and self.current_state == "conversing":
                            # Conversation ended
                            current_person = self.person_tracker.get_person_in_conversation()
                            if current_person:
                                self.person_tracker.mark_conversation_ended(current_person)
                            self.current_state = "idle"
                except Exception as e:
                    print(f"Error syncing conversation state: {e}")

                now = time.time()
                detected_faces = []
                person_detected = False

                # Use Hailo for fast person detection if available
                if self.use_hailo_detection:
                    try:
                        persons = self.hailo_detection.detect_persons(frame)
                        if persons:
                            person_detected = True
                            if loop_count % 50 == 1:
                                print(f"Hailo detected {len(persons)} person(s)")

                            # Only run CPU face recognition periodically when persons detected
                            if (now - last_face_recognition_time) >= self.face_recognition_interval:
                                last_face_recognition_time = now
                                try:
                                    detected_faces = self.face_service.recognize_faces(frame)
                                    if loop_count % 50 == 1:
                                        print(f"Face recognition: {len(detected_faces)} faces")
                                except Exception as e:
                                    print(f"Face recognition error: {e}")
                                    detected_faces = []
                        else:
                            # No person detected by Hailo - skip expensive face recognition
                            pass
                    except Exception as e:
                        print(f"Hailo detection error: {e}")
                        # Fall back to CPU face recognition
                        person_detected = True  # Force fallback
                else:
                    # No Hailo - use CPU face recognition directly (slower)
                    person_detected = True  # Always assume person might be present

                # CPU-only fallback or no Hailo
                if not self.use_hailo_detection and person_detected:
                    if (now - last_face_recognition_time) >= self.detection_interval:
                        last_face_recognition_time = now
                        try:
                            detected_faces = self.face_service.recognize_faces(frame)
                            if loop_count % 10 == 1:
                                print(f"CPU recognize_faces returned {len(detected_faces)} faces")
                        except Exception as e:
                            print(f"recognize_faces error: {e}")
                            detected_faces = []

                # Update person tracker with detected faces
                self.person_tracker.update(detected_faces)

                if detected_faces:
                    frames_without_face = 0

                    # Report first face for debug
                    first_name = detected_faces[0][0]
                    if first_name != "Unknown":
                        report_debug_face(first_name, 'recognized')
                    else:
                        report_debug_face('Unknown', 'new face detected')

                    # Only do rate-limited registration check if idle
                    if self.current_state == "idle" and (now - last_detection_time) >= 5:
                        last_detection_time = now

                        # Check for unknown faces needing registration
                        for name, location in detected_faces:
                            if name == "Unknown":
                                report_debug_event("Unknown face detected", 'camera')
                                break

                elif person_detected:
                    # Person detected but no face found
                    if loop_count % 50 == 1:
                        report_debug_face('Person', 'no face visible')
                else:
                    frames_without_face += 1
                    # Update tracker with empty list to handle departures
                    self.person_tracker.update([])

                    if frames_without_face == 30:  # After ~3 seconds with Hailo
                        report_debug_face('None', 'no person in view')

            except Exception as e:
                print(f"Detection loop error: {e}")
                import traceback
                traceback.print_exc()

            # Use faster loop interval when Hailo is available
            sleep_time = self.hailo_detection_interval if self.use_hailo_detection else self.detection_interval
            time.sleep(sleep_time)

    def stop(self):
        """Stop the HAL controller"""
        self.running = False
        if self.picam:
            try:
                self.picam.stop()
                self.picam.close()
            except:
                pass
        print("HAL 9000 Controller stopped")

    def _mic_monitor_loop(self):
        """Continuously monitor microphone and transcribe for debug display"""
        print(f"Mic monitor thread started (vosk_available={self.vosk_model is not None})")
        import sys
        sample_rate = 16000

        # Initialize Vosk for continuous transcription if available
        # (Hailo is too slow for continuous monitoring, so we use Vosk for this)
        rec = None
        if self.vosk_model is not None:
            rec = KaldiRecognizer(self.vosk_model, sample_rate)
            rec.SetWords(True)

        loop_count = 0
        while self.running:
            try:
                loop_count += 1

                # Skip when paused (during active listening/conversation)
                if self.mic_monitor_paused:
                    time.sleep(0.5)
                    continue

                # Record a short audio chunk for continuous monitoring
                record_cmd = [
                    'arecord',
                    '-D', self.audio_input_device,
                    '-f', 'S16_LE',
                    '-r', str(sample_rate),
                    '-c', '1',
                    '-d', '2',  # 2 seconds for better transcription
                    '-t', 'raw',
                    '-q'
                ]

                process = subprocess.Popen(
                    record_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                # Read audio data
                audio_data, stderr = process.communicate(timeout=5)

                if stderr:
                    stderr_text = stderr.decode()
                    if stderr_text.strip():
                        print(f"Mic monitor arecord stderr: {stderr_text}")
                    sys.stdout.flush()

                if audio_data and len(audio_data) > 0:
                    # Convert to numpy and calculate level
                    audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
                    # Apply gain
                    audio_array = audio_array * self.mic_gain
                    audio_array = np.clip(audio_array, -32767, 32767)
                    max_level = int(np.max(np.abs(audio_array)))
                    self.current_audio_level = max_level
                    report_debug_audio_level(max_level)

                    # Transcribe the audio if Vosk is available
                    text = ""
                    if rec is not None:
                        amplified_bytes = audio_array.astype(np.int16).tobytes()
                        rec.AcceptWaveform(amplified_bytes)
                        result = json.loads(rec.FinalResult())
                        text = result.get("text", "").strip()

                    # Log transcription result
                    if rec is not None:
                        print(f"Mic monitor transcription: '{text}' (level={max_level})")
                    if text:
                        self.current_transcription = text
                        report_debug_transcription(text)

                        # Check for voice commands
                        text_lower = text.lower()
                        if "register" in text_lower and "face" in text_lower:
                            print("Voice command detected: register face")
                            self._trigger_voice_registration()
                    else:
                        self.current_transcription = "(no speech detected)"
                        report_debug_transcription("(no speech detected)")

                    if loop_count % 10 == 1:  # Log every ~20 seconds
                        print(f"Mic monitor: level={max_level}, bytes={len(audio_data)}")
                        sys.stdout.flush()
                else:
                    if loop_count % 10 == 1:
                        print(f"Mic monitor: no audio data received")
                        sys.stdout.flush()

            except subprocess.TimeoutExpired:
                print("Mic monitor: arecord timeout")
                process.kill()
            except Exception as e:
                print(f"Mic monitor error: {e}")
                sys.stdout.flush()

            time.sleep(0.5)  # Small pause between samples

    def get_camera_frame(self):
        """Get the current camera frame as JPEG for debug display"""
        if self.pending_snapshot is not None:
            ret, buffer = cv2.imencode('.jpg', self.pending_snapshot, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ret:
                return buffer.tobytes()
        return None

    def _recognize_face(self, frame):
        """Run face recognition on a frame"""
        try:
            print(f"_recognize_face: frame shape = {frame.shape}")
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb_frame = np.ascontiguousarray(rgb_frame, dtype=np.uint8)
            print(f"_recognize_face: rgb_frame shape = {rgb_frame.shape}")

            face_locations = face_recognition.face_locations(rgb_frame)
            print(f"_recognize_face: found {len(face_locations)} faces")

            if not face_locations:
                print("No face found in snapshot")
                return

            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            if not face_encodings:
                print("Could not encode face")
                return

            face_encoding = face_encodings[0]

            # Check against known faces
            if len(self.face_service.known_faces) > 0:
                known_names = list(self.face_service.known_faces.keys())
                known_encodings = list(self.face_service.known_faces.values())

                matches = face_recognition.compare_faces(known_encodings, face_encoding, tolerance=0.6)
                face_distances = face_recognition.face_distance(known_encodings, face_encoding)

                if True in matches:
                    best_match_index = np.argmin(face_distances)
                    if matches[best_match_index]:
                        name = known_names[best_match_index]
                        report_debug_face(name, 'recognized')
                        self._handle_known_face(name)
                        return

            # Unknown face - start registration conversation
            import sys
            print(f"_recognize_face: Unknown face detected, starting registration...")
            sys.stdout.flush()
            try:
                report_debug_face('Unknown', 'new face detected')
            except Exception as e:
                print(f"_recognize_face: report_debug_face error: {e}")
            print(f"_recognize_face: Calling _handle_unknown_face...")
            sys.stdout.flush()
            self._handle_unknown_face(frame, face_encoding)
            print(f"_recognize_face: _handle_unknown_face returned")
            sys.stdout.flush()

        except Exception as e:
            print(f"Face recognition error: {e}")
            import traceback
            traceback.print_exc()

    def _handle_unknown_face(self, frame, face_encoding):
        """Handle detection of an unknown face - start registration conversation"""
        import sys
        print(f"_handle_unknown_face: current_state={self.current_state}, last_person={self.last_person_seen}")
        sys.stdout.flush()
        with self.conversation_lock:
            if self.current_state != "idle":
                print(f"_handle_unknown_face: skipping - already in conversation (state={self.current_state})")
                return  # Already in a conversation

            now = time.time()
            time_since_last = now - self.last_person_time
            if self.last_person_seen == "unknown" and time_since_last < 30:
                print(f"_handle_unknown_face: skipping - too soon ({time_since_last:.1f}s since last)")
                return  # Don't repeat too quickly

            self.last_person_seen = "unknown"
            self.last_person_time = now

            print("Unknown face detected! Starting registration conversation...")

            # Save for potential registration
            self.pending_face_encoding = face_encoding
            self.pending_snapshot = frame

            # Start registration conversation in a separate thread
            threading.Thread(target=self._registration_conversation, daemon=True).start()

    def _trigger_voice_registration(self):
        """Handle voice-triggered face registration"""
        with self.conversation_lock:
            if self.current_state != "idle":
                print("Voice registration: skipping - not idle")
                return

            # Capture a frame
            if self.picam is None:
                self._speak("I cannot see you. The camera is not available.")
                return

            try:
                frame = self.picam.capture_array()
            except Exception as e:
                print(f"Voice registration capture error: {e}")
                self._speak("I could not capture an image. Please try again.")
                return

            if frame is None:
                self._speak("I could not capture an image. Please try again.")
                return

            # Rotate frame if needed
            if self.camera_rotate_180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)

            # Try to find and encode a face
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb_frame = np.ascontiguousarray(rgb_frame, dtype=np.uint8)
                face_locations = face_recognition.face_locations(rgb_frame)

                if not face_locations:
                    self._speak("I do not see a face. Please look at the camera and try again.")
                    return

                face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                if not face_encodings:
                    self._speak("I could not analyze your face. Please try again.")
                    return

                self.pending_face_encoding = face_encodings[0]
                self.pending_snapshot = frame

                # Start voice registration flow (skip the "would you like me to remember you" question)
                threading.Thread(target=self._voice_registration_flow, daemon=True).start()

            except Exception as e:
                print(f"Voice registration error: {e}")
                self._speak("An error occurred. Please try again.")

    def _voice_registration_flow(self):
        """Registration flow triggered by voice command - skips the initial question"""
        try:
            self.current_state = "asking_name"
            self._speak("What is your name?")
            time.sleep(2.0)

            self.current_state = "awaiting_name"
            print("Listening for name...")
            name_response = self._listen(timeout=8)

            if name_response is None or len(name_response.strip()) == 0:
                self._speak("I did not catch your name. Please try again later.")
                self._reset_conversation()
                return

            name = self._extract_name(name_response)
            print(f"Extracted name: {name}")

            if name:
                self.current_state = "confirming"
                self.face_service.register_face(self.pending_face_encoding, name)
                self._speak(f"Hello {name}. I will remember you.")
                print(f"Registered new face: {name}")
            else:
                self._speak("I could not understand the name. Please try again later.")

            self._reset_conversation()

        except Exception as e:
            print(f"Voice registration flow error: {e}")
            self._reset_conversation()

    def _registration_conversation(self):
        """Run the registration conversation flow"""
        print("_registration_conversation: STARTING")
        try:
            self.current_state = "asking_remember"
            print(f"_registration_conversation: state changed to {self.current_state}")

            # Step 1: Ask if they want to be remembered
            print("_registration_conversation: Speaking prompt...")
            self._speak("I detect an unfamiliar face. Would you like me to remember you?")
            time.sleep(2.0)  # Longer pause to let speaker echo fade

            # Step 2: Listen for yes/no
            self.current_state = "awaiting_yes_no"
            print("Listening for yes/no response...")
            response = self._listen(timeout=8)

            if response is None:
                print("No response received")
                self._speak("I did not hear a response. Perhaps another time.")
                self._reset_conversation()
                return

            print(f"Heard: {response}")

            # Check for affirmative response
            response_lower = response.lower()
            if any(word in response_lower for word in ["yes", "yeah", "yep", "sure", "okay", "ok", "please", "yea"]):
                # Step 3: Ask for name
                self.current_state = "asking_name"
                self._speak("What is your name?")
                time.sleep(2.0)  # Longer pause to let speaker echo fade

                # Step 4: Listen for name
                self.current_state = "awaiting_name"
                print("Listening for name...")
                name_response = self._listen(timeout=8)

                if name_response is None or len(name_response.strip()) == 0:
                    print("No name received")
                    self._speak("I did not catch your name. Please try again later.")
                    self._reset_conversation()
                    return

                # Extract the name (take first word or two as the name)
                name = self._extract_name(name_response)
                print(f"Extracted name: {name}")

                if name:
                    # Step 5: Confirm and register
                    self.current_state = "confirming"
                    self.face_service.register_face(self.pending_face_encoding, name)
                    self._speak(f"Hello {name}. I will remember you.")
                    print(f"Registered new face: {name}")
                else:
                    self._speak("I could not understand the name. Please try again later.")

            else:
                # They said no or something else
                self._speak("Very well. I will not remember this face.")

            self._reset_conversation()

        except Exception as e:
            print(f"Registration conversation error: {e}")
            self._reset_conversation()

    def _extract_name(self, text):
        """Extract a name from the spoken text"""
        # Common patterns: "my name is X", "I'm X", "X", "call me X"
        text = text.strip()
        words = text.split()

        # Remove common filler words
        skip_words = {"my", "name", "is", "i'm", "im", "i", "am", "call", "me", "it's", "its", "the"}

        # Try to find the actual name
        name_parts = []
        for word in words:
            if word.lower() not in skip_words:
                name_parts.append(word.capitalize())
                if len(name_parts) >= 2:  # Max 2 words for a name
                    break

        if name_parts:
            return " ".join(name_parts)

        # If all words were filtered, just use the last word
        if words:
            return words[-1].capitalize()

        return None

    def _listen(self, timeout=8):
        """Record audio and transcribe - uses Hailo Whisper or Vosk"""
        print(f"_listen: ENTERING with timeout={timeout}, use_hailo={self.use_hailo}")
        report_debug_transcription("(listening...)")

        # Pause mic monitor to avoid competition for microphone
        self.mic_monitor_paused = True
        time.sleep(0.3)  # Give mic monitor time to release

        try:
            if self.use_hailo:
                return self._listen_hailo(timeout)
            else:
                return self._listen_vosk(timeout)
        finally:
            # Always resume mic monitor
            self.mic_monitor_paused = False

    def _listen_hailo(self, timeout=8):
        """Record audio and transcribe using Hailo Whisper accelerator"""
        try:
            import tempfile
            sample_rate = 16000
            max_duration = min(timeout, 10)  # Hailo Whisper supports up to 10s

            # Record audio to a temporary file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                audio_path = tmp.name

            record_cmd = [
                'arecord',
                '-D', self.audio_input_device,
                '-f', 'S16_LE',
                '-r', str(sample_rate),
                '-c', '1',
                '-d', str(max_duration),
                audio_path
            ]

            print(f"Listening (Hailo Whisper, max {max_duration}s)...")
            start_time = time.time()

            # Record with timeout
            process = subprocess.Popen(
                record_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            try:
                process.wait(timeout=max_duration + 2)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait()

            record_time = time.time() - start_time
            print(f"Recording complete ({record_time:.1f}s)")

            # Transcribe using Hailo
            transcribe_start = time.time()
            text_result = self.hailo_transcription.transcribe_file(audio_path)
            transcribe_time = time.time() - transcribe_start

            # Clean up temp file
            try:
                import os
                os.unlink(audio_path)
            except:
                pass

            total_time = time.time() - start_time
            print(f"Transcribed in {transcribe_time:.1f}s (total {total_time:.1f}s): '{text_result}'")
            report_debug_transcription(text_result if text_result else "(empty)")
            self.current_transcription = text_result if text_result else "(empty)"
            return text_result if text_result else None

        except Exception as e:
            print(f"Hailo listen error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _listen_vosk(self, timeout=8):
        """Record audio with VAD and transcribe using Vosk - stops when speech ends"""
        try:
            # VAD settings - use highest aggressiveness to filter background noise
            vad = webrtcvad.Vad(3)  # Aggressiveness 0-3 (3 = most aggressive, filters more noise)
            sample_rate = 16000
            frame_duration_ms = 30  # 30ms frames for VAD
            frame_size = int(sample_rate * frame_duration_ms / 1000) * 2  # bytes

            # Initialize Vosk recognizer
            rec = KaldiRecognizer(self.vosk_model, sample_rate)
            rec.SetWords(True)

            # Start recording with arecord in a subprocess (streaming)
            record_cmd = [
                'arecord',
                '-D', self.audio_input_device,
                '-f', 'S16_LE',
                '-r', str(sample_rate),
                '-c', '1',
                '-t', 'raw',
                '-q'  # Quiet mode
            ]

            print("Listening... (speak now)")
            process = subprocess.Popen(
                record_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )

            # Discard first 500ms of audio to flush any echo in the buffer
            flush_frames = int(500 / frame_duration_ms)
            for _ in range(flush_frames):
                process.stdout.read(frame_size)

            speech_frames = 0
            silence_frames = 0
            min_speech_frames = 10  # Require ~300ms of speech before we consider it started
            max_silence_frames = 83  # ~2.5 seconds of silence to stop
            start_time = time.time()

            def amplify_frame(frame_bytes, gain):
                """Amplify audio frame by gain factor"""
                audio = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)
                audio = audio * gain
                audio = np.clip(audio, -32767, 32767).astype(np.int16)
                return audio.tobytes()

            try:
                while True:
                    # Check timeout
                    if time.time() - start_time > timeout:
                        print("Listen timeout reached")
                        break

                    # Read a frame
                    frame = process.stdout.read(frame_size)
                    if len(frame) < frame_size:
                        break

                    # Amplify the audio for better recognition
                    amplified_frame = amplify_frame(frame, self.mic_gain)

                    # Report audio level for debug
                    audio_array = np.frombuffer(amplified_frame, dtype=np.int16)
                    max_level = int(np.max(np.abs(audio_array)))
                    report_debug_audio_level(max_level)

                    # Feed amplified audio to Vosk for real-time transcription
                    rec.AcceptWaveform(amplified_frame)

                    # Check if this frame contains speech (use amplified for better detection)
                    try:
                        is_speech = vad.is_speech(amplified_frame, sample_rate)
                    except:
                        is_speech = False

                    if is_speech:
                        speech_frames += 1
                        silence_frames = 0
                    else:
                        # Only count silence after we've had enough speech
                        if speech_frames >= min_speech_frames:
                            silence_frames += 1
                            # Stop after enough silence following speech
                            if silence_frames >= max_silence_frames:
                                print("Speech ended (silence detected)")
                                break

            finally:
                process.terminate()
                process.wait()

            # Get final transcription
            final_result = json.loads(rec.FinalResult())
            text_result = final_result.get("text", "").strip()

            elapsed = time.time() - start_time
            print(f"Transcribed in {elapsed:.1f}s: '{text_result}'")
            report_debug_transcription(text_result if text_result else "(empty)")
            self.current_transcription = text_result if text_result else "(empty)"
            return text_result if text_result else None

        except Exception as e:
            print(f"Vosk listen error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _reset_conversation(self):
        """Reset conversation state"""
        with self.conversation_lock:
            self.current_state = "idle"
            self.pending_face_encoding = None
            self.pending_snapshot = None
            print("Conversation ended, returning to idle")

    def _handle_known_face(self, name):
        """Handle detection of a known face"""
        now = time.time()

        if self.last_person_seen == name and (now - self.last_person_time) < self.greeting_cooldown:
            return

        self.last_person_seen = name
        self.last_person_time = now

        print(f"Recognized: {name}")

        # Time-appropriate greeting
        hour = datetime.now().hour
        if 5 <= hour < 12:
            time_greeting = "Good morning"
        elif 12 <= hour < 17:
            time_greeting = "Good afternoon"
        elif 17 <= hour < 21:
            time_greeting = "Good evening"
        else:
            time_greeting = "Hello"

        greeting = f"{time_greeting}, {name}. Everything is functioning normally."
        self._speak(greeting)

    def _speak(self, text):
        """Synthesize and play speech using Piper TTS with caching"""
        try:
            # Check cache first
            cache_file = self._get_tts_cache_path(text)
            if cache_file.exists():
                audio_file = cache_file
            else:
                # Generate new audio
                import uuid
                audio_file = self.output_dir / f"{uuid.uuid4()}.wav"
                if not self._generate_tts(text, audio_file):
                    print(f"TTS generation failed for: {text}")
                    return

            # Play audio
            subprocess.run(
                ['aplay', '-D', self.audio_output_device, str(audio_file)],
                capture_output=True,
                timeout=30
            )
            print(f"HAL said: {text}")
            report_debug_tts(text)

        except Exception as e:
            print(f"Speech error: {e}")

    def get_status(self):
        """Get current status for ESP32"""
        conv_info = {}
        if self.conversation_manager:
            conv_info = self.conversation_manager.get_debug_info()

        tracker_info = self.person_tracker.get_debug_info()

        return {
            "state": self.current_state,
            "message": self.esp32_status["message"],
            "last_person": self.last_person_seen,
            "known_faces": self.face_service.get_known_names(),
            "conversation": conv_info,
            "tracker": tracker_info
        }

    def get_memory_store(self):
        """Get the memory store instance"""
        return self.memory_store

    def get_person_tracker(self):
        """Get the person tracker instance"""
        return self.person_tracker

    def get_conversation_manager(self):
        """Get the conversation manager instance"""
        return self.conversation_manager

    def get_latest_snapshot(self):
        """Get the latest person snapshot as JPEG"""
        if self.pending_snapshot is not None:
            ret, buffer = cv2.imencode('.jpg', self.pending_snapshot, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                return buffer.tobytes()
        return None

    def get_frame_base64(self):
        """Get the current camera frame as base64 for Claude Vision API"""
        import base64
        if self.pending_snapshot is not None:
            ret, buffer = cv2.imencode('.jpg', self.pending_snapshot, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                return base64.b64encode(buffer.tobytes()).decode('utf-8')
        return None

    def get_hailo_scene_description(self):
        """Get a quick scene description using Hailo detection (no API call needed)"""
        if self.use_hailo_detection and self.pending_snapshot is not None:
            return self.hailo_detection.describe_scene(self.pending_snapshot)
        return None


# Global controller instance
_controller = None

def get_controller():
    """Get or create the HAL controller instance"""
    global _controller
    if _controller is None:
        _controller = HALController()
    return _controller


if __name__ == "__main__":
    controller = HALController()
    controller.start()

    try:
        print("HAL 9000 is watching via Frigate... Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        controller.stop()
