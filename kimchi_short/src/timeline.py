"""Build the shot list + sound cues from the narration timings.

Every cut is anchored to a spoken word, so edits land on speech.
Output: build/timeline.json  {duration, shots:[{type,start,end}], cues:[{type,t,...}]}
"""
import json, os, random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, "build")
words = json.load(open(os.path.join(B, "words.json")))
lines = json.load(open(os.path.join(B, "lines.json")))
meta = json.load(open(os.path.join(B, "meta.json")))
DUR = meta["duration"]

L = {l["scene"]: l for l in lines}


def w(scene, text, nth=0):
    """start time of the nth word in `scene` whose display text starts with `text`."""
    c = [x for x in words if x["scene"] == scene and x["text"].lower().strip(".,").startswith(text.lower())]
    return c[nth]["start"]


def we(scene, text, nth=0):
    c = [x for x in words if x["scene"] == scene and x["text"].lower().strip(".,").startswith(text.lower())]
    return c[nth]["end"]


cuts = [
    ("apt_phone",     0.0),
    ("big40",         w("hook", "forty") - 0.08),
    ("apt_lean",      L["who"]["start"] - 0.1),
    ("name_card",     L["who_name"]["wstart"] - 0.12),
    ("laptop_chart",  L["who2"]["wstart"] - 0.1),
    ("walk_building", w("who2", "at") - 0.05),
    ("car_drive",     w("who2", "crypto") - 0.1),
    ("desk",          L["trade"]["wstart"] - 0.15),
    ("desk_close",    w("trade", "stories") - 0.05),
    ("fmd",           L["forty"]["wstart"] - 0.06),
    ("laptop_face",   L["emo1"]["wstart"] - 0.2),
    ("check_twice",   L["emo2"]["wstart"] - 0.1),
    ("notifications", L["emo3"]["wstart"] - 0.1),
    ("lobby_walk",    L["life"]["wstart"] - 0.15),
    ("car_inside",    w("life", "what") - 0.05),
    ("skyline_back",  w("life", "and") - 0.05),
    ("watch_close",   w("life", "in") - 0.05),
    ("apt_direct",    L["end1"]["wstart"] - 0.2),
    ("unverified",    L["end2"]["wstart"] - 0.08),
    ("bubblemaps",    L["end3"]["wstart"] - 0.1),
    ("volatile",      L["end4"]["wstart"] - 0.1),
    ("apt_smile",     L["end5"]["wstart"] - 0.1),
    ("end_card",      L["end5"]["wend"] + 0.25),
]
shots = []
for i, (typ, st) in enumerate(cuts):
    en = cuts[i + 1][1] if i + 1 < len(cuts) else DUR
    shots.append(dict(type=typ, start=round(max(0, st), 3), end=round(en, 3)))

cues = []
for s in shots[1:]:
    if s["type"] not in ("big40",):
        cues.append(dict(type="whoosh", t=s["start"] - 0.12))
cues.append(dict(type="impact", t=w("hook", "forty") - 0.02, big=1))
for sc in ("forty", "million", "dollars"):
    cues.append(dict(type="impact", t=L[sc]["wstart"] - 0.02, big=1))
cues.append(dict(type="riser", t=L["forty"]["wstart"] - 1.6, dur=1.6))
cues.append(dict(type="riser", t=w("hook", "forty") - 1.4, dur=1.4))
cues.append(dict(type="ping", t=L["who_name"]["wstart"] + 0.05))
cues.append(dict(type="stamp", t=w("end2", "unverified") + 0.05))
cues.append(dict(type="impact", t=w("end3", "six") - 0.02, big=0))
cues.append(dict(type="shimmer", t=shots[-1]["start"]))
# notifications in emo3: pops
nt = L["emo3"]["wstart"]
pops = [round(nt + 0.05 + i * 0.42, 3) for i in range(7) if nt + 0.05 + i * 0.42 < L["emo3"]["end"] + 0.3]
for p in pops:
    cues.append(dict(type="ping", t=p, soft=1))
# phone notification in hook
cues.append(dict(type="ping", t=0.9, soft=1))
# typing on desk / laptop shots
random.seed(7)
for typ in ("laptop_chart", "desk", "laptop_face"):
    s = next(x for x in shots if x["type"] == typ)
    t = s["start"] + 0.15
    while t < s["end"] - 0.2:
        cues.append(dict(type="key", t=round(t, 3)))
        t += random.uniform(0.07, 0.19) + (0.35 if random.random() < 0.08 else 0)
# rumour bubbles in desk_close
dc = next(x for x in shots if x["type"] == "desk_close")
for i in range(3):
    cues.append(dict(type="ping", t=round(dc["start"] + 0.3 + i * 0.55, 3), soft=1))

cues.sort(key=lambda c: c["t"])
json.dump(dict(duration=DUR, fps=30, shots=shots, cues=cues, pops=pops),
          open(os.path.join(B, "timeline.json"), "w"), indent=1)
for s in shots:
    print(f'{s["type"]:14s} {s["start"]:6.2f} -> {s["end"]:6.2f}  ({s["end"]-s["start"]:.2f}s)')
