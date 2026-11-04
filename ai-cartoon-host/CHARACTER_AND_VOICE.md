# Channel identity: Max (recurring host)
See `output/host_reference_sheet.png` for the reference sheet.

| | |
|---|---|
| Name | Max |
| Personality | Friendly, curious, a little cheeky. Talks to the viewer like a smart friend. |
| Silhouette keys | Tall dark-brown swept quiff · round black glasses · orange hoodie with white drawstrings · electric-blue headphones around the neck |
| Proportions | Large head (1.38× rig head scale), large eyes (1.22×), standard torso. These are fixed in `LOOKS.HOST` in `src/rig.js`. |
| Default set | Navy night room: city window with moon and twinkling stars, bookshelf, purple **MAX** neon, desk lamp, orange "AI" mug, plant, laptop. |
| Voice | Kokoro‑82M, voice `am_puck`, speed **1.05**, en‑US, no accent processing. **Never change these values between episodes.** |
| Captions | Inter Black, white with a black outline. The word being spoken turns **yellow #FFD43B** and pops to 108–112 %. |
| Palette | Navy #141B3A · electric blue #2E9BFF · purple #A35CFF · orange #FF7A1A · yellow #FFD43B · white |

The rig (`src/rig.js`) drives Max for every episode: mouth shapes from the voice's phoneme timing, automatic blinks, gaze, brows, expression keyframes, IK arm poses (type, gesture, point up, shrug, wave, chin, open arms) and head nods on stressed words. To make a new episode, edit `src/episode.py` (lines), then the card and beat section of `src/film.html`, and run `./build.sh`.
