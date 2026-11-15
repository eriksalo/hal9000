"""Mute mic input while HAL is speaking (self-echo guard).

With a USB mic and a separate room speaker in the same room, HAL's own TTS leaks
into the mic; Deepgram Flux then transcribes HAL's voice as a user turn and
interrupts HAL mid-sentence (and queues a phantom reply). Until acoustic echo
cancellation is good enough to separate the user's voice from HAL's, the reliable
fix is to drop mic audio while the bot is speaking, plus a short hangover to
swallow the echo tail after playback stops.

Side effect: this disables barge-in (the user cannot interrupt HAL while it is
speaking). Re-enabling barge-in depends on improving the AEC.

The output transport pushes BotStarted/StoppedSpeakingFrame upstream as well as
downstream, so this processor sees them even though it sits at the input end of
the pipeline.
"""

from __future__ import annotations

import time

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class EchoMuteProcessor(FrameProcessor):
    """Drop InputAudioRawFrames while the bot speaks, plus a hangover tail."""

    def __init__(self, hangover_secs: float = 0.4) -> None:
        super().__init__()
        self._hangover = max(0.0, float(hangover_secs))
        self._bot_speaking = False
        self._unmute_at = 0.0

    def _muted(self) -> bool:
        return self._bot_speaking or time.monotonic() < self._unmute_at

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            if not self._bot_speaking:
                logger.debug("EchoMute: muting mic while HAL speaks")
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._unmute_at = time.monotonic() + self._hangover
        if isinstance(frame, InputAudioRawFrame) and self._muted():
            return  # drop: don't let HAL hear itself
        await self.push_frame(frame, direction)
