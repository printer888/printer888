"""Procedural soundtrack: original synth-pop bed + SFX placed from the renderer's
event list (build/events.json) + narration, with sidechain ducking.
Everything is synthesised here, so there are no licensing issues.
Output: build/mix.wav (48 kHz stereo)."""
import json, os
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, "build")
SR = 48000
rng = np.random.default_rng(7)

ev = json.load(open(os.path.join(B, "events.json")))
DUR = ev["duration"]; N = int(DUR * SR)
voice, vsr = sf.read(os.path.join(B, "narration.wav"))
voice = resample_poly(voice, SR, vsr)[:N]; voice = np.pad(voice, (0, N - len(voice)))

def lp(x, f, o=2): return sosfilt(butter(o, f, "low", fs=SR, output="sos"), x)
def hp(x, f, o=2): return sosfilt(butter(o, f, "high", fs=SR, output="sos"), x)
def bp(x, a, b, o=2): return sosfilt(butter(o, [a, b], "band", fs=SR, output="sos"), x)
def env(n, a, d):
    e = np.ones(n); ka = max(1, int(a * SR)); e[:ka] = np.linspace(0, 1, ka)
    return e * np.exp(-np.arange(n) / SR / d) if d else e
def t_(n): return np.arange(n) / SR
def add(buf, x, t, g=1.0, pan=0.0):
    i = int(t * SR)
    if i >= len(buf) or i + len(x) <= 0: return
    if i < 0: x = x[-i:]; i = 0
    x = x[: len(buf) - i]
    buf[i:i + len(x), 0] += x * g * np.sqrt(0.5 * (1 - pan)) * 1.414
    buf[i:i + len(x), 1] += x * g * np.sqrt(0.5 * (1 + pan)) * 1.414

# ── music ──
BPM = 116; beat = 60 / BPM; bar = 4 * beat
mus = np.zeros((N, 2))
def note(m): return 440 * 2 ** ((m - 69) / 12)
prog = [[57, 60, 64, 69], [53, 57, 60, 65], [48, 52, 55, 60], [55, 59, 62, 67]]  # Am F C G
bass = [45, 41, 36, 43]
def saw(f, n, det=0.0):
    ph = (np.cumsum(np.full(n, f * (1 + det))) / SR) % 1.0
    return 2 * ph - 1
def kick():
    n = int(0.35 * SR); tt = t_(n); f = 45 + 110 * np.exp(-tt * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9) * 0.9
def hat(o=False):
    n = int((0.18 if o else 0.05) * SR); return hp(rng.standard_normal(n), 7000) * np.exp(-t_(n) * (18 if o else 70)) * 0.25
def clap():
    n = int(0.25 * SR); x = bp(rng.standard_normal(n), 900, 2600) * np.exp(-t_(n) * 18)
    return x * 0.5
K, H, HO, C = kick(), hat(), hat(True), clap()
nb = int(DUR / beat) + 2
for b in range(nb):
    tb = b * beat
    section = 0 if tb < 2.9 else 1  # sparse under the hook
    if tb > DUR - 1.2: break
    if section or b % 2 == 0: add(mus, K, tb, 0.9)
    if section and b % 2 == 1: add(mus, C, tb, 0.55, 0.1)
    if section:
        add(mus, H, tb + beat / 2, 0.8, 0.3); add(mus, H, tb, 0.45, -0.3)
        if b % 4 == 3: add(mus, HO, tb + beat / 2, 0.6, 0.3)
# pads, bass, arp
nbar = int(DUR / bar) + 1
for i in range(nbar):
    tb = i * bar; ch = prog[i % 4]; n = int(bar * SR)
    pad = sum(saw(note(m), n, d) for m in ch for d in (-0.004, 0.004))
    pad = lp(pad, 1400 + 600 * np.sin(i)) * 0.045
    e = np.minimum(1, t_(n) / 0.25) * np.minimum(1, (bar - t_(n)) / 0.1)
    add(mus, pad * e, tb, 1.0, -0.2); add(mus, pad * e, tb + 0.012, 0.8, 0.4)
    for q in range(8):
        nn = int(beat / 2 * SR); f = note(bass[i % 4])
        x = (np.sin(2 * np.pi * f * t_(nn)) + 0.3 * lp(saw(f, nn), 500)) * env(nn, 0.005, 0.18) * 0.32
        add(mus, x, tb + q * beat / 2)
    if tb > 2.9:
        arp = ch + [ch[1] + 12, ch[2] + 12, ch[3] + 12, ch[2] + 12]
        for q in range(16):
            nn = int(beat / 4 * SR * 1.6); f = note(arp[q % len(arp)] + 12)
            x = lp(saw(f, nn) + saw(f, nn, 0.006), 3500) * env(nn, 0.003, 0.09) * 0.05
            add(mus, x, tb + q * beat / 4, 1.0, 0.5 * np.sin(q))
# end: let the last chord ring, fade
fade = np.ones(N); k = int(1.5 * SR); fade[-k:] = np.linspace(1, 0, k) ** 2
mus *= fade[:, None]

# ── SFX ──
sfx = np.zeros((N, 2))
def whoosh(d=0.45):
    n = int(d * SR); x = rng.standard_normal(n); tt = t_(n)
    out = np.zeros(n); seg = 512
    for j in range(0, n, seg):
        f = 300 + 5000 * np.sin(np.pi * j / n) ** 2
        out[j:j + seg] = bp(x[j:j + seg + 0], max(100, f * 0.6), min(20000, f * 1.4), 1)
    return lp(out, 9000) * np.sin(np.pi * tt / d) ** 2 * 0.55
def click():
    n = int(0.04 * SR); return (bp(rng.standard_normal(n), 2000, 7000) * np.exp(-t_(n) * 160) + np.sin(2 * np.pi * 1800 * t_(n)) * np.exp(-t_(n) * 120) * 0.5) * 0.6
def key():
    n = int(0.03 * SR); f = rng.uniform(2500, 4500)
    return (bp(rng.standard_normal(n), f * 0.5, f) * np.exp(-t_(n) * 220)) * rng.uniform(0.25, 0.45)
def pop():
    n = int(0.12 * SR); f = 500 + 900 * np.exp(-t_(n) * 40)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t_(n) * 30) * 0.35
def ding(f0=1320):
    n = int(0.9 * SR); tt = t_(n)
    return (np.sin(2 * np.pi * f0 * tt) + 0.5 * np.sin(2 * np.pi * f0 * 1.5 * tt) + 0.25 * np.sin(2 * np.pi * f0 * 2 * tt)) * np.exp(-tt * 5) * 0.16
def impact():
    n = int(0.9 * SR); tt = t_(n); f = 38 + 120 * np.exp(-tt * 18)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 4) * 0.9 + lp(rng.standard_normal(n), 1500) * np.exp(-tt * 14) * 0.5)
def rise(d=0.35):
    n = int(d * SR); tt = t_(n); x = hp(rng.standard_normal(n), 2000) * (tt / d) ** 2 * 0.25
    return x + np.sin(2 * np.pi * np.cumsum(300 + 1500 * (tt / d) ** 2) / SR) * (tt / d) ** 2 * 0.1
def sparkle():
    out = np.zeros(int(0.7 * SR))
    for j, m in enumerate([84, 88, 91, 96, 100]):
        x = np.sin(2 * np.pi * note(m) * t_(int(0.4 * SR))) * np.exp(-t_(int(0.4 * SR)) * 9) * 0.07
        s = int(j * 0.05 * SR); out[s:s + len(x)] += x
    return out
def buzz():
    n = int(0.22 * SR); return lp(saw(110, n) + saw(116, n), 1800) * env(n, 0.005, 0.12) * 0.2
def send():
    n = int(0.25 * SR); tt = t_(n); f = 600 + 1400 * tt / 0.25
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 12) * 0.25 + whoosh(0.25) * 0.3

for e in ev["events"]:
    T, ty = e["t"], e["type"]
    if ty == "whoosh": add(sfx, whoosh(), T - 0.15, 0.55)
    elif ty == "click": add(sfx, click(), T, 0.7, 0.2)
    elif ty == "pop": add(sfx, pop(), T, 0.6, rng.uniform(-.3, .3))
    elif ty == "ding": add(sfx, ding(), T, 0.8)
    elif ty == "stamp": add(sfx, impact(), T, 0.55); add(sfx, click(), T, 0.6)
    elif ty == "impact": add(sfx, impact(), T, 0.5)
    elif ty == "boom": add(sfx, impact(), T, 0.6); add(sfx, sparkle(), T + 0.05, 0.9)
    elif ty == "rise": add(sfx, rise(), T, 0.8)
    elif ty == "sparkle": add(sfx, sparkle(), T, 0.9)
    elif ty == "buzz": add(sfx, buzz(), T, 0.5)
    elif ty == "send": add(sfx, send(), T, 0.6)
    elif ty in ("type", "stream"):
        tt = T; step = 0.075 if ty == "type" else 0.11
        while tt < e["t1"]:
            add(sfx, key(), tt, 0.55 if ty == "type" else 0.18, rng.uniform(-.4, .4)); tt += step * rng.uniform(0.6, 1.4)

# ── ducking: music sits ~-9 dB under the voice while it speaks ──
def movavg(x, k):
    c = np.cumsum(np.concatenate([[0], x])); y = (c[k:] - c[:-k]) / k
    return np.pad(y, (k // 2, len(x) - len(y) - k // 2), mode="edge")
ve = np.abs(voice); k = int(0.05 * SR)
ve = movavg(ve, k); ve = ve / (ve.max() + 1e-9)
act = np.clip(ve * 8, 0, 1)
k2 = int(0.25 * SR); act = movavg(act, k2)
duck = 1 - 0.62 * np.clip(act, 0, 1)
mix = mus * (0.55 * duck)[:, None] + sfx * 0.55 + np.stack([voice, voice], 1) * 1.0
mix = np.tanh(mix * 1.1) / 1.1  # gentle soft-clip safety
sf.write(os.path.join(B, "mix.wav"), mix.astype(np.float32), SR)
print("mix ok", mix.shape, np.abs(mix).max())
