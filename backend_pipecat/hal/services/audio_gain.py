"""Fixed-gain / AGC / noise-gate conditioning for the mic input.

The USB conference mic captures well below line level even at max ALSA gain.
This processor applies (in order of preference) a noise gate, automatic gain
toward a target RMS, or a fixed gain, so frames reach Deepgram at a usable
level. All stages are disabled by default (gain=1, gate=0, target=0), in which
case the processor is not inserted into the pipeline at all.
"""

from __future__ import annotations

import numpy as np
from pipecat.frames.frames import Frame, InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class InputGainProcessor(FrameProcessor):
    """Noise-gated AGC. Falls back to fixed gain when target_rms is 0."""

    def __init__(
        self,
        gain: float = 1.0,
        gate_rms: float = 0.0,
        target_rms: float = 0.0,
        max_gain: float = 30.0,
    ) -> None:
        super().__init__()
        self._gain = float(gain)
        self._gate_rms = float(gate_rms)
        self._target_rms = float(target_rms)
        self._max_gain = float(max_gain)
        self._envelope = 0.0  # smoothed RMS of recent speech frames

    def _frame_gain(self, rms: float) -> float:
        if self._target_rms <= 0.0:
            return self._gain  # fixed-gain mode
        if rms > self._envelope:
            self._envelope = 0.5 * self._envelope + 0.5 * rms
        else:
            self._envelope = 0.9 * self._envelope + 0.1 * rms
        env = max(self._envelope, 1.0)
        return float(np.clip(self._target_rms / env, 1.0, self._max_gain))

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            samples = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32)
            if samples.size:
                rms = float(np.sqrt(np.mean(samples * samples)))
                if self._gate_rms > 0.0 and rms <= self._gate_rms:
                    frame.audio = np.zeros(samples.size, dtype=np.int16).tobytes()
                elif self._gain != 1.0 or self._target_rms > 0.0:
                    g = self._frame_gain(rms)
                    if g != 1.0:
                        np.clip(samples * g, -32768.0, 32767.0, out=samples)
                        frame.audio = samples.astype(np.int16).tobytes()
        await self.push_frame(frame, direction)
