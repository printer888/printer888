"""Max EP soundtrack: original lo-fi bed + room tone + UI SFX on the renderer's cue list
+ host voice; music side-chain ducked under speech.  Output build/mix.wav (48k stereo)."""
import json, os
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); B = os.path.join(ROOT, "build")
SR = 48000; rng = np.random.default_rng(5)
ev = json.load(open(os.path.join(B, "events.json"))); DUR = ev["duration"]; N = int(DUR * SR)
def lp(x, f): return sosfilt(butter(2, f, "low", fs=SR, output="sos"), x)
def hp(x, f): return sosfilt(butter(2, f, "high", fs=SR, output="sos"), x)
def bp(x, a, b): return sosfilt(butter(2, [a, b], "band", fs=SR, output="sos"), x)
def tt(n): return np.arange(n) / SR
def note(m): return 440 * 2 ** ((m - 69) / 12)
def add(buf, x, t, g=1.0, pan=0.0):
    i = int(t * SR)
    if i >= len(buf) or i + len(x) <= 0: return
    if i < 0: x = x[-i:]; i = 0
    x = x[:len(buf) - i]; buf[i:i + len(x), 0] += x * g * np.sqrt(1 - pan); buf[i:i + len(x), 1] += x * g * np.sqrt(1 + pan)
def movavg(x, k):
    c = np.cumsum(np.concatenate([[0], x])); y = (c[k:] - c[:-k]) / k
    return np.pad(y, (k // 2, len(x) - len(y) - k // 2), mode="edge")
voice, vsr = sf.read(os.path.join(B, "dialogue.wav")); voice = resample_poly(voice, SR, vsr)[:N]; voice = np.pad(voice, (0, N - len(voice)))
# lo-fi bed: Fmaj7 - Em7 - Dm7 - Cmaj7, 88 BPM, soft keys + sub + dusty drums + vinyl hiss
mus = np.zeros((N, 2)); BPM = 88; beat = 60 / BPM; bar = 4 * beat
prog = [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]]
def keys(m, n): x = tt(n); f = note(m); return (np.sin(2 * np.pi * f * x) + .3 * np.sin(4 * np.pi * f * x) * np.exp(-x * 3)) * np.exp(-x * 1.2) * .045
def kick(): n = int(.3 * SR); x = tt(n); return np.sin(2 * np.pi * np.cumsum(48 + 80 * np.exp(-x * 30)) / SR) * np.exp(-x * 9) * .6
def snare(): n = int(.25 * SR); x = tt(n); return bp(rng.standard_normal(n), 1200, 5000) * np.exp(-x * 16) * .22 + np.sin(2 * np.pi * 190 * x) * np.exp(-x * 20) * .1
def hat(): n = int(.05 * SR); return hp(rng.standard_normal(n), 7000) * np.exp(-tt(n) * 60) * .08
K, S_, H = kick(), snare(), hat()
for i in range(int(DUR / bar) + 1):
    t0 = i * bar; ch = prog[i % 4]
    if t0 > DUR - 1: break
    for m in ch: add(mus, keys(m, int(bar * SR)), t0 + .01 * rng.random(), 1, rng.uniform(-.4, .4))
    add(mus, np.sin(2 * np.pi * note(ch[0] - 24) * tt(int(bar * SR))) * np.exp(-tt(int(bar * SR)) * .8) * .2, t0)
    for q in range(4):
        tb = t0 + q * beat
        add(mus, K, tb + (0 if q % 2 == 0 else beat * .5) * (q == 2), .9) if q in (0, 2) else add(mus, S_, tb, .9)
        add(mus, H, tb + beat * .5 + .02, 1, .3); add(mus, H, tb, .6, -.3)
mus[:, 0] += lp(rng.standard_normal(N), 6000) * .006; mus[:, 1] += lp(rng.standard_normal(N), 6000) * .006
fade = np.ones(N); k = int(1.2 * SR); fade[-k:] = np.linspace(1, 0, k) ** 2; fade[:int(.3 * SR)] = np.linspace(0, 1, int(.3 * SR)); mus *= fade[:, None]
# sfx
sfx = np.zeros((N, 2))
def pop(): n = int(.12 * SR); x = tt(n); return np.sin(2 * np.pi * np.cumsum(500 + 900 * np.exp(-x * 40)) / SR) * np.exp(-x * 30) * .3
def swoosh(d=.3):
    n = int(d * SR); x = rng.standard_normal(n); out = np.zeros(n)
    for j in range(0, n, 1024): f = 400 + 4000 * np.sin(np.pi * j / n) ** 2; out[j:j + 1024] = bp(x[j:j + 1024], f * .6, min(20000, f * 1.5))
    return out * np.sin(np.pi * tt(n) / d) ** 2 * .3
def click(): n = int(.04 * SR); return bp(rng.standard_normal(n), 2000, 7000) * np.exp(-tt(n) * 160) * .45
def key(): n = int(.03 * SR); f = rng.uniform(2500, 4500); return bp(rng.standard_normal(n), f * .5, f) * np.exp(-tt(n) * 220) * rng.uniform(.18, .3)
def ding(): n = int(.7 * SR); x = tt(n); return (np.sin(2 * np.pi * 1318 * x) + .5 * np.sin(2 * np.pi * 1976 * x)) * np.exp(-x * 6) * .12
def buzz(): n = int(.25 * SR); x = tt(n); ph = (np.cumsum(np.full(n, 110.0)) / SR) % 1; return lp(2 * ph - 1, 1500) * np.exp(-x * 8) * .25
def tick(): n = int(.06 * SR); x = tt(n); return np.sin(2 * np.pi * 1600 * x) * np.exp(-x * 60) * .2
def send(): n = int(.25 * SR); x = tt(n); return np.sin(2 * np.pi * np.cumsum(600 + 1600 * x / .25) / SR) * np.exp(-x * 12) * .18
def rise(): n = int(1.2 * SR); x = tt(n); return np.sin(2 * np.pi * np.cumsum(300 + 900 * x / 1.2) / SR) * (x / 1.2) * np.exp(-np.maximum(0, x - 1) * 20) * .08
def boom(): n = int(1.0 * SR); x = tt(n); return np.sin(2 * np.pi * np.cumsum(45 + 90 * np.exp(-x * 12)) / SR) * np.exp(-x * 4) * .5 + sum(np.sin(2 * np.pi * note(m) * x) for m in [72, 76, 79, 84]) * np.exp(-x * 3) * .05
for e in ev["events"]:
    t, ty = e["t"], e["type"]
    if ty == "pop": add(sfx, pop(), t, 1, rng.uniform(-.3, .3))
    elif ty in ("swoosh", "whoosh"): add(sfx, swoosh(), t - .1, .9)
    elif ty == "click": add(sfx, click(), t, 1)
    elif ty == "ding": add(sfx, ding(), t, 1)
    elif ty == "buzz": add(sfx, buzz(), t, 1)
    elif ty == "tick": add(sfx, tick(), t, 1)
    elif ty == "send": add(sfx, send(), t, 1)
    elif ty == "rise": add(sfx, rise(), t, 1)
    elif ty in ("boom", "end"): add(sfx, boom(), t, 1 if ty == "boom" else .7)
    elif ty == "type":
        x = t
        while x < e["t1"]: add(sfx, key(), x, 1, rng.uniform(-.3, .3)); x += .07 * rng.uniform(.6, 1.4)
room = np.stack([lp(rng.standard_normal(N), 300) * .012] * 2, 1)
ve = movavg(np.abs(voice), int(.05 * SR)); act = movavg(np.clip(ve / ve.max() * 10, 0, 1), int(.25 * SR))
mix = mus * (.8 * (1 - .6 * act))[:, None] + sfx * .7 + room + np.stack([voice, voice], 1)
mix = np.tanh(mix * 1.05) / 1.05
sf.write(os.path.join(B, "mix.wav"), mix.astype(np.float32), SR); print("mix ok", np.abs(mix).max())
