#!/usr/bin/env python3
"""Wake-word smoke test.

    python scripts/wake_test.py                  # listen on the mic for 45 s, print scores
    python scripts/wake_test.py --seconds 20
    python scripts/wake_test.py --wav clip.wav   # score a 16 kHz mono PCM WAV offline

Prints every frame scoring >= 0.3, each detection, and the peak score at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hal.config import load_config  # noqa: E402
from hal.wake import WakeWordListener, load_wake_model  # noqa: E402


def score_wav(path: str) -> int:
    cfg = load_config()
    model = load_wake_model(cfg.wake)
    key = next(iter(model.models))
    frames = model.predict_clip(path)
    scores = [float(f.get(key, 0.0)) for f in frames]
    peak = max(scores) if scores else 0.0
    hits = sum(1 for s in scores if s >= cfg.wake.threshold)
    print(f"'{key}' on {path}: {len(scores)} frames, peak {peak:.2f}, {hits} frames >= {cfg.wake.threshold}")
    return 0 if hits else 1


async def listen(seconds: float) -> int:
    cfg = load_config()
    fired: list[float] = []

    async def on_wake() -> None:
        fired.append(time.time())
        print(f"\n*** WAKE DETECTED (#{len(fired)}) ***\n", flush=True)

    listener = WakeWordListener(cfg.wake, cfg.audio, on_wake=on_wake)
    await listener.start(asyncio.get_running_loop())

    peak = 0.0
    print(f"Listening {seconds:.0f}s for '{listener.phrase}'. Say the wake phrase now...", flush=True)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        s = listener.last_score
        peak = max(peak, s)
        if s >= 0.3:
            print(f"  score {s:.2f}", flush=True)
    await listener.stop()
    print(f"\nDone. detections={len(fired)} peak_score={peak:.2f}", flush=True)
    return 0 if fired else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", help="score a 16 kHz mono 16-bit WAV file instead of the mic")
    ap.add_argument("--seconds", type=float, default=45.0, help="how long to listen on the mic")
    args = ap.parse_args()
    if args.wav:
        return score_wav(args.wav)
    return asyncio.run(listen(args.seconds))


if __name__ == "__main__":
    raise SystemExit(main())
