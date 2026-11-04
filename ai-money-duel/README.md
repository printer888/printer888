# Russian vs Italian — Who Makes More Money With AI? (animated YouTube Short)

A 59.6‑second, 1080×1920 character‑animated comedy short. Dmitri uses Claude to analyse a **simulated** trading challenge, Marco trusts his gut, and Giulia changes seats. It is dialogue only, with no narrator.

| Deliverable | File |
|---|---|
| Final MP4 (H.264/AAC, 30 fps, −14 LUFS) | `output/russian-vs-italian-ai-money.mp4` |
| Script, cast sheet, shot‑by‑shot storyboard | `STORYBOARD_AND_SCRIPT.md` |
| Subtitles: SRT (speaker‑labelled), ASS (word highlight), word timings JSON | `output/` |
| Thumbnail | `output/thumbnail.png` |
| Title, description, hashtags | `YOUTUBE_METADATA.md` |

## Pipeline
```
src/dialogue.py   cast (voice, speed, accent) and lines with acting pauses
src/voices.py     Kokoro-82M TTS with phoneme-level accent rewriting. The ONNX graph is patched to output phoneme durations,
                  giving exact word and phoneme timing for lip-sync and captions
src/rig.js        reusable 2.5D SVG character rig: visemes, blinks, gaze, brows, expressions, IK arms, stand, walk, props
src/film.html     world (London skyline, rooftop, guests, waiter), director (acting per character), virtual camera
                  with parallax and depth of field, Claude/trading inserts, captions, CTA. Every frame is a pure function of t
src/render.js     Playwright renders the frames in parallel and pipes them to ffmpeg; also exports the SFX cue list
src/mix_audio.py  original synthesised score, restaurant ambience, Foley/SFX on cues, panned dialogue, ducking
src/make_subs.py  subtitles
```
To rebuild, run `./build.sh` (about 25 min on 4 cores). Preview single frames with `node src/render.js stills 12.5 40`.

To swap in human voice actors, replace `build/dialogue.wav` and regenerate `build/timeline.json` (word and phoneme times) with a forced aligner such as Montreal Forced Aligner. The lip‑sync and captions follow the new timing automatically.
