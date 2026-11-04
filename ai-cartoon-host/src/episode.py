"""EP01 — 5 Claude tricks most people don't know.  Host: Max (one fixed voice)."""
TITLE = "5 Claude tricks most people don't know"
CAST = {"MAX": {"name": "Max", "voice": "am_puck", "speed": 1.05, "accent": "none"}}
# Hook candidates (picked #2):
# 1 "Claude can do way more than answer questions."  2 "Most people use Claude like a search bar. That's a waste."
# 3 "Stop starting a new chat every time."  4 "Five Claude tricks I wish I knew sooner."  5 "Your prompts aren't the problem. Your workflow is."
LINES = [
    {"id": "hook", "who": "MAX", "pre": .3, "text": "Most people use Claude like a search bar. That's a waste."},
    {"id": "intro", "who": "MAX", "pre": .25, "text": "Here are five tricks that make it way more useful."},
    {"id": "t1", "who": "MAX", "pre": .35, "text": "Trick one: hit the plus button and upload your files."},
    {"id": "t1b", "who": "MAX", "pre": .15, "text": "PDFs, photos, documents. Claude reads them for you."},
    {"id": "t2", "who": "MAX", "pre": .35, "text": "Trick two: create a Project."},
    {"id": "t2b", "who": "MAX", "pre": .15, "text": "Add your notes and instructions once, and every chat inside it can use them. Even the free plan gets five."},
    {"id": "t3", "who": "MAX", "pre": .35, "text": "Trick three: ask for an artifact."},
    {"id": "t3b", "who": "MAX", "pre": .15, "text": "Say, build me a study planner, and Claude makes a real interactive tool right next to the chat."},
    {"id": "t4", "who": "MAX", "pre": .35, "text": "Trick four: don't like the answer? Edit your message and try again, instead of starting a brand new chat."},
    {"id": "t5", "who": "MAX", "pre": .35, "text": "Trick five, my favourite: end your prompt with, ask me three questions before you start."},
    {"id": "t5b", "who": "MAX", "pre": .15, "text": "The answers get so much better."},
    {"id": "end1", "who": "MAX", "pre": .35, "text": "Which trick are you trying first? Tell me in the comments."},
    {"id": "end2", "who": "MAX", "pre": .2, "text": "And if you want to learn more, follow for more."},
]
TAIL = 1.8
