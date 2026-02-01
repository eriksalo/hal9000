# HAL 9000 Pipecat Backend

Full-duplex conversational AI backend using Pipecat framework.

## Overview

This is a modernized version of the HAL 9000 backend that uses [Pipecat](https://github.com/pipecat-ai/pipecat) for streaming audio conversations. Key improvements over the original backend:

- **Full-duplex streaming**: Natural conversation with sub-second latency
- **Unified pipeline**: Single framework for ASR, LLM, TTS, and transport
- **Better interruption handling**: Users can interrupt HAL mid-sentence
- **WebRTC support**: Low-latency audio via Daily.co
- **Reduced boilerplate**: Pipecat handles threading, buffering, and synchronization

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Pipecat Pipeline                         │
│  ┌─────────┐    ┌─────────────┐    ┌──────────────────┐     │
│  │  Vosk/  │───▶│   Claude    │───▶│  HAL-9000 Piper  │     │
│  │ Whisper │    │(w/ memory)  │    │      TTS         │     │
│  │   STT   │    │             │    │                  │     │
│  └─────────┘    └──────┬──────┘    └──────────────────┘     │
│       ▲                │                    │                │
│       │                ▼                    ▼                │
│  ┌────┴────┐    ┌─────────────┐    ┌──────────────────┐     │
│  │  Silero │    │   Memory    │    │  Daily WebRTC    │     │
│  │   VAD   │    │ Processor   │    │   Transport      │     │
│  └─────────┘    └─────────────┘    └──────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Components

### Core Pipeline (`hal_pipeline.py`)
- Main orchestrator for HAL conversation flow
- Integrates all services into unified pipeline
- Manages memory context and personalization

### HAL Piper TTS (`hal_piper_tts.py`)
- Custom Pipecat TTS service for HAL-9000 voice
- Supports both direct Piper and HTTP endpoint modes
- Outputs streaming audio frames

### HAL Whisper/Vosk STT (`hal_whisper_stt.py`)
- Local speech recognition using Whisper or Vosk
- Optional Hailo-10H GPU acceleration
- Streaming transcription with interim results

### Memory Frame Processor
- Integrated into pipeline for conversation tracking
- Reuses existing `MemoryStore` for persistence
- Extracts facts and updates person profiles

## Installation

```bash
cd backend_pipecat

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys and configuration
```

## Configuration

### Required Environment Variables

- `ANTHROPIC_API_KEY`: Your Claude API key
- `DAILY_ROOM_URL`: Daily.co room URL for WebRTC
- `DAILY_TOKEN`: Daily.co authentication token

### Optional Configuration

- `USE_VOSK`: Use Vosk (1) or Whisper (0) for STT
- `USE_HAILO`: Enable Hailo GPU acceleration for Whisper
- `USE_HTTP_TTS`: Use Flask endpoint (1) or direct Piper (0)
- `PERSON_NAME`: Name of person talking to HAL (for memory context)

## Running the Pipeline

```bash
# Make sure Flask backend is running (for HTTP TTS mode)
cd ../backend
python app.py &

# Start Pipecat pipeline
cd ../backend_pipecat
python hal_pipeline.py
```

## Daily.co Setup

The pipeline uses Daily.co for WebRTC transport. To set up:

1. Create account at [daily.co](https://www.daily.co/)
2. Create a room via API or dashboard
3. Generate a meeting token
4. Set `DAILY_ROOM_URL` and `DAILY_TOKEN` in `.env`

### Creating a Daily Room

```bash
# Via API
curl -X POST https://api.daily.co/v1/rooms \
  -H "Authorization: Bearer YOUR_DAILY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"properties": {"enable_chat": false}}'
```

## Frontend Integration

The frontend needs to be updated to use Daily.co client instead of Web Speech API:

```html
<script src="https://unpkg.com/@daily-co/daily-js"></script>
<script>
  const callFrame = window.DailyIframe.createFrame({
    showLeaveButton: false,
    iframeStyle: { display: 'none' }
  });

  await callFrame.join({
    url: 'DAILY_ROOM_URL',
    token: 'DAILY_TOKEN'
  });
</script>
```

## Reused Components

These components are copied from the original backend:

- `memory_store.py`: Per-person conversation tracking
- `prompts.py`: HAL personality and system prompts
- `face_recognition_service.py`: Face detection and recognition

## Differences from Original Backend

| Feature | Original Backend | Pipecat Backend |
|---------|------------------|-----------------|
| Audio flow | Request/response | Full-duplex streaming |
| Latency | 2-3 seconds | Sub-second |
| Interruptions | Not supported | Natural interruption handling |
| State management | Manual state machine | Frame-based pipeline |
| Transport | Web Speech API | WebRTC (Daily.co) |
| Threading | Manual locks/queues | Built-in backpressure |

## Troubleshooting

### Pipeline won't start

- Check all environment variables are set
- Verify Daily.co credentials are valid
- Ensure Flask backend is running (if USE_HTTP_TTS=1)

### No audio output

- Check Daily.co room is active
- Verify Piper model exists at `/home/erik/hal9000/hal_9000_model/hal.onnx`
- Test Flask /api/synthesize endpoint directly

### STT not working

- For Vosk: Verify model at `/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15`
- For Whisper: Check `openai-whisper` is installed
- For Hailo: Ensure Hailo-10H is connected and HailoRT installed

### Memory not persisting

- Check `/home/erik/hal9000/memory/people/` directory exists
- Verify write permissions
- Check logs for MemoryStore errors

## Next Steps

See main CLAUDE.md for migration phases:

- ✅ Phase 1: Parallel development (this backend)
- ⏭ Phase 2: Replace conversation_manager.py
- ⏭ Phase 3: Update frontend for WebRTC
- ⏭ Phase 4: Full cutover and deprecate old backend

## Resources

- [Pipecat Documentation](https://docs.pipecat.ai/)
- [Daily.co API](https://docs.daily.co/reference/rest-api)
- [Anthropic Claude](https://docs.anthropic.com/)
