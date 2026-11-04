"""Narration script, one entry per sentence.  The `id` names the scene beat.
{spoken words|DISPLAY} renders several spoken words as one subtitle token.
`gap` = silence after the sentence (s)."""
SENTENCES = [
    {"id": "hook",    "text": "You're probably using AI completely wrong.", "gap": 0.12},
    {"id": "hook2",   "text": "Let me show you Claude.", "gap": 0.3},
    {"id": "intro",   "text": "Claude is an AI assistant made by Anthropic."},
    {"id": "intro2",  "text": "It can write, explain, analyze your files, and help you think through hard problems.", "gap": 0.3},
    {"id": "step1",   "text": "Step one: go to {claude dot ai|claude.ai}.", "gap": 0.15},
    {"id": "login",   "text": "Click Continue with Google, or enter your email and open the login link."},
    {"id": "free",    "text": "The free plan is enough to start.", "gap": 0.3},
    {"id": "step2",   "text": "Step two: in the chat box, type your first prompt."},
    {"id": "specific","text": "Be specific. Tell Claude who you are, what you need, and the format you want.", "gap": 0.3},
    {"id": "step3",   "text": "Step three: click the plus button to upload a PDF or a photo of your notes."},
    {"id": "ask",     "text": "Then ask: summarize this into five key points and three quiz questions.", "gap": 0.15},
    {"id": "result",  "text": "Seconds later, you've got a study guide.", "gap": 0.25},
    {"id": "uses",    "text": "The same trick works for business emails, plans, and everyday productivity.", "gap": 0.3},
    {"id": "tip",     "text": "Pro tip: if the answer isn't perfect, just reply and ask Claude to improve it.", "gap": 0.3},
    {"id": "cta",     "text": "Follow for more AI tools that actually make your life easier."},
]
