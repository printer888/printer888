"""Original music + sound design, synthesised from scratch with numpy (no samples,
no third-party recordings → fully owned / licence-free).

Music: atmospheric melodic hip-hop, ~80 BPM, minor-key Rhodes-style keys, warm pad,
808 bass, half-time drums, hats with rolls. Tempo is nudged so that a bar downbeat
lands exactly on "Forty." — the drop.

Output: build/music.wav, build/sfx.wav, build/mix.wav (48 kHz stereo, voice-ducked)
"""
import json, os
import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, "build")
SR = 48000
tl = json.load(open(os.path.join(B, "timeline.json")))
lines = {l["scene"]: l for l in json.load(open(os.path.join(B, "lines.json")))}
DUR = tl["duration"]
N = int(DUR * SR) + SR
rng = np.random.default_rng(3)


def lp(x, fc):
    """one-pole low-pass (vectorised via lfilter-like recursion in chunks)."""
    a = np.exp(-2 * np.pi * fc / SR)
    from scipy.signal import lfilter
    return lfilter([1 - a], [1, -a], x)


def hp(x, fc):
    return x - lp(x, fc)


def env_adsr(n, a, d, s, r, sus_len):
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    sl = max(0, int(sus_len * SR) - a - d)
    e = np.concatenate([np.linspace(0, 1, a, endpoint=False), np.linspace(1, s, d, endpoint=False),
                        np.full(sl, s), np.linspace(s, 0, r)])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def add(buf, sig, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= len(buf) or i + len(sig) <= 0:
        return
    if i < 0:
        sig = sig[-i:]; i = 0
    sig = sig[: len(buf) - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * gain * l * 1.414
    buf[i:i + len(sig), 1] += sig * gain * r * 1.414


def mtof(m):
    return 440 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- instruments
def keys(freq, dur):
    n = int((dur + 1.2) * SR); t = np.arange(n) / SR
    s = (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-t * 3)
         + 0.12 * np.sin(2 * np.pi * 3 * freq * t) * np.exp(-t * 6))
    s *= 1 + 0.15 * np.sin(2 * np.pi * 4.5 * t)  # tremolo
    return s * env_adsr(n, 0.005, 0.6, 0.45, 1.1, dur) * 0.22


def pad(freq, dur):
    n = int((dur + 1.5) * SR); t = np.arange(n) / SR
    s = np.zeros(n)
    for det in (-0.09, 0.0, 0.08):
        ph = 2 * np.pi * freq * (1 + det / 100 * 6) * t + rng.uniform(0, 6)
        s += 2 * ((ph / (2 * np.pi)) % 1) - 1  # saw
    s = lp(lp(s, 900), 1400)
    return s * env_adsr(n, 0.8, 0.5, 0.8, 1.4, dur) * 0.06


def bass808(freq, dur):
    n = int((dur + 0.3) * SR); t = np.arange(n) / SR
    f = freq * (1 + 1.6 * np.exp(-t * 28))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.tanh(1.8 * np.sin(ph))
    return s * env_adsr(n, 0.002, 0.25, 0.7, 0.25, dur) * 0.5


def kick():
    n = int(0.35 * SR); t = np.arange(n) / SR
    f = 50 + 120 * np.exp(-t * 35)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
    s[:200] += rng.normal(0, 0.4, 200) * np.linspace(1, 0, 200)
    return np.tanh(s * 1.5) * 0.55


def clap():
    n = int(0.4 * SR); t = np.arange(n) / SR
    nz = rng.normal(0, 1, n)
    nz = hp(lp(nz, 5000), 900)
    e = np.exp(-t * 18)
    for k in (0.0, 0.011, 0.022):
        e += np.where(t >= k, np.exp(-(t - k) * 120), 0) * 0.6
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30) * 0.3
    return (nz * e + body) * 0.35


def hat(open_=False):
    n = int((0.25 if open_ else 0.06) * SR); t = np.arange(n) / SR
    s = hp(rng.normal(0, 1, n), 7000)
    return s * np.exp(-t * (14 if open_ else 70)) * 0.16


def pluck(freq, dur=0.5):
    n = int((dur + 0.6) * SR); t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t + 1.2 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-t * 8))
    return s * np.exp(-t * 5) * 0.13


# ---------------------------------------------------------------- arrangement
t_drop = lines["forty"]["wstart"] - 0.02
bars_before = round(t_drop / 3.0)
BAR = t_drop / bars_before  # ~3 s per bar → ~80 BPM
BEAT = BAR / 4
t_build = lines["who"]["start"] - 0.1
t_strip = lines["end1"]["wstart"] - 0.25
t_out = tl["shots"][-1]["start"]
print(f"BPM {60 / BEAT:.2f} bar {BAR:.3f}s drop {t_drop:.2f}")

# Cm9 – Abmaj7 – Ebmaj7 – Bb6/D   (one per bar)
CHORDS = [
    (48, [60, 63, 67, 70, 74]),
    (44, [60, 63, 67, 72, 70]),
    (51, [58, 62, 63, 67, 70]),
    (46, [58, 62, 65, 67, 74]),
]
MEL = [[(0, 75), (1.5, 74), (2.5, 70)], [(0, 72), (2, 75), (3, 77)],
       [(0, 79), (1.5, 77), (2.5, 75)], [(0, 74), (2, 70)]]

music = np.zeros((N, 2))
nbars = int(np.ceil(DUR / BAR)) + 1
for b in range(nbars):
    t0 = b * BAR
    if t0 > DUR:
        break
    root, notes = CHORDS[b % 4]
    full = t_drop - 0.01 <= t0 < t_strip
    build = t_build <= t0 < t_drop - 0.01
    outro = t0 >= t_strip
    # keys: two stabs per bar
    for k_i, kt in enumerate((0, 2.5)):
        for j, m in enumerate(notes):
            add(music, keys(mtof(m), BEAT * (2.4 if k_i == 0 else 1.4)), t0 + kt * BEAT + j * 0.012,
                0.7 if not full else 0.85, pan=(j - 2) * 0.25)
    for m in notes[:3]:
        add(music, pad(mtof(m - 12), BAR), t0, 1.0, pan=0)
    if build or full:
        # 808 on root
        pattern = [(0, 1.4), (2.5, 0.8)] if build else [(0, 1.2), (1.5, 0.4), (2.5, 0.9), (3.5, 0.4)]
        for bt, ln in pattern:
            add(music, bass808(mtof(root - 12 if root > 45 else root), ln * BEAT), t0 + bt * BEAT,
                0.55 if build else 0.8)
        # hats
        step = 0.5 if build else 0.25
        h = 0.0
        while h < 4:
            vel = 0.7 if (h * 2) % 2 == 0 else 0.45
            add(music, hat(), t0 + h * BEAT, vel * (0.7 if build else 1), pan=0.3)
            h += step
        if full and b % 2 == 1:  # hat roll
            for r in range(6):
                add(music, hat(), t0 + 3.5 * BEAT + r * BEAT / 12, 0.5, pan=0.3)
        add(music, hat(True), t0 + 3 * BEAT, 0.6, pan=-0.3)
    if full:
        add(music, kick(), t0, 1.0)
        add(music, kick(), t0 + 1.75 * BEAT, 0.7)
        add(music, clap(), t0 + 2 * BEAT, 1.0, pan=0.05)
        for bt, m in MEL[b % 4]:
            add(music, pluck(mtof(m + 12)), t0 + bt * BEAT, 1.0, pan=-0.35)
            add(music, pluck(mtof(m + 12)), t0 + bt * BEAT + BEAT * 0.75, 0.35, pan=0.45)  # echo
    if build and b % 2 == 1:
        add(music, clap(), t0 + 2 * BEAT, 0.45)
    if outro and t0 < t_out:
        add(music, kick(), t0, 0.5)

# vinyl/air texture
air = lp(rng.normal(0, 1, N), 3000) * 0.006
music[:, 0] += air; music[:, 1] += np.roll(air, 333)
# global music fade-in / out
fade = np.ones(N)
fi = int(1.2 * SR); fade[:fi] = np.linspace(0.35, 1, fi)
fo0 = int((DUR - 1.4) * SR); fade[fo0:] = np.linspace(1, 0, N - fo0) ** 1.5
# lift on drop: slightly louder from drop to strip
lift = np.ones(N)
a0, a1 = int(t_drop * SR), int(t_strip * SR)
lift[a0:a1] = 1.25
music *= (fade * lift)[:, None]

# ---------------------------------------------------------------- SFX
sfx = np.zeros((N, 2))


def whoosh(d=0.45):
    n = int(d * SR); t = np.arange(n) / SR
    nz = rng.normal(0, 1, n)
    out = np.zeros(n)
    # sweeping band: crossfade of differently filtered noise
    lo, hi = lp(nz, 600), lp(nz, 4000)
    x = t / d
    out = lo * (1 - x) + hi * x
    e = np.sin(np.pi * x) ** 2
    return hp(out, 150) * e * 0.35


def impact(big=True):
    n = int(1.4 * SR); t = np.arange(n) / SR
    f = 42 + 90 * np.exp(-t * 18)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (3 if big else 6))
    crack = hp(rng.normal(0, 1, n), 1500) * np.exp(-t * 40) * 0.5
    tail = lp(rng.normal(0, 1, n), 1200) * np.exp(-t * 4) * 0.15
    return np.tanh((boom + crack + tail) * 1.4) * (0.6 if big else 0.4)


def ping(soft=False):
    n = int(0.7 * SR); t = np.arange(n) / SR
    f1, f2 = (1568, 2093) if not soft else (1319, 1760)
    s = np.sin(2 * np.pi * f1 * t) * np.exp(-t * 9) * (t < 0.09)
    s += np.where(t >= 0.09, np.sin(2 * np.pi * f2 * (t - 0.09)) * np.exp(-(t - 0.09) * 7), 0)
    return s * (0.10 if soft else 0.14)


def key():
    n = int(0.05 * SR); t = np.arange(n) / SR
    s = hp(rng.normal(0, 1, n), 2500) * np.exp(-t * 160)
    s += np.sin(2 * np.pi * rng.uniform(180, 260) * t) * np.exp(-t * 120) * 0.4
    return s * rng.uniform(0.08, 0.13)


def riser(d):
    n = int(d * SR); t = np.arange(n) / SR
    nz = rng.normal(0, 1, n)
    x = t / d
    s = lp(nz, 800) * (1 - x) + hp(nz, 2500) * x
    tone = np.sin(2 * np.pi * np.cumsum(200 + 900 * x ** 2) / SR) * 0.15
    return (s * 0.6 + tone) * x ** 2 * 0.22


def stamp():
    n = int(0.6 * SR); t = np.arange(n) / SR
    s = np.sin(2 * np.pi * np.cumsum(90 + 120 * np.exp(-t * 50)) / SR) * np.exp(-t * 14)
    s += lp(rng.normal(0, 1, n), 2500) * np.exp(-t * 35) * 0.7
    return np.tanh(s * 2) * 0.45


def shimmer():
    n = int(2.0 * SR); t = np.arange(n) / SR
    s = np.zeros(n)
    for i, m in enumerate([84, 87, 91, 94, 98]):
        s += np.where(t > i * 0.06, np.sin(2 * np.pi * mtof(m) * (t - i * 0.06)) * np.exp(-(t - i * 0.06) * 2.5), 0)
    return s * 0.05


for c in tl["cues"]:
    ty, t = c["type"], c["t"]
    if ty == "whoosh":
        add(sfx, whoosh(), t - 0.2, 0.9, pan=rng.uniform(-0.4, 0.4))
    elif ty == "impact":
        add(sfx, impact(bool(c.get("big"))), t, 1.0)
    elif ty == "ping":
        add(sfx, ping(bool(c.get("soft"))), t, 1.0, pan=rng.uniform(-0.3, 0.3))
    elif ty == "key":
        add(sfx, key(), t, 1.0, pan=rng.uniform(-0.15, 0.15))
    elif ty == "riser":
        add(sfx, riser(c["dur"]), t, 1.0)
    elif ty == "stamp":
        add(sfx, stamp(), t, 1.0)
    elif ty == "shimmer":
        add(sfx, shimmer(), t, 1.0)

# city ambience under apartment / skyline shots
amb_types = {"apt_phone", "apt_lean", "apt_direct", "apt_smile", "skyline_back", "car_drive", "lobby_walk", "car_inside"}
amb = lp(np.cumsum(rng.normal(0, 1, N)) * 0.002, 400)
amb = amb - lp(amb, 40)
amb = np.stack([amb, np.roll(amb, 2400)], 1) * 0.5
mask = np.zeros(N)
for s in tl["shots"]:
    if s["type"] in amb_types:
        mask[int(s["start"] * SR):int(s["end"] * SR)] = 1
mask = lp(lp(mask, 3), 3)
sfx += amb * mask[:, None] * 2.0

# ---------------------------------------------------------------- mix + ducking
from scipy.signal import resample_poly
v, vsr = sf.read(os.path.join(B, "voice.wav"))
v = resample_poly(v, SR, vsr)
voice = np.zeros(N); voice[:len(v)] = v
venv = lp(np.abs(voice), 8)
venv = venv / (venv.max() + 1e-9)
duck = 1 - 0.55 * np.clip(venv * 3, 0, 1)
duck = lp(duck, 6)

music_gain = 10 ** (-17 / 20)
sfx_gain = 10 ** (-6 / 20)
mix = voice[:, None] * 1.0 + music * music_gain * duck[:, None] * 1.0 + sfx * sfx_gain
# gentle peak control
peak = np.abs(mix).max()
mix = np.tanh(mix / peak * 1.1) * 0.95 if peak > 0.98 else mix
n_out = int(DUR * SR)
for name, arr in (("music", music * music_gain), ("sfx", sfx * sfx_gain), ("mix", mix)):
    sf.write(os.path.join(B, name + ".wav"), arr[:n_out].astype(np.float32), SR)
print("audio done", n_out / SR)
