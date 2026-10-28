# HAL 9000 — Pi audio/system setup

System-level configuration that lives outside the Python package. These are the
pieces needed to reproduce the working Pi deployment (Raspberry Pi 5, PipeWire,
CMTECK USB mic + USB speaker, Pi Camera).

## Audio: full-duplex with WebRTC echo cancellation

HAL uses a single USB mic (CMTECK) and a separate USB speaker. Without acoustic
echo cancellation the mic hears HAL's own voice, which causes HAL to transcribe
itself and to interrupt its own speech (choppy output). The fix is PipeWire's
`module-echo-cancel` (WebRTC), which inserts a virtual echo-cancelled mic and a
virtual sink between HAL and the hardware, and also provides AGC + noise
suppression (so no manual mic-gain tuning is needed).

```
CMTECK ───▶ echo-cancel-capture ─[WebRTC AEC]─▶ echo_cancel_source ─▶ HAL (captures)
USB spk ◀── echo-cancel-playback ◀────────────── echo_cancel_sink  ◀─ HAL (plays TTS)
```

### One-time setup

```bash
# 1. PipeWire is masked by default on this image; unmask + start it (user services).
systemctl --user unmask pipewire.service pipewire-pulse.service
systemctl --user start  pipewire.service pipewire-pulse.service wireplumber.service
loginctl enable-linger erik      # so they start at boot without a login

# 2. ALSA->PipeWire bridge, so PyAudio/PortAudio can reach the virtual devices.
sudo apt-get install -y pipewire-alsa

# 3. Echo-cancel module config (creates echo_cancel_source / echo_cancel_sink).
mkdir -p ~/.config/pipewire/pipewire.conf.d
cp deploy/pipewire/99-hal-echo-cancel.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber

# 4. Make the cancelled nodes the defaults (ids from `wpctl status`).
wpctl set-default <echo_cancel_source id>
wpctl set-default <echo_cancel_sink id>
```

After this, PyAudio enumerates a `pipewire` device (index 2 here) that routes to
the echo-cancelled nodes. HAL is pointed at it via `AUDIO_INPUT_DEVICE_INDEX=2`
and `AUDIO_OUTPUT_DEVICE_INDEX=2` in `.env`.

### Mic gain quirk (CMTECK / MV-SILICON chip)

The CMTECK reports its capture-gain control with a broken resolution, so ALSA
shows "100%" without actually applying it after a power-cycle — capture comes
back as pure noise floor. The value must be *written* to take effect.
`scripts/set_mic_gain.sh` does this and runs as an `ExecStartPre` of the HAL
service. (With the WebRTC AGC in front this matters less, but it keeps the raw
feed into the canceller at a sane level.)

## systemd

`deploy/systemd/hal.service` — note the two additions vs a plain unit:

- `ExecStartPre=.../scripts/set_mic_gain.sh` — write the CMTECK capture gain.
- `Environment="XDG_RUNTIME_DIR=/run/user/1000"` — lets the service (User=erik)
  reach the PipeWire socket at `/run/user/1000/pipewire-0`.

```bash
sudo cp deploy/systemd/hal.service /etc/systemd/system/hal.service
sudo systemctl daemon-reload && sudo systemctl restart hal.service
```

## Pipeline notes (why the STT changes exist)

- `PipelineParams` must set `audio_in_sample_rate` / `audio_out_sample_rate` to
  the transport's real rates (48000/24000). The default is 16000; leaving it
  meant Deepgram and the VAD both misread every frame and produced no output.
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
