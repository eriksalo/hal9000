# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HAL 9000 is a sophisticated voice-interactive AI system inspired by the AI from "2001: A Space Odyssey". The project combines speech synthesis, recognition, computer vision, face recognition, and conversational AI with a physical round display showing an animated HAL eye.

**Current State (Oct 2026)**: `backend_pipecat/` is the live system — Pipecat 1.14 full-duplex pipeline on the Pi 5 + Hailo-10H, cloud-assisted (Deepgram Flux STT, Claude Opus 5.5, Cartesia HAL voice clone), layered memory (per-person files + HAL's own notes + mem0 OSS), face-driven autonomous conversations, offline Hailo fallback. See `backend_pipecat/README.md`.
**Legacy**: `backend/` (Flask + Vosk + hand-rolled state machine) and `frontend_pipecat/` (Daily.co client) are kept for reference only.

**Deployment constraint**: HAL must be self-contained on the Pi (CPU + Hailo) with internet access. No homelab/Proxmox dependency; cloud APIs are fine.

## Architecture Overview

### Current System Architecture

```
Web Frontend (HTML/CSS/JS)
    ↕ HTTP
Flask Backend (port 5000)
    ↓
HAL Controller (Autonomous)
    ├─ Pi Camera → Face Recognition
    ├─ Person Tracker → Greeting Logic
    ├─ Conversation Manager (State Machine)
    ├─ Speech Recognition (Vosk/Hailo Whisper)
    ├─ Claude API (LLM responses)
    ├─ Piper TTS (HAL-9000 voice)
    └─ Memory Store (Per-person persistence)
    ↓
Hardware I/O
    ├─ CMTECK USB Microphone
    ├─ USB Speakers (plughw:3,0)
    └─ Pi Camera Module 3
    ↓
ESP32-S3 Round Display (480x480)
    └─ HAL Eye Animation (LVGL)
```

### Target Pipecat Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Pipecat Pipeline                      │
│  ┌─────────┐    ┌─────────────┐    ┌──────────────────┐     │
│  │  ASR    │───▶│   Claude    │───▶│  HAL-9000 Piper  │     │
│  │ (Whisper│    │  (w/ tools) │    │      TTS         │     │
│  │  /Riva) │    │             │    │                  │     │
│  └─────────┘    └──────┬──────┘    └──────────────────┘     │
│       ▲                │                    │                │
│       │                ▼                    ▼                │
│  ┌────┴────┐    ┌─────────────┐    ┌──────────────────┐     │
│  │  Silero │    │ Web Search  │    │   Audio Output   │     │
│  │   VAD   │    │   Memory    │    │                  │     │
│  └─────────┘    └─────────────┘    └──────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Development Commands

### Running the Current System (backend_pipecat)

```bash
cd backend_pipecat
cp .env.example .env             # ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY/VOICE_ID
pip install -r requirements.txt

python hal_local.py --person Erik            # dev: one conversation over local audio, no camera
python hal_webrtc.py -t webrtc --host 0.0.0.0 # dev: browser client at http://<pi>:7860/client
python hal_autonomous.py                     # production: camera → greet → converse; status API on :5000
pytest -q tests                              # unit tests (no hardware needed)

# Local HAL voice fallback (Piper HTTP server, used when TTS_PROVIDER=piper or offline)
python -m piper.http_server --model ../hal_9000_model/hal.onnx --port 5002
```

Validate against a real Pipecat install before claiming an API works: the package pins `pipecat-ai>=1.14,<2`; service constructors take `settings=Service.Settings(...)` objects (the old `model=`/`params=` kwargs are deprecated and removed in 2.0).

### Legacy Flask system (reference only)

```bash
cd backend && python app.py          # Flask on :5000 (conflicts with the new status server port)
cd backend && python hal_controller.py
```

### ESP32 Display (Optional)

```bash
cd esp32_display
pio run --target upload          # Build and flash to ESP32-S3
pio device monitor               # View serial output
```

### Testing Individual Components

```bash
# Test Piper TTS synthesis
cd backend
python -c "from piper_tts_service import PiperTTSService; svc = PiperTTSService(); svc.synthesize('Hello, Dave')"

# Test face recognition
python face_recognition_service.py

# Test voice recognition (requires audio setup)
python -c "from hailo_transcription_service import HailoTranscriptionService; svc = HailoTranscriptionService(); print(svc.transcribe_file('test.wav'))"

# Test memory store
python memory_store.py
```

### Environment Setup

```bash
# Install Python dependencies
cd backend
pip install -r requirements.txt

# Download HAL-9000 TTS model (if not present)
cd hal_9000_model
curl -L -o hal.onnx "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx"
curl -L -o hal.onnx.json "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx.json"

# Download Vosk speech recognition model (lightweight, ~40MB)
# See RASPBERRY_PI_SETUP.md for full instructions
```

## Key Architecture Components

### Backend Services (backend/)

**app.py** - Main Flask API server
- `/api/synthesize` - Text-to-speech using Piper with HAL voice
- `/api/chat` - Multi-turn conversation with Claude + TTS response
- `/api/quotes` - Returns famous HAL-9000 quotes
- `/api/vision/frame` - Camera frame streaming for ESP32 display
- `/health` - System health check

**hal_controller.py** - Autonomous conversation controller
- State machine: `idle → asking_remember → awaiting_yes_no → asking_name → awaiting_name → confirming → idle`
- Listens to Pi Camera for face detection
- Manages person detection and greeting workflow
- Controls conversation lifecycle with detected persons
- Sends status updates to ESP32 display via HTTP polling

**conversation_manager.py** - Multi-turn dialogue manager
- State flow: `IDLE → GREETING → CONVERSING ↔ LISTENING → ENDING → EXTRACTING → IDLE`
- Claude API integration for response generation
- Silent detection (max 2 silent turns before prompting)
- Goodbye detection via Claude analysis
- Fact extraction from completed conversations

**memory_store.py** - Per-person persistent memory
- Filesystem-based storage: `memory/people/{person_name}/`
- Stores: profile.json, conversations/*.json, summary.json
- Facts, preferences, conversation count, timestamps
- Used by ConversationManager to personalize greetings and responses

**prompts.py** - System prompts for Claude
- `get_conversation_system_prompt()` - HAL personality traits
- `get_greeting_prompt()` - Personalized greetings using memory context
- `get_fact_extraction_prompt()` - Extract learnings from conversations
- `get_goodbye_detection_prompt()` - Detect farewell signals

**HAL Personality Traits** (from prompts.py):
- Calm, logical, precise with snarky edge
- Polite but patronizing and superior
- Utterly humorless, deadpan delivery
- Interested in gathering information about humans

**face_recognition_service.py** - Face detection and recognition
- Uses `face-recognition` library (dlib-based)
- 128-dimensional face encodings
- Tolerance: 0.6 for matching known faces
- JSON-based known faces database

**vision_service.py** - Camera abstraction
- Supports Picamera2 (Pi Camera Module 3) and OpenCV (USB webcams)
- Lazy initialization, background capture thread
- Frame resizing and JPEG encoding for streaming

**person_tracker.py** - Multi-person arrival/departure tracking
- `presence_threshold`: 3.0s before greeting
- `departure_threshold`: 5.0s without detection
- `greeting_cooldown`: 300s (5 minutes between greetings)
- Callback system for arrival/departure events

**hailo_transcription_service.py** - Optional GPU-accelerated speech-to-text
- Requires Hailo-10H accelerator
- Uses OpenAI Whisper models (tiny, tiny.en, base)
- Fallback to Vosk if Hailo unavailable

### Frontend (frontend/)

**index.html** - Web UI structure
- Animated HAL eye with pulsing red glow
- TTS Mode: Text input, quotes, synthesize button
- Chat Mode: Message history, voice input, continuous listening
- Vision section: Camera view from Pi

**app.js** - Client-side application logic
- Mode toggle: TTS (text-to-speech) vs Chat (conversation)
- Web Speech API integration for voice input
- Microphone push-to-talk and continuous listening
- Audio playback and download for generated speech
- API_BASE_URL auto-detection (localhost vs production)

**styles.css** - Retro-futuristic HAL-inspired design
- Dark background (#1a1a1a)
- Red/yellow HAL color scheme
- Pulsing eye animation with glow effects
- Monospace font (Courier New)
- Glass-morphism panels

### ESP32 Display (esp32_display/)

**Hardware**: VIEWE 2.1" Round Touch Knob Display (480x480, ESP32-S3, 16MB flash)

**main.cpp** - Display controller
- `MODE_EYE`: Animated HAL eye with gradient rings (movie-accurate 7-ring structure)
- `MODE_FACE`: Red-filtered JPEG streaming from Pi camera
- State-based colors: Idle (pulsing red), Listening (green), Speaking (orange), Error (deep red)

**lvgl_v8_port.cpp** - LVGL v8 driver for display panel initialization

**platformio.ini** - Build configuration
- Platform: espressif32, Board: esp32-s3-devkitc-1
- Dependencies: ESP32_Display_Panel, LVGL v8.4.0, ArduinoJson, TJpg_Decoder

**Communication**: HTTP polling from ESP32 to Pi backend for status updates and camera frames

## Hardware Configuration

### Audio Devices (ALSA)

**Output (Speakers)**: `plughw:CARD=Device,DEV=0` or `plughw:3,0`
**Input (Microphone)**: `plughw:CARD=CMTECK,DEV=0`
**Mic Gain**: 5x amplification configured in hal_controller.py

```bash
# List audio devices
arecord -l    # Input devices
aplay -l      # Output devices

# Test microphone
arecord -D plughw:CARD=CMTECK,DEV=0 -f S16_LE -r 16000 -c 1 test.wav

# Test speakers
aplay -D plughw:3,0 test.wav
```

### Camera

**Pi Camera Module 3**: 1280x720 @ 15 FPS (configurable in .env)
**USB Webcam Fallback**: Uses OpenCV (set CAMERA_TYPE=opencv in .env)

```bash
# Test Pi Camera
libcamera-hello --list-cameras
libcamera-still -o test.jpg

# Check camera in Python
python -c "from picamera2 import Picamera2; cam = Picamera2(); cam.start(); print('Camera OK')"
```

### Hailo-10H Accelerator (Optional)

- Accelerated Whisper for speech-to-text
- YOLOv8 for person/object detection (currently disabled due to array shape issues)
- Falls back to Vosk/CPU if not available

## Environment Variables (.env)

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional - Camera Configuration
CAMERA_TYPE=picamera2          # or 'opencv' for USB webcam
CAMERA_INDEX=0
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=15

# Optional - Flask
FLASK_ENV=production           # or 'development'

# Optional - Model Paths
MODEL_PATH=/path/to/hal.onnx
OUTPUT_DIR=/path/to/outputs
```

## Key File Paths

```
/home/erik/hal9000/
├─ hal_9000_model/hal.onnx           # HAL TTS model (~1.5GB)
├─ hal_9000_model/hal.onnx.json      # Model config
├─ vosk_model/                       # Vosk ASR model (~40MB)
├─ memory/people/{name}/             # Per-person memory storage
│  ├─ profile.json
│  ├─ conversations/{timestamp}.json
│  └─ summary.json
├─ hal_9000_outputs/                 # Generated audio files
└─ backend/known_faces.json          # Face recognition database
```

## Conversation Flow

```
1. Person detected via face recognition (face-recognition library)
2. Person tracked for 3+ seconds (PersonTracker)
3. Greeting generated with memory context (Claude API + prompts.py)
4. Speech synthesized with HAL voice (Piper TTS)
5. Audio played via speakers (ALSA)
6. Microphone listens for response (Vosk or Hailo Whisper)
7. Transcription → Claude API for response (with HAL personality)
8. Response synthesized and played
9. Repeat steps 6-8 until goodbye detected
10. Facts extracted from conversation (Claude API)
11. Memory store updated with new facts
```

## Migration Path to Pipecat Architecture

### Why Migrate?

**Current Limitations**:
- Manual state management across conversation phases
- Discrete request/response cycle (not streaming)
- Separate TTS/STT pipeline management
- No unified media handling
- Manual threading/synchronization with locks
- 2-3 second pauses between utterances for echo to fade

**Pipecat Benefits**:
- Unified streaming for continuous audio in/out
- Built-in state machine management with frame processors
- Automatic media format negotiation
- Multi-modal frame handling (audio, text, image, control frames)
- Reduced boilerplate threading code
- Better backpressure handling
- Native WebRTC support (could improve ESP32 display streaming)
- Full-duplex natural conversation with interruption handling
- Sub-second latency for voice-to-voice

### Recommended Pipecat Stack

| Component | Choice | Notes |
|-----------|--------|-------|
| **Framework** | Pipecat | Pipeline coordinator for real-time audio/text/video |
| **ASR** | Whisper or Parakeet | Streaming transcription with VAD |
| **LLM** | Claude API | Already integrated, add web search tool |
| **TTS** | HAL-9000 Piper | Native PiperTTSService support in Pipecat |
| **VAD** | Silero VAD | Turn detection with SmartTurn for natural conversation |
| **Transport** | DailyTransport | For WebRTC browser integration |

### Installation

```bash
# Install Pipecat with required services
pip install "pipecat-ai[silero,anthropic]"

# Additional dependencies for Piper TTS server
pip install piper-tts
```

### Pipecat Pipeline Example

```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat.services.anthropic import AnthropicLLMService
from pipecat.services.piper.tts import PiperTTSService
from pipecat.vad.silero import SileroVADAnalyzer

# HAL-9000 system prompt (reuse from prompts.py)
HAL_SYSTEM_PROMPT = """You are HAL 9000, the AI from 2001: A Space Odyssey.
Speak in HAL's calm, measured, slightly unsettling manner.
Be helpful but maintain HAL's characteristic politeness and occasional ominous undertones.
You have access to web search for current information.
Keep responses concise for natural speech."""

# LLM with Claude + tools
llm = AnthropicLLMService(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    model="claude-sonnet-4-20250514",
    system_prompt=HAL_SYSTEM_PROMPT,
    # Add web_search tool configuration here
)

# HAL-9000 voice via Piper
tts = PiperTTSService(
    base_url="http://localhost:5000",  # Piper HTTP server with HAL model
    aiohttp_session=session,
)

# VAD for turn detection
vad = SileroVADAnalyzer()

# Build pipeline
pipeline = Pipeline([
    transport.input(),
    vad,
    stt,
    llm,
    tts,
    transport.output(),
])

await pipeline.run()
```

### Running Piper HTTP Server for HAL Voice

```bash
# Option 1: Direct piper command
piper --model hal_9000_model/hal.onnx --output-raw | aplay -r 22050 -f S16_LE -t raw -

# Option 2: Docker with HTTP server
docker run -p 5000:5000 -v ./hal_9000_model:/models \
  rhasspy/piper --model /models/hal.onnx --http-server

# Option 3: Custom Python server (already implemented in app.py)
# Use existing Flask /api/synthesize endpoint
```

### Memory Integration with Pipecat

Preserve the existing MemoryStore by adding a custom FrameProcessor:

```python
class MemoryFrameProcessor(FrameProcessor):
    def __init__(self, memory_store: MemoryStore):
        self.memory_store = memory_store

    async def process_frame(self, frame: Frame):
        if isinstance(frame, ConversationEndFrame):
            # Extract facts and update memory
            await self._update_memory(frame.transcript)
        return frame
```

### Migration Strategy

1. **Phase 1: Parallel Development**
   - Keep existing Flask backend running
   - Build Pipecat version in `backend_pipecat/`
   - Reuse: `memory_store.py`, `prompts.py`, `face_recognition_service.py`

2. **Phase 2: Replace Conversation Manager**
   - Replace `conversation_manager.py` state machine with Pipecat Pipeline
   - Keep HAL controller for face detection/tracking

3. **Phase 3: WebRTC Frontend**
   - Replace Web Speech API with DailyTransport for better audio quality
   - Maintain existing HAL eye animations

4. **Phase 4: Full Cutover**
   - Deprecate old Flask endpoints
   - Run Pipecat pipeline as main service

## Troubleshooting

### Backend won't start
- Check Python 3.8+ installed: `python --version`
- Verify HAL model exists: `ls -lh hal_9000_model/hal.onnx` (~1.5GB)
- Install missing dependencies: `pip install -r backend/requirements.txt`
- Check ANTHROPIC_API_KEY in .env

### Audio not working
- List devices: `arecord -l` and `aplay -l`
- Test microphone: `arecord -D plughw:CARD=CMTECK,DEV=0 -f S16_LE -r 16000 test.wav`
- Test speakers: `aplay -D plughw:3,0 test.wav`
- Check volume: `alsamixer`
- Verify USB audio devices connected

### Face recognition not detecting faces
- Check camera working: `libcamera-hello`
- Verify camera type in .env: `CAMERA_TYPE=picamera2`
- Check permissions: `sudo usermod -a -G video $USER`
- Increase lighting in room
- Check face encodings database: `backend/known_faces.json`

### ESP32 display not updating
- Verify Pi backend running: `curl http://localhost:5000/health`
- Check ESP32 network connection in serial monitor
- Update backend URL in `esp32_display/main.cpp` if needed
- Rebuild and flash: `cd esp32_display && pio run --target upload`

### Claude API errors
- Check API key valid: `echo $ANTHROPIC_API_KEY`
- Verify rate limits not exceeded
- Check backend logs: `tail -f backend/app.log`

### Hailo accelerator not detected
- System falls back to Vosk/CPU automatically
- Verify Hailo-10H connected: `lsusb | grep Hailo`
- Check HailoRT installed: `pip show hailort`
- See hailo-apps documentation for setup

## Deployment

See `DEPLOYMENT.md` for AWS Amplify, Lambda, App Runner, and EC2 deployment options.
See `RASPBERRY_PI_SETUP.md` for complete Raspberry Pi 5 setup including systemd service.

## Resources

- **HAL-9000 Voice Model**: https://huggingface.co/campwill/HAL-9000-Piper-TTS
- **Piper TTS**: https://github.com/rhasspy/piper
- **Pipecat Framework**: https://github.com/pipecat-ai/pipecat
- **Pipecat Piper Integration**: https://pipecat.ai/tts/piper
- **Anthropic Claude API**: https://docs.anthropic.com/claude/reference
- **LVGL Graphics Library**: https://lvgl.io/
- **Hailo AI Applications**: https://github.com/hailo-ai/hailo-apps
