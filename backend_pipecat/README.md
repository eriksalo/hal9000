# HAL 9000 — conversational agent (Pipecat 1.x)

Self-contained on a Raspberry Pi 5 + Hailo-10H, cloud-assisted for the parts
that matter most (brain, ears, voice). Watches the camera, greets people it
knows, asks strangers their name, holds a natural full-duplex conversation, and
remembers everyone across conversations.

```
Pi 5 (edge)                                  Cloud (over the internet)
├─ mic / speakers  ── LocalAudioTransport     ├─ Deepgram Flux      STT + end-of-turn
├─ Pi Camera ─ face recognition ─ presence    ├─ Claude Opus 5.5    conversation (tools, 1h prompt cache)
├─ Silero VAD + Smart Turn v3.2 (fallback)    ├─ Claude Haiku 5.5   reflection, web search, vision
├─ Piper HAL voice (fallback)                 └─ Cartesia Sonic     cloned HAL voice
├─ Hailo-10H: Whisper-Small, Qwen3 (offline)
├─ mem0 OSS + Qdrant (on disk) + notes.md
└─ status API :5000 → ESP32 eye display
```

## Layout

```
backend_pipecat/
├─ hal_autonomous.py      camera → greet → converse → remember (production entry point)
├─ hal_local.py           one conversation over local audio, no camera (dev)
├─ hal_webrtc.py          browser client via Pipecat dev runner, http://<pi>:7860/client
├─ hal/
│  ├─ config.py           every knob, loaded from .env
│  ├─ prompts.py          persona (stable, cached) + per-person context
│  ├─ pipeline.py         HALSession: builds and runs one Pipecat pipeline per conversation
│  ├─ app.py              AppContext: shared resources, presence → conversation orchestration
│  ├─ state.py            what HAL is doing right now (feeds the ESP32)
│  ├─ status_server.py    aiohttp API: /api/hal/display, /api/hal/face_frame, /api/hal/status, …
│  ├─ connectivity.py     online? → cloud profile : Hailo/offline profile
│  ├─ services/           stt.py, tts.py, llm.py factories; hailo_stt.py (Whisper on the NPU)
│  ├─ tools/              remember / recall_memories / update_notes / web_search / analyze_camera /
│  │                      get_current_time / end_conversation / introduce_person
│  ├─ memory/             store.py (profiles, transcripts), notes.py (HAL's own notes),
│  │                      semantic.py (mem0 OSS), extraction.py (Haiku reflection)
│  └─ vision/             camera.py, faces.py, tracker.py, presence.py
├─ tests/                 pytest, runs anywhere (no hardware)
├─ systemd/               hal.service, hal-piper.service
├─ requirements.txt
└─ .env.example
```

## How a conversation works

1. Someone says the wake phrase → `AppContext.start_conversation(name, opening="wake")`,
   where `name` is the recognised face in view (or the unknown-person flow, or `PERSON_NAME`).
   With `WAKE_ENABLED=false`, `PresenceMonitor` seeing a known face for 3 s starts it instead.
2. `HALSession` loads the person's profile summary, HAL's `notes.md`, and the top mem0
   memories, builds the system prompt (persona first so the prompt cache hits), and
   registers the tools.
3. An opening instruction is queued and HAL acknowledges them by name (or greets them, when
   started by presence), in context.
4. Deepgram Flux decides when the user has finished speaking; Claude replies; Cartesia
   streams HAL's voice. Interruptions are handled by the aggregators.
5. HAL calls `remember` as it learns things and `end_conversation` when they say goodbye.
   Silence triggers two check-ins, then a goodbye. Leaving the camera view ends it too.
6. On close, Haiku reflects on the transcript (facts, summary, mood, open threads) →
   `profile.json`, `summary.json`, `notes.md`, and the transcript is ingested into mem0.

Strangers: HAL asks their name; when they answer, `introduce_person` links the last
unknown face encoding to that name and the conversation continues as that person.

Offline: if `api.anthropic.com` is unreachable at session start, the session uses
`HAILO_ENABLED` → Hailo Whisper + hailo-ollama (Qwen3-1.7B) + Piper. No tools, no memory
write-back, but HAL still answers.

## Setup

```bash
cd ~/hal9000
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend_pipecat/requirements.txt
sudo apt install python3-picamera2          # Pi Camera
cp backend_pipecat/.env.example backend_pipecat/.env   # fill in keys
```

Keys you need: `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` +
`CARTESIA_VOICE_ID` (clone the HAL voice from a few clean Douglas Rain clips in the
Cartesia dashboard, paste the voice id). Everything else has a working default.

Local HAL voice fallback (Piper):

```bash
python -m piper.http_server --model hal_9000_model/hal.onnx --port 5002
```

Find audio device indices:

```bash
python -c "import pyaudio;p=pyaudio.PyAudio();[print(i,p.get_device_info_by_index(i)['name']) for i in range(p.get_device_count())]"
```

## Run

```bash
cd backend_pipecat
python hal_local.py --person Erik          # talk to HAL now, no camera
python hal_webrtc.py -t webrtc --host 0.0.0.0   # browser: http://<pi>:7860/client
python hal_autonomous.py                   # production: camera + status API on :5000
pytest -q tests                            # unit tests
```

Status API: `curl localhost:5000/api/hal/status`, `curl -X POST localhost:5000/api/hal/speak -d '{"text":"Hello, Dave."}' -H 'content-type: application/json'`.

Install as a service:

```bash
sudo cp systemd/hal.service systemd/hal-piper.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now hal-piper hal
journalctl -fu hal
```

## Tuning

| Symptom | Knob |
|---|---|
| HAL answers too slowly | `LLM_MODEL=claude-sonnet-5-5`, keep `LLM_EFFORT=low`; check `usage.cache_read_input_tokens` in logs |
| HAL cuts you off mid-sentence | Flux: raise `eot_threshold` in `services/stt.py` (0.7 → 0.8); local: raise `SMART_TURN_STOP_SECS` |
| HAL waits too long after you stop | lower `eot_threshold` / `SMART_TURN_STOP_SECS`; `VAD_STOP_SECS` |
| Name misheard | add to `STT_KEYTERMS` |
| Wake word misses you / false-triggers | lower / raise `WAKE_THRESHOLD`; `WAKE_TRIGGER_FRAMES=2` to require two frames; `WAKE_VAD_THRESHOLD=0.3` |
| HAL answers conversations not meant for it | keep `WAKE_ENABLED=true` (presence alone no longer starts a session) |
| HAL forgets things | check `memory/people/<name>/notes.md` and `summary.json`; `MEMORY_SEMANTIC_ENABLED` |
| Pi CPU pegged | `SMART_TURN_CPU_COUNT=1`, lower `CAMERA_FPS`, raise `DETECTION_INTERVAL_SECS` |

## Wake word

`hal/wake.py` runs [openWakeWord](https://github.com/dscripka/openWakeWord) on the
echo-cancelled mic whenever no conversation is active (~5 ms per 80 ms frame on the Pi 5,
ONNX runtime). On a hit it starts a session for whoever the camera sees; the listener is
paused for the whole conversation so it never hears HAL's own voice. Nothing streams to the
cloud while HAL is idle, and HAL stops answering conversations that were not addressed to it.

```bash
pip install --no-deps 'openwakeword>=0.6'   # tflite-runtime has no py3.13/arm64 wheel; ONNX is used
python scripts/wake_test.py                 # listen 45 s, print scores and detections
python scripts/wake_test.py --wav clip.wav  # score a 16 kHz mono WAV offline
```

Knobs: `WAKE_MODEL`, `WAKE_THRESHOLD`, `WAKE_TRIGGER_FRAMES`, `WAKE_REFRACTORY_SECS` (see
`.env.example`). The dashboard pill shows `wake armed` / `wake paused`.

**Custom "Hey HAL" phrase.** The stock models are `hey_jarvis`, `hey_mycroft`, `alexa`,
`hey_rhasspy`. To get HAL's own name, train a model with the openWakeWord
[automatic training notebook](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb)
(Colab, ~1 h on a free GPU; it synthesises the phrase with TTS, no recordings needed), download
the resulting `hey_hal.onnx`, put it under `backend_pipecat/models/`, and set
`WAKE_MODEL=models/hey_hal.onnx`. Two-syllable phrases like "Hey HAL" false-trigger more than
longer ones; "Hello HAL" or "HAL, listen" train noticeably cleaner.

## Hailo-10H

Requires HailoRT ≥ 5.2.0 and hailo-apps checked out at `HAILO_APPS_PATH` (default
`/home/erik/hailo-apps`) with the Whisper HEFs downloaded (`hailo-download-resources`).
Set `HAILO_ENABLED=true` to use the NPU as the offline fallback (and `STT_PROVIDER=hailo`
to use it as the primary ears). hailo-ollama must be running for the offline brain.

## Legacy

`backend/` (Flask + Vosk + hand-rolled state machine) and `frontend_pipecat/` (Daily.co
client) are superseded by this package and the prebuilt WebRTC client. They are kept for
reference only.
