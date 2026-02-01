# HAL 9000 Pipecat WebRTC Frontend

Modern WebRTC-based frontend for HAL 9000 using Daily.co and Pipecat.

## Overview

This frontend provides a low-latency, full-duplex voice interface to HAL 9000 using WebRTC instead of the legacy Web Speech API. It connects to a Daily.co room where the Pipecat backend handles real-time audio streaming.

## Features

- **WebRTC Audio**: Low-latency voice communication via Daily.co
- **Full-Duplex**: Natural conversation with interruption support
- **Real-time Transcript**: Live conversation history display
- **Visual Feedback**: HAL eye animation reflects conversation state
- **Audio Visualizer**: Real-time waveform display
- **Connection Management**: Easy room setup and connection controls

## Quick Start

### 1. Prerequisites

- Daily.co account (free tier available)
- HAL 9000 Pipecat backend running
- Modern web browser (Chrome, Firefox, Safari, Edge)

### 2. Setup Daily.co Room

#### Option A: Create via Dashboard

1. Go to [daily.co](https://www.daily.co/)
2. Sign up / Log in
3. Create a new room
4. Copy the room URL (e.g., `https://your-domain.daily.co/room-name`)

#### Option B: Create via API

```bash
curl -X POST https://api.daily.co/v1/rooms \
  -H "Authorization: Bearer YOUR_DAILY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "properties": {
      "enable_chat": false,
      "enable_screenshare": false,
      "enable_recording": false
    }
  }'
```

### 3. Launch Frontend

```bash
# Option 1: Direct file open
open frontend_pipecat/index.html

# Option 2: HTTP server (recommended)
cd frontend_pipecat
python -m http.server 8080

# Then visit: http://localhost:8080
```

### 4. Connect to HAL

1. Enter your Daily.co room URL
2. (Optional) Enter room token for secure access
3. Enter your name (e.g., "Dave")
4. Click "Connect to HAL"
5. Allow microphone access when prompted
6. Start speaking - HAL will respond in real-time!

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Browser)                        │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐  │
│   │  Daily.co WebRTC Client                              │  │
│   │  - Audio capture from microphone                     │  │
│   │  - Audio playback to speakers                        │  │
│   │  - Real-time streaming                               │  │
│   └──────────────────┬───────────────────────────────────┘  │
│                      │                                       │
└──────────────────────┼───────────────────────────────────────┘
                       │
                  WebRTC (Daily.co)
                       │
┌──────────────────────┼───────────────────────────────────────┐
│                      ▼                                        │
│   ┌──────────────────────────────────────────────────────┐  │
│   │  Pipecat Backend (hal_pipeline.py)                   │  │
│   │  - STT (Vosk/Whisper)                                │  │
│   │  - LLM (Claude with HAL personality)                 │  │
│   │  - TTS (HAL-9000 Piper voice)                        │  │
│   │  - Memory (per-person persistence)                   │  │
│   └──────────────────────────────────────────────────────┘  │
│                                                              │
│                 Backend (Raspberry Pi/Server)                │
└─────────────────────────────────────────────────────────────┘
```

## HAL Eye States

The HAL eye animation changes color and pulse rate based on conversation state:

| State | Color | Pulse Rate | Meaning |
|-------|-------|------------|---------|
| Idle | Red | 2s | HAL is waiting |
| Connecting | Yellow | 0.8s | Connecting to room |
| Listening | Green | 1s | HAL is listening |
| Speaking | Orange | 0.5s | HAL is speaking |
| Error | Bright Red | 0.3s | Connection error |

## Configuration

### Environment Variables

The frontend uses localStorage to persist settings:

- `hal_room_url`: Last used Daily.co room URL
- `hal_person_name`: Last used person name

### Daily.co Room Options

Configure room properties via Daily.co API:

```json
{
  "properties": {
    "enable_chat": false,
    "enable_screenshare": false,
    "enable_recording": false,
    "start_video_off": true,
    "start_audio_off": false,
    "max_participants": 2
  }
}
```

## Browser Compatibility

Tested browsers:

- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Edge 90+

**Note**: Microphone access requires HTTPS in production (localhost works without SSL).

## Deployment

### Static Hosting

Deploy to any static hosting service:

```bash
# Netlify
netlify deploy --dir=frontend_pipecat

# Vercel
vercel --prod frontend_pipecat

# AWS S3
aws s3 sync frontend_pipecat s3://your-bucket-name --acl public-read

# GitHub Pages
# Just push to gh-pages branch
```

### With SSL Certificate

For production, use HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name hal9000.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    root /var/www/hal9000/frontend_pipecat;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

## Troubleshooting

### "Microphone access denied"

- Click the lock icon in address bar
- Allow microphone access
- Refresh the page

### "Connection failed"

- Check Daily.co room URL is correct
- Verify room still exists (rooms expire after 10 minutes of inactivity)
- Check browser console for errors
- Ensure backend is running and connected to same room

### "No audio from HAL"

- Check speaker icon isn't muted
- Verify browser audio isn't muted
- Check backend TTS service is running
- Test audio with: `curl http://localhost:5000/health`

### "High latency"

- Check internet connection speed
- Use wired connection instead of WiFi
- Close other bandwidth-intensive applications
- Choose Daily.co server region closest to you

### "Echo or feedback"

- Use headphones instead of speakers
- Lower speaker volume
- Check microphone isn't picking up speaker output
- Enable echo cancellation in Daily.co settings

## Advanced Features

### Custom Styling

Edit `styles_webrtc.css` to customize:

- HAL eye colors and animations
- Transcript appearance
- Button styles
- Layout and spacing

### Integration with Original Frontend

You can run both frontends side-by-side:

- Original: Text-based TTS testing (http://localhost:8080)
- Pipecat: Live voice conversation (http://localhost:8081)

### Recording Conversations

Enable recording in Daily.co room properties:

```json
{
  "properties": {
    "enable_recording": "cloud",
    "recording_bucket": {
      "bucket_name": "your-s3-bucket",
      "bucket_region": "us-west-2"
    }
  }
}
```

## Performance

Expected performance metrics:

| Metric | Target | Typical |
|--------|--------|---------|
| Audio latency | <500ms | 200-400ms |
| STT latency | <1s | 300-800ms |
| LLM latency | <2s | 1-2s |
| TTS latency | <1s | 500-1000ms |
| Total latency | <4s | 2-3s |

## Resources

- [Daily.co Documentation](https://docs.daily.co/)
- [Daily.co JavaScript SDK](https://docs.daily.co/reference/daily-js)
- [WebRTC Samples](https://webrtc.github.io/samples/)
- [HAL 9000 Project](https://github.com/eriksalo/hal9000)
- [Pipecat Framework](https://docs.pipecat.ai/)

## License

MIT License - See LICENSE file for details

## Credits

- HAL 9000 character from "2001: A Space Odyssey"
- HAL-9000 voice by [campwill](https://huggingface.co/campwill/HAL-9000-Piper-TTS)
- WebRTC powered by [Daily.co](https://www.daily.co/)
- Framework by [Pipecat](https://pipecat.ai/)
