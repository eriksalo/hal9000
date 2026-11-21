#!/usr/bin/env bash
# Program the ReSpeaker XVF3800 playback gain to 0 dB before HAL starts.
# The board's USB mixer boots with its PCM playback controls attenuated
# ('PCM',1 at -20 dB), which makes the JST speaker very quiet, and ALSA mixer
# state is not persisted across a reboot or USB replug. So set it each start.
set -uo pipefail
card=$(aplay -l 2>/dev/null | grep -iE "reSpeaker|XVF3800|Array" | grep -oP "card \K[0-9]+" | head -1)
if [ -z "${card:-}" ]; then
  echo "set_audio_gain: ReSpeaker not found" >&2
  exit 0
fi
# Both playback controls to max (0 dB); 'PCM',1 is the one that boots at -20 dB.
amixer -c "$card" sset "PCM",0 60 >/dev/null 2>&1 || true
amixer -c "$card" sset "PCM",1 60 >/dev/null 2>&1 || true
echo "set_audio_gain: ReSpeaker on card $card set to 0 dB playback"
