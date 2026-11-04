# Max: animated AI-tips channel (2D cartoon host)

**EP01: "5 Claude tricks most people don't know"** (53.6 s, 1080×1920, English)

| Deliverable | File |
|---|---|
| Final MP4 | `output/max-ep01-claude-tricks.mp4` |
| Script, hooks, storyboard, fact check | `EP01_SCRIPT_AND_STORYBOARD.md` |
| Character reference sheet | `output/host_reference_sheet.png` |
| Character and voice specification | `CHARACTER_AND_VOICE.md` |
| Word-level subtitles | `output/subtitles.srt`, `output/subtitles_word_highlight.ass`, `output/word_timestamps.json` |
| Thumbnail | `output/thumbnail.png` |
| Title, description, hashtags | `YOUTUBE_METADATA.md` |

To rebuild, run `./build.sh` (about 15 min on 4 cores).

For a new episode:
1. Write the lines in `src/episode.py`.
2. Update the cards and beats in `src/film.html`.
3. Run `./build.sh`.

Max's design and voice live in `src/rig.js` (`LOOKS.HOST`) and `src/episode.py` (`CAST`). Keep those fixed so the character stays consistent across episodes.
