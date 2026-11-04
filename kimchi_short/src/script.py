"""Narration script — single source of truth for voice, subtitles and timeline.

Word syntax:
  plain word              -> displayed and spoken as written
  display=spoken_words    -> displayed as `display`, spoken as `spoken words` (underscores = spaces)
  *word                   -> keyword, highlighted yellow in subtitles

Each line: (scene_id, text, pause_after_seconds)
"""

LINES = [
    # SCENE 1 — HOOK
    ("hook",   "Imagine waking up and finding out that *one *trade could be worth *forty *million *dollars.", 0.45),
    # SCENE 2 — WHO IS HE
    ("who",    "Online, there's a trader who goes by just one name.", 0.20),
    ("who_name", "*Kimchi.", 0.40),
    ("who2",   "A pseudonymous Solana meme-coin=memecoin trader, at the center of one of *crypto's wildest stories.", 0.45),
    # SCENE 3 — THE BIG TRADE
    ("trade",  "In January *2025=twenty_twenty-five, when the *$TRUMP=Trump coin launched, stories started circulating that he'd made around *forty *million *dollars from *one *trade.", 0.50),
    ("forty",  "*Forty.", 0.30),
    ("million", "*Million.", 0.30),
    ("dollars", "*Dollars.", 0.55),
    # SCENE 4 — THE EMOTIONS
    ("emo1",   "Just imagine seeing a number like that on your screen.", 0.15),
    ("emo2",   "You'd probably check it twice, just to make sure you weren't dreaming.", 0.35),
    ("emo3",   "People online couldn't stop talking about it.", 0.45),
    # SCENE 5 — THE LIFESTYLE
    ("life",   "Suddenly, everyone wanted to know who he was, what happened, and how anyone ends up in a story like this.", 0.55),
    # SCENE 6 — THE ENDING
    ("end1",   "But here's the thing.", 0.30),
    ("end2",   "That *forty *million dollar claim is still *unverified.", 0.25),
    ("end3",   "On-chain analysts at *Bubblemaps=Bubble_maps traced closer to *six *million.", 0.30),
    ("end4",   "And *crypto can be extremely *unpredictable.", 0.45),
    ("end5",   "That's the story behind the name *Kimchi.", 0.0),
]

VOICE = "am_michael"
SPEED = 1.08
LEAD_IN = 0.35   # seconds of silence before first word
TAIL = 2.6       # seconds after last word (end card)
