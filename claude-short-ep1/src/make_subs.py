"""SRT (phrase level) + ASS (word-by-word highlight, karaoke-style) from build/words.json."""
import json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "build", "words.json"))); W = d["words"]
OUT = os.path.join(ROOT, "output")
# same chunking rule as the renderer
chunks, cur = [], None
for i, w in enumerate(W):
    pv = W[i - 1] if i else None
    if (not cur or len(cur["w"]) >= 3 or re.search(r"[.,:!?]$", pv["w"]) or w["s"] - pv["e"] > 0.35
            or cur["len"] + len(w["w"]) > 17 or w["si"] != pv["si"]):
        cur = {"w": [], "len": 0}; chunks.append(cur)
    cur["w"].append(w); cur["len"] += len(w["w"]) + 1
for i, c in enumerate(chunks):
    c["s"] = c["w"][0]["s"] - 0.04
for i, c in enumerate(chunks):
    nx = chunks[i + 1] if i + 1 < len(chunks) else None; last = c["w"][-1]["e"]
    c["e"] = min(nx["s"], last + 0.7) if nx else last + 1.0
    if nx and nx["s"] - last > 0.7: c["e"] = last + 0.45
clean = lambda s: re.sub(r"[.,:]$", "", s)
def srt_t(t): h, r = divmod(max(t, 0), 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"
def ass_t(t): h, r = divmod(max(t, 0), 3600); m, s = divmod(r, 60); return f"{int(h)}:{int(m):02d}:{s:05.2f}"
# SRT: one cue per sentence-chunk (readable captions for YouTube upload)
with open(os.path.join(OUT, "subtitles.srt"), "w") as f:
    for i, c in enumerate(chunks, 1):
        f.write(f"{i}\n{srt_t(c['s'])} --> {srt_t(c['e'])}\n{' '.join(clean(w['w']) for w in c['w'])}\n\n")
# ASS: one event per word-state, active word coloured + scaled
PURPLE = {"claude", "ai", "anthropic", "claude.ai"}; ORANGE = {"one", "two", "three", "five", "free", "pro", "tip", "step", "follow", "wrong"}
def col(w):
    k = re.sub(r"[^a-z0-9.']", "", w.lower()).rstrip(".")
    return "&H00FF8BC0&" if k in PURPLE else "&H003D9AFF&" if k in ORANGE else "&H00FFB53F&"  # BGR
hdr = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter Black,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,4,5,90,150,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
with open(os.path.join(OUT, "subtitles_word_highlight.ass"), "w") as f:
    f.write(hdr)
    for c in chunks:
        ws = c["w"]
        for i, w in enumerate(ws):
            a = w["s"] - 0.04; b = ws[i + 1]["s"] - 0.04 if i + 1 < len(ws) else c["e"]
            parts = []
            for j, x in enumerate(ws):
                t = clean(x["w"]).upper()
                if j < i: parts.append(t)
                elif j == i: parts.append(r"{\c" + col(x["w"]) + r"\fscx112\fscy112}" + t + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                else: parts.append(r"{\alpha&HFF&}" + t + r"{\alpha&H00&}")
            f.write(f"Dialogue: 0,{ass_t(a)},{ass_t(b)},Cap,,0,0,0,,{{\\pos(500,1360)}}{' '.join(parts)}\n")
json.dump(W, open(os.path.join(OUT, "word_timestamps.json"), "w"), indent=1)
print(len(chunks), "caption chunks,", len(W), "words")
