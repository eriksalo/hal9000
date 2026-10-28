#!/usr/bin/env bash
# Explicitly program the CMTECK USB mic capture gain.
# The MV-SILICON chip reports its volume control with a broken resolution, so
# snd-usb-audio displays 100% without actually applying it after a power-cycle.
# The value must be *written* to take effect, or capture is pure noise floor.
set -uo pipefail
card=$(arecord -l | grep -i cmteck | grep -oP "card \K[0-9]+" | head -1)
if [ -z "${card:-}" ]; then
  echo "set_mic_gain: CMTECK not found" >&2
  exit 0
fi
# Double-write (low then max) guarantees the USB control is pushed to hardware
# even when the stored value already reads as max.
amixer -c "$card" cset name="Mic Capture Volume" 1000 >/dev/null 2>&1 || true
amixer -c "$card" cset name="Mic Capture Volume" 3996 >/dev/null 2>&1 || true
amixer -c "$card" cset name="Mic Capture Switch" on   >/dev/null 2>&1 || true
echo "set_mic_gain: CMTECK on card $card set to max capture gain"
