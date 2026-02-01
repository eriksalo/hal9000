# HAL 9000 Pipecat Backend - Quick Start Guide

Get up and running with the new Pipecat-based HAL backend in 5 minutes.

## Prerequisites

1. **Python 3.8+** installed
2. **HAL-9000 TTS model** downloaded (see main README.md)
3. **Vosk model** for speech recognition (optional but recommended)
4. **Anthropic API key** for Claude
5. **Flask backend** running (for TTS HTTP mode)

## Quick Setup

### 1. Install Dependencies

```bash
cd /home/erik/hal9000/backend_pipecat

# Install Python packages
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and set:
# - ANTHROPIC_API_KEY=your_key_here
# - Other settings as needed
nano .env
```

### 3. Test Components

Before running the full pipeline, test individual components:

```bash
# Run component tests
python test_components.py
```

This will verify:
- ✓ Memory Store
- ✓ Prompts
- ✓ HAL Tools (web search, memory)
- ✓ Anthropic API
- ✓ Vosk STT
- ✓ HAL TTS (HTTP)

If all tests pass, proceed to the next step.

## Running HAL

You have three options for running HAL:

### Option 1: Local Pipeline (Simplest)

Local audio pipeline without Daily.co WebRTC:

```bash
# Make sure Flask backend is running first
cd /home/erik/hal9000/backend
python app.py &

# Run local pipeline
cd /home/erik/hal9000/backend_pipecat
python hal_pipeline_local.py
```

This starts a voice conversation using your local microphone and speakers.

### Option 2: Autonomous Mode (Face Recognition)

Full autonomous HAL with face detection and tracking:

```bash
# Make sure Flask backend is running
cd /home/erik/hal9000/backend
python app.py &

# Run autonomous controller
cd /home/erik/hal9000/backend_pipecat
python hal_autonomous.py
```

HAL will:
1. Monitor camera for faces
2. Detect and recognize people
3. Greet when someone arrives
4. Have a conversation
5. Remember facts for next time

### Option 3: WebRTC Pipeline (Daily.co)

For low-latency WebRTC conversations:

```bash
# Set up Daily.co room first (see README.md)
# Add DAILY_ROOM_URL and DAILY_TOKEN to .env

# Run WebRTC pipeline
cd /home/erik/hal9000/backend_pipecat
python hal_pipeline.py
```

This requires frontend integration with Daily.co client.

## Testing the Pipeline

### Quick TTS Test

```bash
python -c "
import asyncio
from hal_piper_tts import HALPiperTTSServiceHTTP

async def test():
    tts = HALPiperTTSServiceHTTP()
    await tts.start()
    await tts.say('Good evening, Dave.')
    await tts.stop()

asyncio.run(test())
"
```

### Quick STT Test

```bash
# Record 5 seconds of audio and transcribe
arecord -D plughw:CARD=CMTECK,DEV=0 -f S16_LE -r 16000 -d 5 test.wav

# Transcribe with Vosk
python -c "
from hal_whisper_stt import HALVoskSTTService
import wave

stt = HALVoskSTTService()

with wave.open('test.wav', 'rb') as wf:
    audio = wf.readframes(wf.getnframes())

# Process audio through STT
import asyncio
async def test():
    async for frame in stt.run_stt(audio):
        print(frame)

asyncio.run(test())
"
```

## Common Issues

### "ANTHROPIC_API_KEY not set"

```bash
# Check .env file
cat .env | grep ANTHROPIC_API_KEY

# Should show your key, not "your_api_key_here"
```

### "Failed to connect to TTS service"

Make sure Flask backend is running:

```bash
# In another terminal
cd /home/erik/hal9000/backend
python app.py

# Test endpoint
curl http://localhost:5000/health
```

### "Vosk model not found"

```bash
# Check model exists
ls -lh /home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15/

# If missing, download:
cd /home/erik/hal9000/vosk_model
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
```

### "No audio input/output"

```bash
# List audio devices
arecord -l    # Input devices
aplay -l      # Output devices

# Test microphone
arecord -D plughw:CARD=CMTECK,DEV=0 -f S16_LE -r 16000 -d 3 test.wav
aplay test.wav

# Update .env with correct device names if needed
```

## Next Steps

1. **Configure person names** - Add faces to face recognition database
2. **Customize prompts** - Edit `prompts.py` for HAL personality tweaks
3. **Add web search** - Install `duckduckgo_search` for internet access
4. **Deploy to Pi** - Use systemd service for autostart (see DEPLOYMENT.md)
5. **Update frontend** - Integrate Daily.co for WebRTC (see Phase 3 in CLAUDE.md)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Pipecat Pipeline                         │
│                                                              │
│  Audio In → STT → LLM → TTS → Audio Out                      │
│             ↓      ↓     ↓                                    │
│            VAD  Claude  Memory                               │
│                  Tools  Processor                            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Key Components:**
- **STT**: Vosk (local, lightweight) or Whisper (more accurate)
- **LLM**: Claude Sonnet 4 with HAL personality
- **TTS**: Piper with HAL-9000 voice model
- **VAD**: Silero for voice activity detection
- **Memory**: Per-person conversation tracking

## Performance Tips

### Reduce Latency

1. Use Vosk instead of Whisper for STT (`USE_VOSK=1`)
2. Enable HTTP TTS mode (`USE_HTTP_TTS=1`)
3. Use Daily.co WebRTC instead of local audio
4. Run on Raspberry Pi 5 or better hardware

### Improve Accuracy

1. Use Whisper for STT (`USE_VOSK=0`)
2. Enable Hailo acceleration if available (`USE_HAILO=1`)
3. Increase microphone gain (`MIC_GAIN=20` in .env)
4. Use higher quality audio devices

## Monitoring

View HAL logs in real-time:

```bash
# Main log
tail -f /home/erik/hal9000/backend_pipecat/hal_autonomous.log

# Flask backend log
tail -f /home/erik/hal9000/backend/hal9000.log
```

## Getting Help

- Check main `README.md` for architecture details
- See `CLAUDE.md` for development guidance
- Review logs for error messages
- Test components individually with `test_components.py`

## Resources

- [Pipecat Docs](https://docs.pipecat.ai/)
- [Claude API](https://docs.anthropic.com/)
- [Vosk Models](https://alphacephei.com/vosk/models)
- [Daily.co](https://www.daily.co/)
