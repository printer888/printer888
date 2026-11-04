# Claude from Zero · EP 1 — "How to start using Claude AI" (YouTube Short)

A 58‑second, 1080×1920 YouTube Short teaching complete beginners how to start using Claude. Every step below was produced by code in this folder: the AI voice‑over, the word‑synced captions, the motion graphics, the music and SFX, and the final render.

| Deliverable | File |
|---|---|
| Final video (H.264/AAC, 30 fps, −14 LUFS) | `output/claude-ai-beginners-ep1.mp4` |
| Narration script + scene‑by‑scene storyboard + fact check | `SCRIPT_AND_STORYBOARD.md` |
| Subtitles, SRT | `output/subtitles.srt` |
| Subtitles, ASS with word‑by‑word highlight | `output/subtitles_word_highlight.ass` |
| Word‑level timestamps | `output/word_timestamps.json` |
| Thumbnail / cover | `output/thumbnail.png` |
| Title, description, hashtags | `YOUTUBE_METADATA.md` |

## How it is made

```
src/narration.py    script, one entry per sentence
src/tts_align.py    Kokoro-82M TTS. The ONNX graph is patched to expose phoneme durations, giving exact word timestamps
src/index.html      motion-graphics engine. Every element is a pure function of time t (no realtime CSS animation),
                    so each frame is deterministic and synced to the word timestamps
src/render.js       Playwright/Chromium renders each frame and pipes PNGs into ffmpeg (4 parallel workers);
                    it also exports the SFX cue list
src/mix_audio.py    original synthesised music (116 BPM, Am–F–C–G) and SFX (whoosh, clicks, typing, pops, impacts, dings)
                    placed on the cue list; music is side-chain ducked about 9 dB under the voice
src/make_subs.py    SRT, word-highlight ASS and JSON
build.sh            runs the whole pipeline
```

## Rebuild

Requirements: Python 3.10+, Node 18+, Playwright with Chromium (`npm i -g playwright && npx playwright install chromium`), and ffmpeg.

```bash
./build.sh            # about 20 min on 4 CPU cores; downloads the Kokoro model (about 350 MB) once
```

To change the script, edit `src/narration.py` and rerun. The visuals are keyed to *spoken words* (for example `W('login','google')`), so the animations follow the new timing automatically. To preview single frames: `node src/render.js stills 3.5 17 41`.

To change the voice, set `VOICE` in `src/tts_align.py` (for example `am_michael` or `bm_george`). To use a human voice‑over instead, replace `build/narration.wav` and regenerate `build/words.json` with any forced aligner (e.g. WhisperX), keeping the same JSON shape.
