# Wake models

Custom [openWakeWord](https://github.com/dscripka/openWakeWord) models for HAL.

## `hello_hal.onnx`

The "Hello, HAL" wake phrase — HAL only opens a cloud STT/LLM/TTS session once it
hears this, so idle costs nothing.

- **Phrase:** "Hello, HAL"
- **Trained:** 2026-11-24, on a Windows RTX 4070 SUPER via WSL2 (openWakeWord custom training)
- **Data:** 250,000 synthetic positives (piper-sample-generator) + ACAV100M negative
  features, RIR-augmented
- **Eval:** accuracy 0.844, recall 0.689 @ threshold 0.5, **0 false-positives/hr**
- **Runtime:** ONNX, ~5 ms of one core per 80 ms frame on the Pi 5

The model keys itself as `hello_hal` (the filename stem), which becomes the phrase
openWakeWord reports.

### Tuning

The eval is conservative (0 FP/hr), so there is headroom to **lower**
`WAKE_THRESHOLD` below 0.5 if it misses you; raise it if it ever false-triggers.
See `../.env.example`.

### Retraining

The training environment, data cache, and version pins are recorded in Claude's
memory (`hal-wake-word-training-setup`). The reusable 17 GB data cache lives at
`~/oww-cache` in WSL, so the next wake word does not re-download anything.
