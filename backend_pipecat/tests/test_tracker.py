import time

from hal.vision.tracker import PersonTracker

LOC = (0, 10, 10, 0)


def test_arrival_requires_presence_threshold(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    tracker = PersonTracker(presence_threshold=3.0, departure_threshold=5.0, greeting_cooldown=300.0)

    assert not tracker.update([("Erik", LOC)])
    now[0] += 2.0
    assert not tracker.update([("Erik", LOC)])
    now[0] += 1.5
    event = tracker.update([("Erik", LOC)])
    assert event.arrived == ["Erik"]
    # No repeat arrival while still present
    now[0] += 1.0
    assert not tracker.update([("Erik", LOC)])


def test_departure_and_cooldown(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    tracker = PersonTracker(presence_threshold=0.0, departure_threshold=5.0, greeting_cooldown=300.0)

    tracker.update([("Erik", LOC)])
    now[0] += 0.1
    assert tracker.update([("Erik", LOC)]).arrived == ["Erik"]
    tracker.mark_in_conversation("Erik", True)

    now[0] += 6.0
    event = tracker.update([])
    assert event.departed == ["Erik"]
    assert tracker.present() == []

    # Comes back within cooldown: tracked again but no new arrival event
    now[0] += 1.0
    tracker.update([("Erik", LOC)])
    now[0] += 1.0
    assert not tracker.update([("Erik", LOC)]).arrived

    # After cooldown expires, greet again
    now[0] += 400.0
    assert tracker.update([("Erik", LOC)]).arrived == ["Erik"]


def test_unknown_face_not_in_present_known():
    tracker = PersonTracker(presence_threshold=0.0, departure_threshold=5.0, greeting_cooldown=0.0)
    tracker.update([("Unknown", LOC), ("Erik", LOC)])
    assert set(tracker.present()) == {"Unknown", "Erik"}
    assert tracker.present_known() == ["Erik"]
