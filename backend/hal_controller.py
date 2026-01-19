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

# MQTT for Frigate events
import paho.mqtt.client as mqtt

# Speech recognition
from vosk import Model, KaldiRecognizer
import webrtcvad

import face_recognition
from face_recognition_service import FaceRecognitionService

# Debug reporting (imported when available)
def report_debug_event(message, event_type='mqtt'):
    try:
        from app import add_debug_event
        add_debug_event(message, event_type)
    except:
        pass

def report_debug_tts(text):
    try:
        from app import set_debug_tts
        set_debug_tts(text)
    except:
        pass

def report_debug_transcription(text):
    try:
        from app import set_debug_transcription
        set_debug_transcription(text)
    except:
        pass

def report_debug_audio_level(level):
    try:
        from app import set_debug_audio_level
        set_debug_audio_level(level)
    except:
        pass

def report_debug_face(name, status):
    try:
        from app import set_debug_face
        set_debug_face(name, status)
    except:
        pass


class HALController:
    def __init__(self):
        # Paths
        self.base_dir = Path(__file__).parent.parent
        self.model_path = self.base_dir / "hal_9000_model" / "hal.onnx"
        self.output_dir = self.base_dir / "hal_9000_outputs"
        self.output_dir.mkdir(exist_ok=True)

        # Vosk speech recognition model
        vosk_model_path = self.base_dir / "vosk_model" / "vosk-model-small-en-us-0.15"
        self.vosk_model = Model(str(vosk_model_path))

        # Audio devices - use card names for reliability
        self.audio_output_device = "plughw:CARD=UACDemoV10,DEV=0"  # USB speaker
        self.audio_input_device = "plughw:CARD=CMTECK,DEV=0"  # CMTECK USB microphone
        self.mic_gain = 10  # Amplification for CMTECK mic

        # Frigate settings
        self.frigate_host = "localhost"
        self.frigate_port = 5001
        self.mqtt_host = "localhost"
        self.mqtt_port = 1883
        self.camera_name = "hal_camera"

        # Face recognition
        self.face_service = FaceRecognitionService()

        # State machine states
        # idle -> asking_remember -> awaiting_yes_no -> asking_name -> awaiting_name -> confirming -> idle
        self.running = False
        self.current_state = "idle"
        self.last_person_seen = None
        self.last_person_time = 0
        self.greeting_cooldown = 60

        # Pending registration
        self.pending_face_encoding = None
        self.pending_snapshot = None
        self.conversation_lock = threading.Lock()

        # MQTT client
        self.mqtt_client = None

        # ESP32 status
        self.esp32_status = {
            "state": "pulsing",
            "message": "HAL 9000 Online"
        }

        # TTS cache for common phrases
        self.tts_cache_dir = self.output_dir / "tts_cache"
        self.tts_cache_dir.mkdir(exist_ok=True)
        self._precache_common_phrases()

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

        # Start MQTT listener for Frigate events
        self.mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
        self.mqtt_thread.start()

        print("HAL 9000 Controller started - listening to Frigate")

    def stop(self):
        """Stop the HAL controller"""
        self.running = False
        if self.mqtt_client:
            self.mqtt_client.disconnect()
        print("HAL 9000 Controller stopped")

    def _mqtt_loop(self):
        """Connect to MQTT and listen for Frigate events"""
        print(f"MQTT thread starting, connecting to {self.mqtt_host}:{self.mqtt_port}")

        def on_connect(client, userdata, flags, reason_code, properties):
            print(f"MQTT on_connect called with reason_code: {reason_code}")
            if reason_code == 0:
                print(f"Connected to MQTT broker")
                client.subscribe("frigate/events")
                client.subscribe(f"frigate/{self.camera_name}/person")
                print(f"Subscribed to Frigate events")
            else:
                print(f"MQTT connection failed: {reason_code}")

        def on_message(client, userdata, msg):
            try:
                self._handle_frigate_event(msg.topic, msg.payload)
            except Exception as e:
                print(f"Error handling MQTT message: {e}")

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_message = on_message

        while self.running:
            try:
                self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
                self.mqtt_client.loop_forever()
            except Exception as e:
                print(f"MQTT connection error: {e}, retrying in 5s...")
                time.sleep(5)

    def _handle_frigate_event(self, topic, payload):
        """Handle a Frigate MQTT event"""
        try:
            data = json.loads(payload)
        except:
            return

        if "after" in data and data["after"]:
            event = data["after"]
            label = event.get("label", "")

            if label == "person":
                event_id = event.get("id", "")
                camera = event.get("camera", "")

                print(f"Person detected on {camera}, event: {event_id}")
                report_debug_event(f"Person detected on {camera}", 'mqtt')
                self._process_person_detection(event_id)

    def _process_person_detection(self, event_id):
        """Process a person detection - get snapshot and run face recognition"""
        try:
            snapshot_url = f"http://{self.frigate_host}:{self.frigate_port}/api/events/{event_id}/snapshot.jpg"
            response = requests.get(snapshot_url, timeout=5)

            if response.status_code != 200:
                print(f"Failed to get snapshot: {response.status_code}")
                return

            img_array = np.frombuffer(response.content, dtype=np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if frame is None:
                print("Failed to decode snapshot")
                return

            self._recognize_face(frame)

        except Exception as e:
            print(f"Error processing detection: {e}")

    def _recognize_face(self, frame):
        """Run face recognition on a frame"""
        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb_frame = np.ascontiguousarray(rgb_frame, dtype=np.uint8)

            face_locations = face_recognition.face_locations(rgb_frame)

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
            report_debug_face('Unknown', 'new face detected')
            self._handle_unknown_face(frame, face_encoding)

        except Exception as e:
            print(f"Face recognition error: {e}")

    def _handle_unknown_face(self, frame, face_encoding):
        """Handle detection of an unknown face - start registration conversation"""
        with self.conversation_lock:
            if self.current_state != "idle":
                return  # Already in a conversation

            now = time.time()
            if self.last_person_seen == "unknown" and (now - self.last_person_time) < 30:
                return  # Don't repeat too quickly

            self.last_person_seen = "unknown"
            self.last_person_time = now

            print("Unknown face detected! Starting registration conversation...")

            # Save for potential registration
            self.pending_face_encoding = face_encoding
            self.pending_snapshot = frame

            # Start registration conversation in a separate thread
            threading.Thread(target=self._registration_conversation, daemon=True).start()

    def _registration_conversation(self):
        """Run the registration conversation flow"""
        try:
            self.current_state = "asking_remember"

            # Step 1: Ask if they want to be remembered
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
            return text_result if text_result else None

        except Exception as e:
            print(f"Listen error: {e}")
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
        return {
            "state": self.current_state,
            "message": self.esp32_status["message"],
            "last_person": self.last_person_seen,
            "known_faces": self.face_service.get_known_names()
        }

    def get_latest_snapshot(self):
        """Get the latest person snapshot as JPEG"""
        if self.pending_snapshot is not None:
            ret, buffer = cv2.imencode('.jpg', self.pending_snapshot, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                return buffer.tobytes()
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
