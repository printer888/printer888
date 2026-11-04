"""Soundtrack: original synthesised score + restaurant ambience + Foley/SFX placed
on the renderer's cue list (build/events.json) + dialogue (panned per character),
with side-chain ducking so music/ambience always sit under the voices.
Output: build/mix.wav (48 kHz stereo)."""
import json, os
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); B = os.path.join(ROOT, "build")
SR = 48000; rng = np.random.default_rng(11)
ev = json.load(open(os.path.join(B, "events.json"))); tl = json.load(open(os.path.join(B, "timeline.json")))
DUR = ev["duration"]; N = int(DUR * SR)
lines = {l["id"]: l for l in tl["lines"]}

def lp(x, f, o=2): return sosfilt(butter(o, f, "low", fs=SR, output="sos"), x)
def hp(x, f, o=2): return sosfilt(butter(o, f, "high", fs=SR, output="sos"), x)
def bp(x, a, b, o=2): return sosfilt(butter(o, [a, b], "band", fs=SR, output="sos"), x)
def tt(n): return np.arange(n) / SR
def note(m): return 440 * 2 ** ((m - 69) / 12)
def add(buf, x, t, g=1.0, pan=0.0):
    i = int(t * SR)
    if i >= len(buf) or i + len(x) <= 0: return
    if i < 0: x = x[-i:]; i = 0
    x = x[: len(buf) - i]
    buf[i:i + len(x), 0] += x * g * np.sqrt(1 - pan) ; buf[i:i + len(x), 1] += x * g * np.sqrt(1 + pan)
def movavg(x, k):
    c = np.cumsum(np.concatenate([[0], x])); y = (c[k:] - c[:-k]) / k
    return np.pad(y, (k // 2, len(x) - len(y) - k // 2), mode="edge")

# ── dialogue, per-speaker pan ──
voice, vsr = sf.read(os.path.join(B, "dialogue.wav")); voice = resample_poly(voice, SR, vsr)[:N]; voice = np.pad(voice, (0, N - len(voice)))
dlg = np.zeros((N, 2)); PAN = {"IT": -.18, "RU": .18, "GF": 0}
for l in tl["lines"]:
    a, b = int((l["s"] - .08) * SR), int((l["e"] + .2) * SR); seg = voice[a:b]
    add(dlg, seg, a / SR, 1.0, PAN[l["who"]])
# small room: short early reflections
room = np.zeros_like(dlg)
for d, g in [(.023, .12), (.041, .08), (.067, .05)]:
    k = int(d * SR); room[k:] += dlg[:-k] * g
dlg = dlg + np.stack([lp(room[:, 0], 4000), lp(room[:, 1], 4000)], 1)

# ── ambience: crowd murmur + clinks + city hum ──
amb = np.zeros((N, 2))
for ch in range(2):
    n = rng.standard_normal(N)
    babble = sum(bp(n * (0.5 + 0.5 * np.sin(2 * np.pi * tt(N) * f + ch * 2 + k)) ** 2, lo, hi)
                 for k, (f, lo, hi) in enumerate([(3.1, 300, 900), (4.3, 500, 1500), (2.2, 900, 2600)]))
    amb[:, ch] = babble * .05 + lp(rng.standard_normal(N), 180) * .05
def clink():
    n = int(.6 * SR); f0 = rng.uniform(2400, 3600)
    return sum(np.sin(2 * np.pi * f0 * r * tt(n)) * np.exp(-tt(n) * (8 + 6 * i)) / (i + 1) for i, r in enumerate([1, 2.32, 3.7])) * .06
t = .8
while t < DUR - 1: add(amb, clink(), t, 1, rng.uniform(-.8, .8)); t += rng.uniform(1.4, 3.5)

# ── score: Dm–Bb–F–C lounge/cinematic, tension before reveal, lift at the end ──
mus = np.zeros((N, 2)); BPM = 96; beat = 60 / BPM; bar = 4 * beat
prog = [[50, 57, 62, 65], [46, 53, 58, 62], [41, 48, 57, 60], [48, 55, 60, 64]]
T = {e["type"]: e["t"] for e in ev["events"]}
rev = [e["t"] for e in ev["events"] if e["type"] == "reveal"][0]
risA = [e for e in ev["events"] if e["type"] == "riser"][0]
cta = [e["t"] for e in ev["events"] if e["type"] == "cta"][0]
def saw(f, n, det=0.0): ph = (np.cumsum(np.full(n, f * (1 + det))) / SR) % 1.0; return 2 * ph - 1
def pad(ch, n): x = sum(saw(note(m), n, d) for m in ch for d in (-.003, .003)); return lp(x, 1100) * .03
def pluck(f, n): x = np.zeros(n); x += np.sin(2 * np.pi * f * tt(n)) + .4 * np.sin(4 * np.pi * f * tt(n)); return x * np.exp(-tt(n) * 5) * .05
def kick(): n = int(.3 * SR); return np.sin(2 * np.pi * np.cumsum(45 + 90 * np.exp(-tt(n) * 30)) / SR) * np.exp(-tt(n) * 10) * .7
def hat(): n = int(.04 * SR); return hp(rng.standard_normal(n), 8000) * np.exp(-tt(n) * 80) * .15
K, Hh = kick(), hat()
nbar = int(DUR / bar) + 1
for i in range(nbar):
    t0 = i * bar; ch = prog[i % 4]; n = int(bar * SR)
    if t0 > DUR - 1: break
    tense = risA["t"] - 2 < t0 < rev
    e = np.minimum(1, tt(n) / .3) * np.minimum(1, (bar - tt(n)) / .15)
    add(mus, pad(ch, n) * e, t0, 1.0, -.3); add(mus, pad(ch, n) * e, t0 + .015, .8, .3)
    for q in range(8):  # bass + arpeggio
        nn = int(beat / 2 * SR); fb = note(ch[0] - 12)
        add(mus, np.sin(2 * np.pi * fb * tt(nn)) * np.exp(-tt(nn) * 4) * .22, t0 + q * beat / 2)
        if t0 > 2.5: add(mus, pluck(note(ch[(q * 3) % 4] + 12), int(.5 * SR)), t0 + q * beat / 2, 1, .5 * np.sin(q))
    for q in range(4):
        tb = t0 + q * beat
        if 2.5 < tb and not tense: add(mus, K, tb, .8); add(mus, Hh, tb + beat / 2, 1, .3)
        if tense: add(mus, K, tb, .5)
# silence the groove under the reveal hit, then sting
mute = np.ones(N); a, b = int((rev - .35) * SR), int((rev + .9) * SR); mute[a:b] = np.linspace(1, .15, b - a) ** 2; mus *= mute[:, None]
fade = np.ones(N); k = int(1.6 * SR); fade[-k:] = np.linspace(1, 0, k) ** 2; mus *= fade[:, None]; amb *= fade[:, None]

# ── SFX ──
sfx = np.zeros((N, 2))
def whoosh(d=.4):
    n = int(d * SR); x = rng.standard_normal(n); out = np.zeros(n)
    for j in range(0, n, 1024): f = 300 + 4500 * np.sin(np.pi * j / n) ** 2; out[j:j + 1024] = bp(x[j:j + 1024], f * .6, min(20000, f * 1.5), 1)
    return out * np.sin(np.pi * tt(n) / d) ** 2 * .35
def step(): n = int(.12 * SR); return lp(rng.standard_normal(n), 400) * np.exp(-tt(n) * 40) * .5 + bp(rng.standard_normal(n), 2000, 5000) * np.exp(-tt(n) * 120) * .15
def heel(): n = int(.1 * SR); return bp(rng.standard_normal(n), 2500, 7000) * np.exp(-tt(n) * 90) * .35 + np.sin(2 * np.pi * 1900 * tt(n)) * np.exp(-tt(n) * 60) * .12
def chair(): n = int(.45 * SR); return bp(rng.standard_normal(n), 300, 1400) * np.exp(-((tt(n) - .2) / .12) ** 2) * .25
def key(): n = int(.03 * SR); f = rng.uniform(2500, 4500); return bp(rng.standard_normal(n), f * .5, f) * np.exp(-tt(n) * 220) * rng.uniform(.2, .35)
def click(): n = int(.04 * SR); return bp(rng.standard_normal(n), 2000, 7000) * np.exp(-tt(n) * 160) * .5
def notif():
    n = int(.6 * SR); return (np.sin(2 * np.pi * 1318 * tt(n)) * (tt(n) < .12) + np.sin(2 * np.pi * 1760 * tt(n)) * (tt(n) >= .12)) * np.exp(-tt(n) * 7) * .12
def laptop(): n = int(.35 * SR); return bp(rng.standard_normal(n), 800, 3000) * np.exp(-tt(n) * 12) * .12 + np.sin(2 * np.pi * 523 * tt(n)) * np.exp(-tt(n) * 6) * .05
def riser(d):
    n = int(d * SR); x = hp(rng.standard_normal(n), 1500) * (tt(n) / d) ** 2 * .2
    return x + np.sin(2 * np.pi * np.cumsum(200 + 1400 * (tt(n) / d) ** 2) / SR) * (tt(n) / d) ** 2 * .12
def tick(): n = int(.03 * SR); return np.sin(2 * np.pi * 2400 * tt(n)) * np.exp(-tt(n) * 150) * .15
def reveal():
    n = int(2.2 * SR); x = tt(n); boom = np.sin(2 * np.pi * np.cumsum(32 + 80 * np.exp(-x * 14)) / SR) * np.exp(-x * 2.5)
    chord = sum(np.sin(2 * np.pi * note(m) * x) for m in [62, 66, 69, 74, 78]) * np.exp(-x * 1.6) * .08
    return boom * .8 + lp(rng.standard_normal(n), 2000) * np.exp(-x * 9) * .3 + chord
def crowd():
    n = int(1.4 * SR); x = tt(n); env = np.sin(np.pi * np.clip(x / 1.4, 0, 1)) ** 1.5
    return sum(bp(rng.standard_normal(n), lo, hi) for lo, hi in [(250, 700), (500, 1200)]) * env * .5
def stinger(): n = int(.8 * SR); x = tt(n); return sum(np.sin(2 * np.pi * note(m) * x) for m in [50, 56, 62]) * np.exp(-x * 4) * .14 + whoosh(.3)[:n].sum() * 0
def boing():
    n = int(.5 * SR); x = tt(n); f = 180 + 120 * np.sin(2 * np.pi * 9 * x) * np.exp(-x * 4)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-x * 5) * .25
def ctahit():
    n = int(1.2 * SR); x = tt(n); return sum(np.sin(2 * np.pi * note(m) * x) for m in [62, 69, 74, 77, 81]) * np.exp(-x * 2.5) * .07 + whoosh(.35).sum() * 0
def ending():
    n = int(1.4 * SR); x = tt(n); return np.sin(2 * np.pi * np.cumsum(40 + 60 * np.exp(-x * 8)) / SR) * np.exp(-x * 3) * .6 + hp(rng.standard_normal(n), 3000) * np.exp(-x * 4) * .08
for e in ev["events"]:
    t, ty = e["t"], e["type"]
    if ty == "whoosh": add(sfx, whoosh(), t - .2, .9)
    elif ty == "cut": add(sfx, whoosh(.18), t - .09, .25)
    elif ty == "step": add(sfx, step(), t, .8, .5)
    elif ty == "heel": add(sfx, heel(), t, .7, .2)
    elif ty == "chair": add(sfx, chair(), t, 1.0)
    elif ty == "laptop": add(sfx, laptop(), t, 1.0)
    elif ty == "click": add(sfx, click(), t, 1.0)
    elif ty == "send": add(sfx, whoosh(.2), t, .5)
    elif ty == "notif": add(sfx, notif(), t, 1.0)
    elif ty == "riser": add(sfx, riser(e["t1"] - t + .7), t, 1.0)
    elif ty == "reveal": add(sfx, reveal(), t, 1.0)
    elif ty == "crowd": add(sfx, crowd(), t, .9)
    elif ty == "stinger": add(sfx, stinger(), t, 1.0)
    elif ty == "boing": add(sfx, boing(), t, .8)
    elif ty == "cta": add(sfx, ctahit(), t, 1.0); add(sfx, whoosh(.3), t - .1, .5)
    elif ty == "end": add(sfx, ending(), t, 1.0)
    elif ty in ("type", "stream", "tick"):
        x = t; stp = {"type": .07, "stream": .1, "tick": .09}[ty]
        while x < e["t1"]:
            add(sfx, tick() if ty == "tick" else key(), x, .6 if ty != "stream" else .25, rng.uniform(-.3, .3)); x += stp * rng.uniform(.6, 1.4)

# ── ducking & master ──
ve = movavg(np.abs(voice), int(.05 * SR)); act = movavg(np.clip(ve / (ve.max() + 1e-9) * 10, 0, 1), int(.25 * SR))
duck = 1 - .6 * np.clip(act, 0, 1)
mix = mus * (.75 * duck)[:, None] + amb * (.8 * (1 - .4 * act))[:, None] + sfx * .7 + dlg * 1.0
mix = np.tanh(mix * 1.05) / 1.05
sf.write(os.path.join(B, "mix.wav"), mix.astype(np.float32), SR); print("mix ok", np.abs(mix).max())
