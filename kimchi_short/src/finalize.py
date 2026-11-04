"""Mux final MP4 (loudness-normalised to -14 LUFS for Shorts) + export subtitle files."""
import json, os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B, O = os.path.join(ROOT, "build"), os.path.join(ROOT, "out")
os.makedirs(O, exist_ok=True)
words = json.load(open(os.path.join(B, "words.json")))


def ts_srt(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ts_ass(t):
    cs = int(round(t * 100)); h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# same paging rule as the renderer
pages, by_line = [], {}
for w in words:
    by_line.setdefault(w["line"], []).append(w)
for ln in sorted(by_line):
    ws, cur, chars = by_line[ln], [], 0
    for i, w in enumerate(ws):
        cur.append(w); chars += len(w["text"]) + 1
        punct = w["text"][-1] in ".,!?"
        brk = punct or chars > 17 or len(cur) >= 4
        nxt = ws[i + 1] if i + 1 < len(ws) else None
        if (brk and not (nxt and len(cur) == 1 and not punct)) or not nxt:
            pages.append(cur); cur, chars = [], 0

# SRT: one cue per page (phrase level)
with open(os.path.join(O, "subtitles.srt"), "w") as f:
    for i, pg in enumerate(pages):
        st = pg[0]["start"]; en = pg[-1]["end"] + 0.15
        if i + 1 < len(pages):
            en = min(en, pages[i + 1][0]["start"] - 0.01)
        f.write(f"{i+1}\n{ts_srt(st)} --> {ts_srt(en)}\n{' '.join(w['text'] for w in pg)}\n\n")

# word-level SRT (one cue per word, exact timestamps)
with open(os.path.join(O, "subtitles_words.srt"), "w") as f:
    for i, w in enumerate(words):
        f.write(f"{i+1}\n{ts_srt(w['start'])} --> {ts_srt(w['end'])}\n{w['text']}\n\n")

# ASS with \k karaoke tags (word-level highlight in any ASS-capable player/editor)
hdr = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Inter Display Black,78,&H004DE1FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,7,2,2,90,90,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
with open(os.path.join(O, "subtitles_karaoke.ass"), "w") as f:
    f.write(hdr)
    for i, pg in enumerate(pages):
        st = pg[0]["start"]; en = pg[-1]["end"] + 0.15
        if i + 1 < len(pages):
            en = min(en, pages[i + 1][0]["start"] - 0.01)
        parts, cur = [], st
        for w in pg:
            gap = max(0, w["start"] - cur)
            if gap > 0.01:
                parts.append(f"{{\\k{int(round(gap*100))}}}")
            dur = int(round((w["end"] - w["start"]) * 100))
            parts.append(f"{{\\k{dur}}}{w['text'].upper()} ")
            cur = w["end"]
        f.write(f"Dialogue: 0,{ts_ass(st)},{ts_ass(en)},Karaoke,,0,0,0,,{''.join(parts).strip()}\n")

# final mux, 2-pass-ish loudnorm to -14 LUFS / -1 dBTP
out = os.path.join(O, "kimchi_40m_story_short.mp4")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(B, "video_noaudio.mp4"), "-i", os.path.join(B, "mix.wav"),
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.0:LRA=11", "-ar", "48000",
                "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", out], check=True)
print("wrote", out, len(pages), "subtitle pages")
