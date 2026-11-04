#!/usr/bin/env bash
# Full rebuild of "Claude from Zero – EP 1".  Needs: python3, node + playwright (chromium), ffmpeg.
set -euo pipefail
cd "$(dirname "$0")"
pip install -q kokoro-onnx soundfile onnx scipy numpy
mkdir -p build output
python3 src/tts_align.py          # 1. narration.wav + exact word timestamps (downloads Kokoro model ~350 MB once)
node src/render.js video 30 4     # 2. 1080x1920@30 frames -> build/video_noaudio.mp4 (+ build/events.json for SFX)
python3 src/mix_audio.py          # 3. music + SFX + voice with ducking -> build/mix.wav
ffmpeg -y -loglevel error -i build/video_noaudio.mp4 -i build/mix.wav \
  -af "loudnorm=I=-14:TP=-1.0:LRA=11" -c:v copy -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart -shortest output/claude-ai-beginners-ep1.mp4   # 4. mux, -14 LUFS
python3 src/make_subs.py          # 5. SRT + word-highlight ASS + word_timestamps.json
node src/render.js thumb          # 6. thumbnail
echo "done -> output/"
