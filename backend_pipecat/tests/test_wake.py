import asyncio
import time

import numpy as np

from hal.config import AudioConfig, WakeConfig
from hal.prompts import wake_instruction
from hal.vision.faces import UNKNOWN
from hal.wake import FRAME_SAMPLES, WakeWordListener, choose_wake_person

FRAME = np.zeros(FRAME_SAMPLES, dtype=np.int16)


class FakeModel:
    def __init__(self, scores):
        self.models = {"hey_hal": object()}
        self.scores = list(scores)
        self.resets = 0

    def predict(self, x, **kwargs):
        return {"hey_hal": self.scores.pop(0) if self.scores else 0.0}

    def reset(self):
        self.resets += 1


def make_listener(scores, monkeypatch, **cfg):
    fired = []

    async def on_wake():
        fired.append(True)

    config = WakeConfig(**cfg)
    listener = WakeWordListener(config, AudioConfig(), on_wake=on_wake, model=FakeModel(scores))
    fires = []
    monkeypatch.setattr(listener, "_fire", lambda: fires.append(True))
    return listener, fires


def test_fires_once_above_threshold(monkeypatch):
    listener, fires = make_listener([0.1, 0.9, 0.95, 0.2], monkeypatch, threshold=0.5, refractory_secs=3.0)
    assert listener.phrase == "hey_hal"
    assert listener.process(FRAME) is False
    assert listener.process(FRAME) is True
    assert listener._model.resets == 1  # buffers cleared after a detection
    # Still above threshold but inside the refractory window: no second fire.
    assert listener.process(FRAME) is False
    assert listener.process(FRAME) is False
    assert len(fires) == 1


def test_trigger_frames_requires_consecutive_hits(monkeypatch):
    listener, fires = make_listener([0.9, 0.1, 0.9, 0.9], monkeypatch, threshold=0.5, trigger_frames=2)
    assert listener.process(FRAME) is False
    assert listener.process(FRAME) is False  # dip resets the run
    assert listener.process(FRAME) is False
    assert listener.process(FRAME) is True
    assert len(fires) == 1


def test_refractory_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    listener, fires = make_listener([0.9, 0.9, 0.9], monkeypatch, threshold=0.5, refractory_secs=3.0)
    assert listener.process(FRAME) is True
    now[0] += 1.0
    assert listener.process(FRAME) is False
    now[0] += 2.5
    assert listener.process(FRAME) is True
    assert len(fires) == 2


def test_resume_resets_model_and_reports_armed(monkeypatch):
    armed = []
    listener = WakeWordListener(
        WakeConfig(), AudioConfig(), on_wake=_noop, on_armed_change=armed.append, model=FakeModel([])
    )
    listener.pause()
    listener.resume()
    assert armed == [False, True]
    assert listener._model.resets == 1
    assert listener.armed


def test_fire_schedules_callback_on_loop():
    hits = []

    async def on_wake():
        hits.append(True)

    async def run():
        listener = WakeWordListener(WakeConfig(), AudioConfig(), on_wake=on_wake, model=FakeModel([0.99]))
        listener._loop = asyncio.get_running_loop()
        assert listener.process(FRAME) is True
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert hits == [True]


def test_choose_wake_person():
    assert choose_wake_person(known_present=["Erik"], present=["Erik", UNKNOWN], default_person="Dave") == "Erik"
    assert choose_wake_person(known_present=[], present=[UNKNOWN], default_person="Dave") == UNKNOWN
    assert choose_wake_person(known_present=[], present=[], default_person="Dave") == "Dave"


def test_wake_instruction_mentions_person():
    assert "Erik" in wake_instruction("Erik")
    assert "name" in wake_instruction(UNKNOWN).lower()


async def _noop() -> None:
    pass
