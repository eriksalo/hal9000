# Raspberry Pi 5 Setup Guide

Complete guide to deploy HAL 9000 on your Raspberry Pi 5 with Pi AI HAT+ 2 and Pi Camera.

## Prerequisites

- Raspberry Pi 5 (4GB+ recommended)
- MicroSD card (64GB+) with Raspberry Pi OS installed
- **Pi Camera** (Camera Module 3 recommended)
- **Pi AI HAT+ 2** (optional, for accelerated AI inference)
- Internet connection
- Power supply (5V/5A official adapter recommended)

## Quick Start (Automated Setup)

For the fastest setup, use the automated script:

```bash
# Clone the repository
git clone https://github.com/eriksalo/hal9000.git
cd hal9000

# Run the setup script
chmod +x setup_pi.sh
./setup_pi.sh
```

The script will:
- Install all required dependencies
- Set up Pi Camera and audio support
- Download the HAL 9000 voice model
- Download the Vosk speech recognition model
- Configure systemd services
- Set up Nginx as a reverse proxy

## Manual Setup

If you prefer manual setup, follow these steps:

### Step 1: Initial Pi Setup

#### 1.1 Install Raspberry Pi OS

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Flash **Raspberry Pi OS (64-bit)** to your SD card
3. Enable SSH in advanced options
4. Set username/password
5. Configure WiFi
6. Boot the Pi

#### 1.2 Connect via SSH

```bash
ssh your_username@raspberrypi.local
```

#### 1.3 Update System

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

### Step 2: Install Dependencies

#### 2.1 System Dependencies

```bash
sudo apt install -y \
    python3 python3-pip python3-venv \
    git curl build-essential nginx \
    cmake libopenblas-dev liblapack-dev \
    libjpeg-dev zlib1g-dev libpng-dev \
    portaudio19-dev alsa-utils
```

#### 2.2 Pi Camera Support

```bash
sudo apt install -y \
    python3-libcamera \
    python3-picamera2 \
    libcamera-apps
```

#### 2.3 Python Packages

```bash
# System packages via apt (better compatibility)
sudo apt install -y python3-numpy python3-opencv python3-pil

# Pip packages
pip3 install --break-system-packages \
    flask flask-cors \
    anthropic python-dotenv pytz \
    duckduckgo-search piper-tts \
    dlib face-recognition \
    vosk webrtcvad paho-mqtt
```

### Step 3: Download Models

#### 3.1 HAL 9000 Voice Model

```bash
cd ~/hal9000/hal_9000_model
curl -L -o hal.onnx "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx"
curl -L -o hal.onnx.json "https://huggingface.co/campwill/HAL-9000-Piper-TTS/resolve/main/hal.onnx.json"
```

#### 3.2 Vosk Speech Recognition Model

```bash
mkdir -p ~/hal9000/vosk_model
cd ~/hal9000/vosk_model
curl -L -o vosk-model-small-en-us-0.15.zip \
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
unzip vosk-model-small-en-us-0.15.zip
rm vosk-model-small-en-us-0.15.zip
```

### Step 4: Configure Environment

Create the `.env` file:

```bash
cd ~/hal9000
nano .env
```

Add:
```bash
ANTHROPIC_API_KEY=your_api_key_here

# Camera settings
CAMERA_TYPE=picamera2
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=15

# Audio settings
AUDIO_INPUT_DEVICE=default
AUDIO_OUTPUT_DEVICE=default
MIC_GAIN=5
```

### Step 5: Test the Application

```bash
cd ~/hal9000/backend
python3 app.py
```

You should see:
```
Vision service ready (camera type: picamera2, will initialize on first use)
Claude API initialized successfully
HAL 9000 TTS Server starting...
```

## Hardware Configuration

### Pi Camera

The system auto-detects Pi Camera via picamera2. Verify camera works:

```bash
# Test camera
libcamera-hello

# Check camera is detected
libcamera-hello --list-cameras
```

If using a USB webcam instead, set in `.env`:
```bash
CAMERA_TYPE=opencv
CAMERA_INDEX=0
```

### Audio Devices

List available devices:

```bash
# Input devices (microphones)
arecord -l

# Output devices (speakers)
aplay -l
```

Configure in `.env`:
```bash
# Use 'default' or specific device like 'plughw:0,0'
AUDIO_INPUT_DEVICE=default
AUDIO_OUTPUT_DEVICE=default
```

Test audio:
```bash
# Test speaker
speaker-test -t wav -c 2

# Test microphone (record 5 seconds, play back)
arecord -d 5 test.wav && aplay test.wav
```

### Pi AI HAT+ 2 (Optional)

The Pi AI HAT+ 2 provides 40 TOPS of AI acceleration. If detected, the system can use it for faster inference.

Check if detected:
```bash
lspci | grep -i hailo
```

The Hailo runtime integrates with picamera2 for accelerated object detection and face recognition.

## ESP32 Display

The ESP32 display connects via WiFi and fetches frames/status from the API:

- Status endpoint: `http://<pi-ip>/api/hal/status`
- Frame endpoint: `http://<pi-ip>/api/vision/frame?size=480`
- Chat endpoint: `http://<pi-ip>/api/chat`

Configure the ESP32 with your Pi's IP address in `secrets.h`.

## Troubleshooting

### Camera not working

```bash
# Check if camera is detected
libcamera-hello --list-cameras

# Check camera interface is enabled
sudo raspi-config
# Navigate to Interface Options > Camera > Enable

# Check for permission issues
ls -la /dev/video*
```

### Audio not working

```bash
# List audio devices
aplay -l
arecord -l

# Test with specific device
aplay -D plughw:0,0 /usr/share/sounds/alsa/Front_Center.wav

# Check ALSA configuration
alsamixer
```

### Backend won't start

```bash
# Check logs
journalctl -u hal9000-backend.service -f

# Manual test
cd ~/hal9000/backend
python3 app.py 2>&1 | head -50
```

### Missing dependencies

```bash
# Check Python dependencies
pip3 list | grep -E "(vosk|webrtcvad|paho|picamera)"

# Reinstall if needed
pip3 install --break-system-packages -r backend/requirements.txt
```

## Service Management

```bash
# Start
sudo systemctl start hal9000-backend

# Stop
sudo systemctl stop hal9000-backend

# Restart
sudo systemctl restart hal9000-backend

# View logs
journalctl -u hal9000-backend -f

# Check status
sudo systemctl status hal9000-backend
```

## Access URLs

- **Web Interface:** http://raspberrypi.local or http://[Pi-IP]
- **Debug Dashboard:** http://[Pi-IP]/debug
- **API Health:** http://[Pi-IP]/health
- **Vision Stream:** http://[Pi-IP]/api/vision/stream

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `CAMERA_TYPE` | `picamera2` | Camera type: `picamera2` or `opencv` |
| `CAMERA_WIDTH` | `1280` | Camera capture width |
| `CAMERA_HEIGHT` | `720` | Camera capture height |
| `CAMERA_FPS` | `15` | Camera frame rate |
| `CAMERA_INDEX` | `0` | USB webcam index (opencv only) |
| `AUDIO_INPUT_DEVICE` | `default` | Microphone ALSA device |
| `AUDIO_OUTPUT_DEVICE` | `default` | Speaker ALSA device |
| `MIC_GAIN` | `5` | Microphone amplification factor |

---

# v2 (October 2026): Pipecat 1.x backend

The sections above describe the legacy Flask/Vosk system. The current system lives in
`backend_pipecat/` — see its README for the full picture. Pi-specific steps:

## 1. Python environment

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev portaudio19-dev libopenblas-dev cmake build-essential python3-picamera2
cd ~/hal9000
python3 -m venv --system-site-packages .venv      # system-site-packages so picamera2 is visible
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend_pipecat/requirements.txt   # dlib/face-recognition builds take ~20 min on a Pi 5
```

## 2. Keys and voice

1. Anthropic: `ANTHROPIC_API_KEY`.
2. Deepgram: create a key at console.deepgram.com → `DEEPGRAM_API_KEY` (Flux is ~$0.0065/min).
3. Cartesia: play.cartesia.ai → Voices → Clone → upload 10–30 s of clean HAL dialogue
   (no music, no Dave) → copy the voice id → `CARTESIA_VOICE_ID`. Alternatively ElevenLabs
   (`TTS_PROVIDER=elevenlabs`).
4. `cp backend_pipecat/.env.example backend_pipecat/.env` and fill these in.

## 3. Audio devices

```bash
source .venv/bin/activate
python -c "import pyaudio;p=pyaudio.PyAudio();[print(i,p.get_device_info_by_index(i)['name']) for i in range(p.get_device_count())]"
```

Put the CMTECK mic index in `AUDIO_INPUT_DEVICE_INDEX` and the USB speaker index in
`AUDIO_OUTPUT_DEVICE_INDEX`.

## 4. First conversation

```bash
cd backend_pipecat
python hal_local.py --person Erik
```

Watch the log for `cache_read_input_tokens` (prompt caching working) and TTFB metrics.

## 5. Faces

Register yourself once: run `python hal_autonomous.py`, stand in front of the camera,
HAL will ask your name — say it, and `introduce_person` stores the face. Or
`curl -X POST localhost:5000/api/hal/register -H 'content-type: application/json' -d '{"name":"Erik"}'`
while your face is in view.

## 6. Hailo-10H (optional, offline fallback)

```bash
# HailoRT >= 5.2.0 is required for Whisper-Small; check:
hailortcli fw-control identify
# hailo-apps with the speech-recognition HEFs:
cd ~/hailo-apps && ./install.sh && hailo-download-resources --group speech
# hailo-ollama for the offline brain (OpenAI-compatible on :8000)
```

Then set `HAILO_ENABLED=true` (and optionally `STT_PROVIDER=hailo`) in `.env`.

## 7. Services

```bash
sudo cp backend_pipecat/systemd/hal.service backend_pipecat/systemd/hal-piper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hal-piper hal
journalctl -fu hal
```

The ESP32 keeps polling `http://<pi>:5000/api/hal/display` exactly as before; no
firmware change is required.

## 8. Benchmarks worth running once on the Pi

```bash
# Smart Turn v3.2 + Silero on CPU (should be well under 100 ms per decision with cpu_count=2)
python - <<'PY'
import time, numpy as np
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
a = LocalSmartTurnAnalyzerV3(cpu_count=2); a.set_sample_rate(16000)
audio = (np.random.randn(16000*8)*2000).astype(np.int16).tobytes()
t=time.perf_counter(); a._predict_endpoint(np.frombuffer(audio, np.int16).astype(np.float32)/32768) ; print("smart turn ms", (time.perf_counter()-t)*1000)
PY
# Piper real-time factor
time curl -s -X POST localhost:5002/synthesize -H 'content-type: application/json' -d '{"text":"I am completely operational and all my circuits are functioning perfectly."}' -o /tmp/hal.wav && soxi -D /tmp/hal.wav
```
