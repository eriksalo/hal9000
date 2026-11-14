# HAL 9000 (Pi): XiaoZhi-style voice front-end plan

Status: planning + de-risking spike (2026-11-14). Nothing built yet. Companion to
`hal9000-mini/docs/xiaozhi-migration-plan.md`, but written for the **big** HAL (Raspberry Pi 5
+ Hailo-10H + Pipecat), with two deliberate differences from the mini's plan: the server runs
**on the Pi, not on Proxmox**, and we **keep Pipecat** rather than adopt `xiaozhi-esp32-server`.

## Goal

Give the big HAL the voice interaction of the AIPI Lite / Evo (which runs XiaoZhi firmware):
on-device wake word, hardware echo cancellation, streaming replies, barge-in. Keep everything
that makes this HAL more than a toy — the Cartesia HAL voice clone, layered memory (per-person
files + mem0), face recognition / presence, Claude Opus 5.5, and the Hailo offline fallback.

## Why this is the right move for *this* project

Recent sessions have put as much effort into the Linux audio stack as into the AI:

| Problem on the Pi | What the XiaoZhi model does instead |
|---|---|
| CMTECK delivering a flat ~100-rms noise floor through PipeWire; gain quirk needs a write on every (re)open | ES7210 mic array + ES8311 codec, a purpose-built audio front end |
| WebRTC AEC via PipeWire, fragile, only "warm" mid-call | AEC in the device firmware/codec, always on |
| openWakeWord now runs, but on a placeholder "hey jarvis", with "Hello HAL" untrained and an **open self-echo issue** (HAL waking on its own TTS) | **On-device wake word (ESP-SR) + hardware AEC — a solid wake phrase and no self-echo, zero cloud cost** |
| 16k/48k sample-rate bugs, device indices, XDG sockets | Opus frames over a WebSocket — no ALSA/PipeWire at all |

The always-listening-for-free requirement is satisfied in silicon here, and on-device AEC closes
the self-echo gap that the software stack still has open — which is the main reason this is worth doing.

## Target architecture

The ESP32 becomes a thin client; all intelligence stays in the existing Pipecat brain on the Pi.

```
ESP32-S3 thin client  ──Opus / WebSocket──▶  Pi 5 = HAL brain (unchanged)
  • mic array + hardware AEC                    • Pipecat 1.14 pipeline
  • on-device wake word (ESP-SR)                • Deepgram Flux → Claude Opus 5.5 → Cartesia HAL clone
  • speaker                                     • per-person memory + mem0 + face recognition
  • the HAL eye (480² display)                  • Hailo offline fallback
         ▲                                              │
         └───────── OTA/config HTTP (ws url + token) ───┘
```

| Layer | Pick | Notes |
|---|---|---|
| Device | Stock `xiaozhi-esp32` firmware | On-device wake word, AEC, Opus over WebSocket |
| Server | **Pipecat on the Pi** (not xiaozhi-esp32-server, not Proxmox) | Keeps the brain we already built |
| Transport | New `SingleClientWebsocketServerTransport` + a custom serializer | Dropped in via the existing `transport_factory` |
| STT / LLM / TTS | Deepgram Flux / Claude Opus 5.5 / Cartesia HAL clone | Unchanged; cascaded pipeline preserves the HAL clone |

Keep the pipeline cascaded (STT → LLM → TTS). Speech-to-speech models have fixed voices, so
they would lose the HAL clone.

### What stays, what is retired

- **Stays:** the whole Pipecat brain — `hal/pipeline.py`, memory, faces/presence, the HAL persona,
  Hailo fallback, and the status server / dashboard. The eye display and persona carry over.
- **Retired:** the `LocalAudioTransport` path (CMTECK), the PipeWire WebRTC echo-cancel config,
  `scripts/set_mic_gain.sh`, openWakeWord-on-the-Pi, and the USB speaker — the fragile layer.

## The bridge — spike findings (the one real new piece)

This is the risk I was asked to retire before touching hardware. **Verdict: feasible and
idiomatic.** The big project is already transport-pluggable — `AppContext(transport_factory=…)`
with three existing front ends (`hal_autonomous.py` / `hal_local.py` / `hal_webrtc.py`) — so this
is "add a fourth front end," not surgery on the brain.

### XiaoZhi wire protocol (what the device speaks)

Confirmed from the firmware repo (`78/xiaozhi-esp32`: `docs/websocket.md`, `main/ota.cc`):

1. **OTA/config bootstrap (HTTP, before the socket):** device POSTs to an OTA endpoint with
   headers `Device-Id` (MAC), `Client-Id` (UUID), `Activation-Version`; server replies JSON
   whose `websocket` object gives `{ "url": "ws://pi:PORT/xiaozhi/v1/", "token": "…" }` (plus
   `server_time`, optional `firmware`, `activation`). This is how the device learns our ws URL.
2. **WebSocket upgrade headers:** `Authorization: Bearer <token>`, `Protocol-Version`,
   `Device-Id`, `Client-Id`.
3. **Handshake:** device sends `hello` `{type, version:1, transport:"websocket",
   features:{aec,mcp}, audio_params:{format:"opus", sample_rate:16000, channels:1,
   frame_duration:60}}`. **Server must reply a `hello` within 10 s** with its own
   `audio_params` (downlink; commonly 24000 for TTS — honor whatever we advertise) and an
   optional `session_id` the device then echoes.
4. **Audio:** WebSocket **binary** frames carry Opus; **version 1 = raw Opus packet, no header**
   (what we target). Mic = device→server; TTS = server→device, sent between `tts start`/`stop`.
   60 ms @ 16 kHz = 960 samples/packet.
5. **Control JSON (text frames):**
   - Device→server: `listen {state:start|stop|detect, mode:auto|manual|realtime}` (turn control;
     `detect` carries the wake phrase), `abort {reason}` (barge-in), `mcp` (device tool calls).
   - Server→device: `tts {state:start|sentence_start|stop, text}`, `stt {text}` (user subtitle),
     `llm {emotion}`, `mcp`, `system`, `alert`.

### Pipecat integration (how we speak it)

Confirmed against Pipecat `v1.14.0` source (the version on the Pi):

- Use **`SingleClientWebsocketServerTransport`** / `SingleClientWebsocketServerParams` in
  `pipecat.transports.websocket.server` (the non-deprecated names; the old
  `transports.network.websocket_server` path is gone). Single-client is exactly right for one HAL.
- Write a **`XiaozhiFrameSerializer(FrameSerializer)`** — the same shape as the shipped telephony
  serializers (`twilio.py`, `telnyx.py`, `exotel.py`, `plivo.py`). Only `serialize` /
  `deserialize` are abstract; `setup` captures the negotiated sample rate and builds resamplers.
  - `deserialize(bytes)` → Opus-decode + resample → `InputAudioRawFrame`.
  - `deserialize(str)` → branch on `listen` / `abort` / `mcp`.
  - `serialize(OutputAudioRawFrame)` → resample + Opus-encode → binary frame.
  - `serialize(InterruptionFrame)` → `abort` JSON; `serialize(OutputTransportMessageFrame)` →
    `json.dumps(message)`.
- **The one gotcha:** `TTSStartedFrame`/`TTSStoppedFrame`, `BotStarted/StoppedSpeakingFrame`,
  and `TranscriptionFrame` **do not reach `serialize`** by default. To emit the `tts`/`stt`
  control JSON the device expects, insert a small **control-plane `FrameProcessor` just before
  `transport.output()`** that converts those internal frames into `OutputTransportMessageFrame`
  (which *does* serialize). ~40–80 LOC.
- **Opus:** Pipecat 1.14 has **no** built-in Opus codec and no `[opus]` extra — bring our own
  (`opuslib` / `PyOgg` / `av`), decode/encode per 60 ms / 960-sample frame. New dependency.
- **Resampling:** use `create_stream_resampler()` from `pipecat.audio.utils` (one for in, one for
  out) to bridge device 16 kHz ↔ Cartesia's output rate. (`create_default_resampler` in older
  docs does not exist in 1.14.)
- **Handshake + OTA:** send the server `hello` from the transport's `on_client_connected` handler
  (as an urgent transport message); add a tiny OTA route to the existing aiohttp status server
  (`hal/status_server.py`) returning the `websocket` url+token (~30 LOC).

### Frame mapping

| Direction | XiaoZhi wire | Pipecat frame |
|---|---|---|
| in | binary Opus (mic) | `InputAudioRawFrame` (after decode + resample) |
| in | `abort` | `StartInterruptionFrame` *(verify it triggers the interruption path)* |
| in | `listen {start/stop}` | turn signal — let Pipecat/Flux VAD drive turns, or map to UserStarted/Stopped |
| in | `listen {detect}` | wake word → start/unmute the session |
| out | `OutputAudioRawFrame` | binary Opus (between `tts start`/`stop`) |
| out | `TTSStarted/Stopped` → `OutputTransportMessageFrame` | `tts {state:start/stop}` |
| out | `TranscriptionFrame` → `OutputTransportMessageFrame` | `stt {text}` |
| out | `InterruptionFrame` | `abort` / stop sending audio |

### Effort

- `XiaozhiFrameSerializer`: ~150–250 LOC.
- Opus encode/decode wiring + repacketization to a steady 60 ms cadence: ~40–80 LOC.
- Control-plane processor (TTS/STT state → device JSON): ~40–80 LOC.
- `hal_xiaozhi.py` entrypoint + OTA route + hello handshake glue: ~80 LOC.
- **Total ≈ 300–500 LOC, ~1–3 focused days** for a working bridge, plus the Opus dependency.

### Hard parts / risks

1. Control frames not reaching `serialize` — handled by the control-plane processor above.
2. Opus framing: raw packets (not Ogg); buffering arbitrary-size TTS chunks into a steady
   60 ms/960-sample cadence out to the device.
3. Two-way rate matching (device 16 k ↔ Flux ↔ Cartesia out) via the two stream resamplers.
4. Inbound `abort` → interruption: returning `StartInterruptionFrame` from `deserialize` is the
   pragmatic hook; confirm it fires the pipeline's interruption path.
5. Byte endianness of the v2/v3 binary headers is unconfirmed — but v1 (raw Opus) avoids headers.

## Memory

Already ahead of the mini's plan — the Pi brain has per-person memory files, a background
extraction job, and mem0 recall. No change needed; it just rides along behind the new transport.

## Hardware

The current round-display ESP32 is **display-only** — it polls HTTP for the eye and has no audio.
XiaoZhi needs an audio-capable ESP32-S3:

- **Simplest:** reuse the mini's board (Waveshare ESP32-S3-Touch-AMOLED-1.75 — display + ES7210
  mic array + ES8311 codec in one). It could *become* the big HAL's face+voice unit.
- **Keep the current round display:** add an I2S mic + a MAX98357A amp (or an ES8311 codec) to an
  ESP32-S3 and drive the existing panel. More wiring, keeps the look.
- Mount the speaker facing away from the mics; a loud nearby speaker makes AEC harder.

## Steps

1. Flash stock `xiaozhi-esp32` firmware on an audio-capable ESP32-S3; verify against the hosted
   `xiaozhi.me` backend so we know the device works before any server work.
2. Build the bridge on the Pi: `XiaozhiFrameSerializer` + control-plane processor +
   `SingleClientWebsocketServerTransport`, wired through `transport_factory` in a new
   `hal_xiaozhi.py`. Add the OTA route to `hal/status_server.py`. Add the Opus dependency.
3. Point the device's OTA config at the Pi; get a round-trip: wake → speak → HAL replies in the
   clone voice, with barge-in.
4. Port the HAL eye animation to the XiaoZhi firmware (ESP-IDF, LVGL 9) driven by
   idle/listening/thinking/speaking states; or keep it as a separate display fed by the status API.
5. Retire the CMTECK / PipeWire / openWakeWord path once the new path is proven.

## Unverified assumptions / open questions

- That `xiaozhi-esp32` has a board definition for the exact board we pick (the mini assumed the
  Waveshare AMOLED board; confirm).
- Downlink sample rate: the firmware doc is self-contradictory (16000 vs 24000) — honor whatever
  our server `hello` advertises and resample TTS to match.
- Whether returning `StartInterruptionFrame` from `deserialize` cleanly triggers interruption.
- Opus 5.5 time-to-first-token on real voice turns; thinking cannot be disabled on Opus 5.5.
  Fallback is Sonnet 5.5 with thinking off.
- Byte endianness / exact layout of v2/v3 binary headers (only relevant if we enable server-side
  AEC via protocol v2; v1 raw-Opus avoids it).

## References

- XiaoZhi firmware protocol: `78/xiaozhi-esp32` → `docs/websocket.md`, `docs/mqtt-udp.md`, `main/ota.cc`
- XiaoZhi server (for comparison only): `xinnan-tech/xiaozhi-esp32-server`
- Pipecat v1.14.0: `pipecat.transports.websocket.server`, `pipecat.serializers.base_serializer`,
  and `serializers/twilio.py` (reference pattern); `pipecat.audio.utils` (resamplers)
- This repo's pluggable transport: `backend_pipecat/hal/app.py` (`transport_factory`),
  `hal_webrtc.py` (precedent for a non-local transport)
