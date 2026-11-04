"""SRT (speaker-labelled) + ASS (word-by-word highlight in speaker colours) + word JSON."""
import json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "build", "timeline.json"))); W = d["words"]; OUT = os.path.join(ROOT, "output")
NAME = {"RU": "DMITRI", "IT": "MARCO", "GF": "GIULIA"}
chunks, cur = [], None
for i, w in enumerate(W):
    pv = W[i - 1] if i else None
    if not cur or len(cur["w"]) >= 3 or re.search(r"[.,:!?…]$", pv["w"]) or w["s"] - pv["e"] > .35 or cur["len"] + len(w["w"]) > 16 or w["li"] != pv["li"]:
        cur = {"w": [], "len": 0}; chunks.append(cur)
    cur["w"].append(w); cur["len"] += len(w["w"]) + 1
for c in chunks: c["s"] = c["w"][0]["s"] - .04
for i, c in enumerate(chunks):
    nx = chunks[i + 1] if i + 1 < len(chunks) else None; last = c["w"][-1]["e"]
    c["e"] = min(nx["s"], last + .6) if nx else last + .8
clean = lambda s: re.sub(r"[.,:…]+$", "", s)
def srt_t(t): h, r = divmod(max(t, 0), 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"
def ass_t(t): h, r = divmod(max(t, 0), 3600); m, s = divmod(r, 60); return f"{int(h)}:{int(m):02d}:{s:05.2f}"
with open(os.path.join(OUT, "subtitles.srt"), "w") as f:
    for i, l in enumerate(d["lines"], 1):
        nxt = d["lines"][i]["s"] - .1 if i < len(d["lines"]) else l["e"] + .8
        f.write(f"{i}\n{srt_t(l['s'] - .05)} --> {srt_t(min(l['e'] + .3, nxt))}\n{NAME[l['who']]}: {l['text']}\n\n")
COL = {"RU": "&H00FF9B2E&", "IT": "&H001F8AFF&", "GF": "&H00A25FFF&"}; GREEN = "&H008AE82E&"; PURPLE = "&H00FF6BB2&"
NUM = {"two", "thousand", "eight", "hundred", "and", "fifty"}
hdr = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter Black,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,4,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
cta_li = [l["i"] for l in d["lines"] if l["id"] == "ru6"][0]; num_li = [l["i"] for l in d["lines"] if l["id"] == "it5"][0]
with open(os.path.join(OUT, "subtitles_word_highlight.ass"), "w") as f:
    f.write(hdr)
    for c in chunks:
        ws = c["w"]
        for i, w in enumerate(ws):
            a = w["s"] - .04; b = ws[i + 1]["s"] - .04 if i + 1 < len(ws) else c["e"]; parts = []
            for j, x in enumerate(ws):
                t = clean(x["w"]).upper(); col = COL[x["who"]]
                if x["li"] == num_li and re.sub(r"\W", "", x["w"].lower()) in NUM: col = GREEN
                if x["li"] == cta_li: col = PURPLE
                if j < i: parts.append(t)
                elif j == i: parts.append(r"{\c" + col + r"\fscx108\fscy108}" + t + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                else: parts.append(r"{\alpha&HFF&}" + t + r"{\alpha&H00&}")
            f.write(f"Dialogue: 0,{ass_t(a)},{ass_t(b)},Cap,{NAME[w['who']]},0,0,0,,{{\\pos(540,1545)}}{' '.join(parts)}\n")
json.dump([{k: w[k] for k in ("w", "s", "e", "who")} for w in W], open(os.path.join(OUT, "word_timestamps.json"), "w"), indent=1)
print(len(chunks), "chunks", len(W), "words")
