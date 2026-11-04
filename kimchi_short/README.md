# "The $40 Million Story": animated YouTube Short

A fictionalized, animated reconstruction of the widely shared and **unverified** claim that the pseudonymous trader "Kimchi" made about $40M from one $TRUMP memecoin trade.

| Deliverable | File |
|---|---|
| Final video (1080×1920, 30 fps, H.264/AAC, 62.6 s, −14 LUFS) | `out/kimchi_40m_story_short.mp4` |
| Thumbnail / cover (1080×1920) | `out/thumbnail.png` |
| Subtitles, phrase level | `out/subtitles.srt` |
| Subtitles, word level (one cue per word) | `out/subtitles_words.srt` |
| Karaoke subtitles (`\k` word timing) | `out/subtitles_karaoke.ass` |
| Source / pipeline | `src/` |

---

## Editorial decisions (please read)

- **The narrator is not Kimchi.** Kimchi is a real, identifiable person. The brief had the character say "My name is Kimchi" and speak in first person. That would put invented words in a real person's mouth, so an **original character tells Kimchi's story in third person** ("there's a trader who goes by…"). The character is an original design. He does not copy anyone's face, voice or identity.
- **The $40M is framed as a claim from start to finish.** It has a "?" on screen, a "CLAIMED · UNVERIFIED" tag and an "UNVERIFIED" stamp. A **counter-estimate is included**: on-chain analytics firm Bubblemaps traced closer to ~$6M in profit (also reported by Protos). It is shown as an estimate.
- **Every scene is labelled.** A "DRAMATIZATION" badge stays on screen for the whole video. Lifestyle shots carry "ILLUSTRATIVE SCENE". Charts and the balance UI are labelled "ILLUSTRATIVE". Social posts are anonymous, invented reactions labelled "ILLUSTRATIVE". No real prices, entries, balances, usernames or brands appear.
- "Not financial advice" appears in the crypto-risk beat.

## Honest note on visual style

The brief asked for photoreal 3D character animation. This environment has no 3D or generative-video model, so the film is **procedural 2.5D motion graphics** drawn in code:
- a stylized character with lighting, rim light and screen glow
- lip-sync driven by phonemes
- blinks, head motion and changing expressions
- camera push-ins and whip transitions
- parallax city skylines, particles and film grain

It's a polished stylized-animation look, not a Pixar-grade 3D render. If you want true 3D, you can keep the script, voice, timing JSON, subtitles and music, and hand them to a 3D or AI-video tool.

---

## Narration script (as voiced, 62.6 s)

| # | Scene | Line |
|---|---|---|
| 1 | Hook | Imagine waking up and finding out that one trade could be worth forty million dollars. |
| 2 | Who | Online, there's a trader who goes by just one name. **Kimchi.** A pseudonymous Solana memecoin trader, at the center of one of crypto's wildest stories. |
| 3 | The trade | In January 2025, when the $TRUMP coin launched, stories started circulating that he'd made around forty million dollars from one trade. **Forty. Million. Dollars.** |
| 4 | Emotions | Just imagine seeing a number like that on your screen. You'd probably check it twice, just to make sure you weren't dreaming. People online couldn't stop talking about it. |
| 5 | Lifestyle | Suddenly, everyone wanted to know who he was, what happened, and how anyone ends up in a story like this. |
| 6 | Ending | But here's the thing. That forty million dollar claim is still unverified. On-chain analysts at Bubblemaps traced closer to six million. And crypto can be extremely unpredictable. That's the story behind the name Kimchi. |

Voice: Kokoro neural TTS (open-weight, Apache-2.0), voice `am_michael`, speed 1.08: young male, calm, conversational. One voice throughout.

## Storyboard (cuts land on spoken words)

| Time | Shot | Visual | Audio |
|---|---|---|---|
| 0.00–4.33 | `apt_phone` | Night penthouse with city through floor-to-ceiling windows. He looks down at his phone, a notification pops, he looks up at camera. Slow push-in from wide to face. | City ambience, notification ping, soft keys and pad |
| 4.33–6.05 | `big40` | Darkened room with gold light rays. **$0 → $40,000,000** counter slams in with a pulsing blue **?**, plus "ONE TRADE?" and "CLAIMED · UNVERIFIED". | Riser into impact |
| 6.05–9.43 | `apt_lean` | Medium shot. He leans back and gestures while the camera slides sideways. | Drums and 808 enter (build) |
| 9.43–10.50 | `name_card` | Letter-by-letter neon **KIMCHI** with glitch, an orange underline sweep and "pseudonymous online trader". Subtitles hidden because the title is the word. | Ping |
| 10.50–13.40 | `laptop_chart` | Laptop close-up with an illustrative candlestick chart building and hands typing. Camera drifts. | Typing |
| 13.40–14.40 | `walk_building` | Back view walking through a glowing corridor, light strips rushing past. | Whoosh |
| 14.40–16.51 | `car_drive` | Unbadged coupe at night: passing streetlight reflections, spinning wheels, headlight beam, speed lines. | Whoosh |
| 16.51–20.74 | `desk` | At his desk, lit by the screen. A **"JANUARY 2025 / $TRUMP memecoin launches"** card (historical context) drops in on the words. | Typing |
| 20.74–26.29 | `desk_close` | Push-in to his face. Anonymous "posts circulating online" cards slide in, and **$40M?** pops beside him. | Pings, riser |
| 26.29–29.17 | `fmd` | **FORTY. / MILLION. / DOLLARS.** Each word slams in time with the voice, with a camera punch, white flash and colour change (purple→blue→orange). His expression goes from serious to excited. | **Beat drop on "Forty."** Impact on every word. |
| 29.17–32.28 | `laptop_face` | POV from the laptop, face lit blue. Eyes widen, brows rise, then a smile. | Typing |
| 32.28–36.22 | `check_twice` | Floating balance card: **$40,000,000?** The cursor clicks REFRESH on "check" and on "twice" and the number blurs. A double-take head shake and a "×2" badge. | |
| 36.22–39.07 | `notifications` | He laughs and shakes his head while illustrative reaction cards stack in. | 7 pings |
| 39.07–41.97 | `lobby_walk` | Gold marble hotel lobby with receding columns and chandeliers. | Ambience |
| 41.97–43.05 | `car_inside` | Interior: steering wheel, hand with watch, city bokeh streaming, purple LED strip. | |
| 43.05–44.32 | `skyline_back` | He stands at a window overlooking the skyline. | |
| 44.32–46.01 | `watch_close` | Macro of a generic watch: sweeping second hand, rotating bezel light, glint. | |
| 46.01–47.50 | `apt_direct` | Back in the apartment, calm and direct to camera. | Music strips back |
| 47.50–50.94 | `unverified` | "$40,000,000" is struck through and a red **UNVERIFIED** stamp slams on the word, with "No public proof of the full amount". | Stamp |
| 50.94–54.97 | `bubblemaps` | ON-CHAIN CHECK: a hatched "CLAIMED $40M?" bar next to a "TRACED ~$6M (estimate)" bar that grows on "six", with a source pill. | Impact on "six" |
| 54.97–57.85 | `volatile` | A jagged red and green chart draws itself, then "CRYPTO / EXTREMELY UNPREDICTABLE" and "NOT FINANCIAL ADVICE". | |
| 57.85–60.80 | `apt_smile` | Small confident smile as the camera pulls back to wide. | |
| 60.80–62.63 | `end_card` | **THE $40 MILLION STORY** plus "Dramatization · original character · claim unverified". | Shimmer, fade |

## Subtitles: how the sync works

Word timestamps are **not estimated**. The Kokoro ONNX graph is patched so its duration predictor (`/encoder/Clip_output_0`, frames of 600 samples at 24 kHz) is exposed as an extra output. Every word's start and end therefore comes from the same model pass that produced the audio. Each word is phonemized separately so phoneme tokens map exactly to words.

On screen:
- Upcoming words show at 55 % opacity. Spoken words are white.
- The **active word** pops (scale 1.14) on an electric-blue pill.
- Keywords stay **yellow** and glow when spoken: FORTY, MILLION, DOLLARS, ONE TRADE, CRYPTO, KIMCHI, $TRUMP, UNVERIFIED, SIX MILLION, BUBBLEMAPS, UNPREDICTABLE.

Subtitles sit around y≈1330 px, clear of the Shorts title area at the bottom and the button rail on the right.

The same phoneme timings drive the **lip-sync**. Each phoneme maps to a mouth shape:
- open vowels → wide open
- m/b/p → closed
- f/v → nearly closed
- rounded sounds → pursed

## Music & sound

All audio is **synthesized from scratch in `src/audio.py`**, with no samples and no third-party recordings, so it's fully original and licence-free.
- **Music:** melodic hip-hop at 82 BPM in C minor (Cm9–Abmaj7–Ebmaj7–Bb6). It has Rhodes-style keys, a warm detuned pad, an 808 bass, half-time claps, hats with rolls and an echoing pluck lead.
  - The tempo is solved so a bar downbeat lands exactly on **"Forty."**: quiet intro, build from scene 2, full drop at the reveal, strip-back for the ending.
- **SFX:** whooshes on cuts, sub impacts, risers, notification pings, keyboard clicks, a stamp, an end shimmer and city ambience.
- **Mix:** the music is sidechain-ducked under the voice, so it sits about 12 dB below the narration while he speaks. The final mix is loudness-normalized to −14 LUFS, −1 dBTP.

---

## YouTube metadata

**Title:** He Made $40 Million on ONE Trade? 🤯 The Kimchi Story

Alternatives:
- "The $40M Memecoin Trade Nobody Can Verify"
- "Who Is Kimchi? The $40 Million $TRUMP Coin Story"

**Description:**
> Did one trader really make $40 million from a single $TRUMP memecoin trade? 🤯
> Here's the internet-famous story of "Kimchi", the pseudonymous Solana trader everyone was talking about, and what the on-chain data actually suggests.
>
> ⚠️ This is an animated dramatization with an original character. It is not the real Kimchi and not real footage. The $40M figure is a widely circulated but unverified claim. Bubblemaps' on-chain analysis traced roughly $6M. Crypto is extremely volatile. Nothing here is financial advice.
>
> Follow for more crypto stories, told honestly.

**Hashtags:** #Shorts #crypto #memecoin #kimchi #trumpcoin #solana #cryptotrading #cryptonews #onchain #bitcoin #trading #storytime

## Sources used for fact-checking
- Protos: "Pump.fun's Kimchi partnership has turned into chaos" (verifiable profits ≈ $6M): https://protos.com/pump-funs-kimchi-partnership-has-turned-into-chaos/
- Tapbit Learn: "Who Is Kimchi Trader? …Allegedly Made $40M on TRUMP": https://www.tapbit.com/en/learn/article/who-is-kimchi-trader-trump-40-million-claim-20261009
- AMBCrypto: Pump.fun trader $40M claim: https://ambcrypto.com/pump-fun-trader-nets-40m-profit-despite-solana-memecoin-slump-how
- Bitcoin.com News: Kimchi X account / Project Kimchi token crash: https://news.bitcoin.com/market-updates/kimchi-x-account-hacked-project-kimchi-token-crash/

---

## Rebuild from source

Requirements: Python 3.10+, Node 18+, ffmpeg, Playwright with Chromium.

```bash
pip install kokoro-onnx soundfile scipy onnx
mkdir -p models && cd models
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
cd ..
python3 src/tts.py          # voice.wav + word/phoneme timings (patches model on first run)
python3 src/timeline.py     # shot list + SFX cues anchored to words
python3 src/audio.py        # original music, SFX, ducked mix
node src/render.js preview 1 5 28.8   # optional: spot-check frames → build/preview_*.jpg
node src/render.js full 4   # render 1879 frames with 4 parallel Chromium workers (~3 min)
python3 src/finalize.py     # mux + loudnorm + SRT/ASS export
node src/render.js thumb    # out/thumbnail.png
```

To edit the story, change `src/script.py` and rerun the chain. Every cut, subtitle, lip movement, music drop and SFX re-times automatically.
