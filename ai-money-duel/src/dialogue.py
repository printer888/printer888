"""Dialogue script. pre = silence before the line (s), used for acting beats."""
CAST = {
    "RU": {"name": "Dmitri", "voice": "am_onyx", "speed": 1.0, "accent": "ru"},
    "IT": {"name": "Marco", "voice": "im_nicola", "speed": 1.04, "accent": "it"},
    "GF": {"name": "Giulia", "voice": "af_bella", "speed": 1.0, "accent": "light"},
}
LINES = [
    {"id": "it1", "who": "IT", "pre": 2.9, "text": "Still trying to make money with AI?"},
    {"id": "ru1", "who": "RU", "pre": 0.35, "text": "Actually, it's making my work a lot easier."},
    {"id": "it2", "who": "IT", "pre": 0.3, "text": "Let's see who's making more money."},
    {"id": "it3", "who": "IT", "pre": 1.3, "text": "I trust my instincts. That's how real businessmen work."},
    {"id": "ru2", "who": "RU", "pre": 1.1, "text": "I prefer having data behind my decisions."},
    {"id": "ru3", "who": "RU", "pre": 0.45, "text": "Let AI do the thinking. I'll make the decisions."},
    {"id": "it4", "who": "IT", "pre": 3.7, "text": "What exactly is that thing doing?"},
    {"id": "ru4", "who": "RU", "pre": 0.3, "text": "Helping me understand the market before I make a decision."},
    {"id": "it5", "who": "IT", "pre": 3.0, "text": "Wait... two thousand eight hundred and fifty?"},
    {"id": "gf1", "who": "GF", "pre": 0.35, "text": "How did you manage that?"},
    {"id": "ru5", "who": "RU", "pre": 0.3, "text": "Preparation. Better analysis. And AI."},
    {"id": "gf2", "who": "GF", "pre": 2.6, "text": "I think I chose the wrong businessman."},
    {"id": "it6", "who": "IT", "pre": 0.3, "text": "Seriously?!"},
    {"id": "ru6", "who": "RU", "pre": 1.0, "text": "If you want the same, follow for more."},
]
TAIL = 2.4
