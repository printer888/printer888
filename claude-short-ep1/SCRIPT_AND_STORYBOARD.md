# Claude from Zero · EP 1 — Script & Storyboard

**Runtime:** 58.1 s · **Format:** 1080×1920, 30 fps, H.264 + AAC (−14 LUFS)
**Voice:** Kokoro‑82M neural TTS, voice `af_heart`, 1.06× speed
**Timestamps below are the actual times from the rendered video.**

## Full narration script

> You're probably using AI completely wrong. Let me show you Claude.
> Claude is an AI assistant made by Anthropic. It can write, explain, analyze your files, and help you think through hard problems.
> Step one: go to claude.ai. Click Continue with Google, or enter your email and open the login link. The free plan is enough to start.
> Step two: in the chat box, type your first prompt. Be specific. Tell Claude who you are, what you need, and the format you want.
> Step three: click the plus button to upload a PDF or a photo of your notes. Then ask: summarize this into five key points and three quiz questions. Seconds later, you've got a study guide.
> The same trick works for business emails, plans, and everyday productivity.
> Pro tip: if the answer isn't perfect, just reply and ask Claude to improve it.
> Follow for more AI tools that actually make your life easier.

(155 words.)

## Scene‑by‑scene storyboard

| # | Time | Beat (brief) | Narration | Visuals & motion | Sound |
|---|------|--------------|-----------|------------------|-------|
| 1 | 0.0–2.9 | **HOOK** | "You're probably using AI completely wrong." | Fast 1.9× → 1× zoom onto a chat bar where a lazy prompt "write essay" types out. A generic grey answer flickers below. On "wrong", a red ✗ stamp lands, **WRONG** slams in at 3× scale with a gradient fill, and the camera shakes. | Sparse kick, typing, impact on "wrong" |
| 2 | 2.9–4.5 | **REVEAL** | "Let me show you Claude." | The hook UI flies up and out. On "show", the orange Claude spark spins up with an elastic scale. On "Claude", rays burst out and the letters C‑L‑A‑U‑D‑E drop in one by one; UDE is in Claude orange. | Riser → boom + sparkle, full beat starts |
| 3 | 4.5–13.0 | **INTRO** | "Claude is an AI assistant made by Anthropic. It can write, explain, analyze your files, and help you think through hard problems." | Zoom‑blur transition. The spark rotates while the serif wordmark "Claude" tracks in. The pills "AI assistant" and "by Anthropic" pop on their words. Four capability cards (Write / Explain / Analyze files / Think it through) bounce in, each on its spoken word. The active card glows in its own colour, and every card bobs. | Whoosh, pop per item |
| 4 | 13.0–15.4 | **STEP 1 – find it** | "Step one: go to claude.ai." | A STEP 1 badge slides in. A browser window rises with an empty address bar, "claude.ai" types in, the cursor clicks, and a loading bar sweeps across. | Typing, click |
| 5 | 15.4–19.8 | **Sign up** | "Click Continue with Google, or enter your email and open the login link." | The login page fades in: Continue with Google, OR, Enter your email, Continue with email. The camera pushes in. A glowing ring and bouncing arrow move from **Continue with Google** to the email field to **Continue with email**. The cursor clicks, "you@example.com" types out, and a "Check your inbox" toast slides up on "login link". | Clicks, typing, ding |
| 6 | 19.8–22.2 | **Free** | "The free plan is enough to start." | The browser blurs and dims, and a **FREE PLAN / START FOR $0** stamp crashes in with a rotation. | Stamp impact + sparkle |
| 7 | 22.2–25.5 | **STEP 2 – first prompt** | "Step two: in the chat box, type your first prompt." | Whoosh into a recreation of the Claude chat UI in dark mode: sidebar (New chat · Chats · Projects · Recents), greeting, and chat box with + and send. An orange ring and arrow mark the chat box, and the camera zooms to it. The prompt types out live. | Click, typing |
| 8 | 25.5–30.3 | **Prompt formula** | "Be specific. Tell Claude who you are, what you need, and the format you want." | Each part of the prompt is highlighted on its spoken word: **WHO** (blue) "I'm a nursing student." · **WHAT** (purple) "Explain how the heart works" · **FORMAT** (orange) "in 5 simple bullet points." Then the cursor clicks send, which pulses. | 3 pops, send swoosh |
| 9 | 30.3–35.2 | **STEP 3 – upload** | "Step three: click the plus button to upload a PDF or a photo of your notes." | A new chat opens. The **+** button is ringed and clicked, and a menu pops up with *Add files or photos* and *Add from Google Drive*. The cursor picks *Add files or photos*. The **Biology_notes.pdf** chip drops in on "PDF" and **notes_photo.jpg** on "photo". | Clicks, pops |
| 10 | 35.2–40.1 | **Ask** | "Then ask: summarize this into five key points and three quiz questions." | The prompt types into the box synced to speech, then gets sent. | Typing, send |
| 11 | 40.1–42.5 | **Result** | "Seconds later, you've got a study guide." | The camera pulls back. The user message moves to the top and Claude's answer streams in line by line: 5 key points, then 3 quiz questions. A **✓ STUDY GUIDE READY** badge pops in. | Soft stream ticks, ding |
| 12 | 42.5–47.5 | **Use cases** | "The same trick works for business emails, plans, and everyday productivity." | The title "SAME TRICK." tracks in. The Studying, Business emails, Plans and Everyday productivity cards fly in from the sides on their words, glowing while active. | Pops |
| 13 | 47.5–52.7 | **Pro tip** | "Pro tip: if the answer isn't perfect, just reply and ask Claude to improve it." | A PRO TIP badge wobbles in. The "Answer v1" card gets a red **NOT QUITE** tag on "perfect". On "reply", a user bubble types "Make it shorter and add an example." A loop icon spins, then the green "Answer v2 · Improved" card rises on "improve". | Buzz, typing, send, ding |
| 14 | 52.7–58.1 | **CTA** | "Follow for more AI tools that actually make your life easier." | The spark spins and **FOLLOW** slams in with a pulsing glow. "for more AI tools that make life easier" slides up, then a "CLAUDE FROM ZERO · EP 1 ✓" pill. Music fades out. | Boom, sparkle |

**Always on screen:**
* An animated canvas background: drifting blue, purple and orange light blobs, a perspective grid, rising particles and a vignette.
* The "CLAUDE FROM ZERO · EP 1" series tag.
* Word‑by‑word captions at y≈1235–1485, inside the Shorts safe area (clear of the top bar, the right‑side buttons and the bottom title area).

## Word‑level caption system

* **Timing source:** I patched Kokoro's ONNX graph to also output its duration predictor (`/encoder/Clip_output_0`), which gives frames per phoneme. 1 frame is 600 samples at 24 kHz, or 25 ms. I mapped phonemes back to words, so every word's start and end is the time the synthesiser actually spoke it. This is better than forced alignment because no estimation is involved. The timestamps are in `output/word_timestamps.json`.
* **Behaviour:**
  * Each word pops in (scale 0.55 → 1, slight rise) exactly at its start time.
  * The word being spoken is coloured and scaled to 110 % with a glow. It returns to white when the next word starts.
* **Colours:**
  * Electric blue is the default highlight.
  * Purple is for *Claude / AI / Anthropic / claude.ai*.
  * Orange is for *step numbers, free, pro tip, follow, wrong*.
* **Line breaks:** a new caption block starts after 3 words, at punctuation, at a pause longer than 350 ms, or past 17 characters.

## Fact check (official Anthropic sources, Nov 2026)

* Claude is made by Anthropic and is used at **claude.ai**. There are web, desktop and mobile apps. — claude.com
* Sign‑up: "Continue with Google" or enter an email; email sign‑in sends a login link. — support.claude.com, *Log in to your Claude account*
* There is a **Free plan**, with usage limits. — claude.com/pricing, support.claude.com, *What is the Pro plan?*
* Uploads: click the **"+" button** at the lower left of the chat box (or drag and drop). PDFs, documents and images are supported, and Google Drive files can be added from the same "+" menu. — support.claude.com, *Upload files to Claude*, *Use Google Workspace connectors*
* The interface is an approximation, drawn with real element names: New chat, Chats, Projects, the chat box with "+" and send, and the "How can I help you today?" placeholder. Claude's UI changes over time, and the greeting "Good evening, Alex" stands in for the personalised greeting.
* The spark is a stylised orange starburst in the spirit of the Claude mark. It is not the official logo file. If the channel has permission to use Anthropic brand assets, swap it in `spark()` in `src/index.html`.
