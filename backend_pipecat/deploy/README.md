# HAL 9000 — Pi audio/system setup

System-level configuration that lives outside the Python package. These are the
pieces needed to reproduce the working Pi deployment (Raspberry Pi 5, PipeWire,
ReSpeaker XVF3800 4-Mic Array with a speaker on its JST connector, Pi Camera).

## Audio: ReSpeaker XVF3800 (hardware AEC over USB)

HAL's mic and speaker are both the **Seeed ReSpeaker XVF3800 4-Mic Array**,
connected over USB-C, with a passive 8Ω speaker wired to the board's JST
connector (driven by the onboard LM48511 class-D amp). The XVF3800 is a
VocalFusion speakerphone SoC: it does **acoustic echo cancellation, AGC,
beamforming and noise suppression in hardware**. HAL's TTS is sent down the USB
cable, the board plays it on the JST speaker and uses it as the AEC far-end
reference, and the mic capture comes back already echo-cancelled — so HAL does
not hear its own voice and does not interrupt itself.

```
HAL (plays TTS) ─USB─▶ XVF3800 ─▶ JST speaker (8Ω)
HAL (captures)  ◀USB─ XVF3800 mic array  [HW AEC/AGC/beamforming/NS]
```

The board is USB UAC, **locked to 16 kHz, S16_LE, 2ch** (`/proc/asound/card2/stream0`);
it advertises no other rate. PipeWire still runs (routing + any resampling), but
the **software WebRTC echo-cancel is NOT used** — it would double-process against
the hardware AEC. The legacy `deploy/pipewire/99-hal-echo-cancel.conf` is kept
only for reference / a non-AEC mic; do not install it with the ReSpeaker.

### One-time setup

```bash
# 1. PipeWire is masked by default on this image; unmask + start it (user services).
systemctl --user unmask pipewire.service pipewire-pulse.service
systemctl --user start  pipewire.service pipewire-pulse.service wireplumber.service
loginctl enable-linger erik      # so they start at boot without a login

# 2. ALSA->PipeWire bridge, so PyAudio/PortAudio can reach PipeWire.
sudo apt-get install -y pipewire-alsa

# 3. Make the ReSpeaker the default sink + source (ids from `wpctl status`).
wpctl set-default <reSpeaker sink id>
wpctl set-default <reSpeaker source id>
```

PyAudio exposes only `pipewire` / `default` devices (not raw `hw:`), both routed
to the PipeWire default nodes. HAL leaves `AUDIO_INPUT_DEVICE_INDEX` /
`AUDIO_OUTPUT_DEVICE_INDEX` **unset** in `.env` so it follows that default — do
not hardcode a numeric index (it drifts when the node graph changes). Sample
rates are `AUDIO_IN_SAMPLE_RATE=16000` / `AUDIO_OUT_SAMPLE_RATE=16000`, and
`ECHO_MUTE=false` (the software echo-mute is unnecessary with hardware AEC, and
turning it off keeps barge-in working).

### Playback gain (ReSpeaker)

The board's USB mixer boots with its PCM playback controls attenuated — `'PCM',1`
comes up at **−20 dB** — which makes the JST speaker very quiet, and ALSA mixer
state is not persisted across a reboot or USB replug. `scripts/set_audio_gain.sh`
sets both PCM playback controls to 0 dB and runs as an `ExecStartPre` of the HAL
service. (PipeWire's own sink volume is separate; set it with
`wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0`.)

## systemd

`deploy/systemd/hal.service` — note the two additions vs a plain unit:

- `ExecStartPre=.../scripts/set_audio_gain.sh` — set the ReSpeaker playback gain.
- `Environment="XDG_RUNTIME_DIR=/run/user/1000"` — lets the service (User=erik)
  reach the PipeWire socket at `/run/user/1000/pipewire-0`.

```bash
sudo cp deploy/systemd/hal.service /etc/systemd/system/hal.service
sudo systemctl daemon-reload && sudo systemctl restart hal.service
```

## Pipeline notes (why the STT changes exist)

- `PipelineParams` must set `audio_in_sample_rate` / `audio_out_sample_rate` to
  the device's real rate (16000 for the ReSpeaker). The default is also 16000,
  but keep these explicit and matched to the device — a mismatch makes Deepgram
  and the VAD misread every frame and produce no output.
- The aggregator VAD is only wired for non-Flux STT. Deepgram Flux does its own
  server-side turn detection; attaching a local VAD there threw per-frame errors.

## Camera

Pi Camera (ov5647) over CSI. If `rpicam-hello --list-cameras` reports "No
cameras available!", it is almost always a marginal CSI ribbon connection —
reseat both ends and reboot (CSI is not hot-pluggable). The feed is mounted
upside down on this unit, corrected in software with `CAMERA_ROTATE_180=true`.

## Keep PipeWire off the camera

Installing pipewire-alsa pulls in the libcamera SPA plugin, which makes PipeWire
enumerate (and potentially grab) the Pi camera, contending with HALs Picamera2.
Remove it and pin it so apt upgrades do not bring it back:

    sudo apt-get remove -y pipewire-libcamera libspa-0.2-libcamera
    printf "Package: pipewire-libcamera\nPin: release *\nPin-Priority: -1\n" | sudo tee /etc/apt/preferences.d/no-pipewire-libcamera
    printf "Package: libspa-0.2-libcamera\nPin: release *\nPin-Priority: -1\n" | sudo tee -a /etc/apt/preferences.d/no-pipewire-libcamera
    systemctl --user restart pipewire pipewire-pulse wireplumber

HAL uses libcamera directly via Picamera2, so this does not affect the camera
feed. The camera thread also retries on its own if the CSI link drops.
