#!/usr/bin/env bash
# Rebuild "Russian vs Italian — Who Makes More Money With AI?"  Needs python3, node + playwright (chromium), ffmpeg.
set -euo pipefail; cd "$(dirname "$0")"
pip install -q kokoro-onnx soundfile onnx scipy numpy
mkdir -p build output
python3 src/voices.py            # 3 character voices + phoneme/word timing (downloads Kokoro once, ~350 MB)
node src/render.js video 30 4    # animation -> build/video_noaudio.mp4 + build/events.json (SFX cues)
python3 src/mix_audio.py         # score + ambience + SFX + dialogue -> build/mix.wav
ffmpeg -y -loglevel error -i build/video_noaudio.mp4 -i build/mix.wav -af "loudnorm=I=-14:TP=-1.0:LRA=11" \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -movflags +faststart -shortest output/russian-vs-italian-ai-money.mp4
python3 src/make_subs.py         # SRT + word-highlight ASS + word JSON
node src/render.js thumb 50.6    # thumbnail
